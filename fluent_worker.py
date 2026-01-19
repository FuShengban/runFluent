import ansys.fluent.core as pyfluent
import psutil
import time
import shutil
import threading
import os
import re
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from config import (
    FLUENT_DIMENSION, FLUENT_PROCESSORS,
    TIME_STEP_SIZE, WARM_STEPS, SAMPLING_STEPS_INIT, SAMPLING_STEPS_INTERVAL, GUI_FLAG,
    MOVE_MESH_AFTER_RUN,
    SERVER_HOST, SERVER_PORT,
    NAS_ENABLE,
    NAS_RESULTS_PATH,  # 新增：NAS结果目录的SFTP路径
    NAS_DELETE_LOCAL_AFTER_UPLOAD,
    NAS_UPLOAD_IDLE_SLEEP_SEC,
    NAS_UPLOAD_RETRIES, NAS_UPLOAD_BASE_BACKOFF_SEC,
    NAS_UPLOAD_EXT_WHITELIST,
    CONV_SKIP_STEPS,
    CONV_TAIL_LENGTH,
    CONV_RANGE_THRESHOLD,
    CASE_DONE_SIGNAL_FILE,
    FLUENT_RESULT_FILE_PATTERNS,
)
from sftp_utils import (
    sftp_upload_file, sftp_exists, sftp_rename, 
    sftp_remove_file, _connect, _sftp_makedirs
)
from protocol import request


def build_fluent_result_files(out_dir: Path, stem: str) -> list[Path]:
    return [
        out_dir / pattern.format(stem=stem)
        for pattern in FLUENT_RESULT_FILE_PATTERNS
    ]

def result_is_convergence(cd_out_path: str, cl_out_path: str) -> bool:
    """
    1) 读取 cd/cl 的 .out 文件数值序列（每行取最后一个可解析数字）
    2) 跳过前 CONV_SKIP_STEPS 个点（burn-in）
    3) 对剩余序列计算“累计均值序列” mean[i] = avg(x[0:i+1])（O(n) running sum）
    4) 取累计均值序列最后 CONV_TAIL_LENGTH 个点，若长度 > CONV_MIN_POINTS，
       且 (max-min) < CONV_RANGE_THRESHOLD，则判为稳定
    5) cd 和 cl 都稳定才算收敛
    """

    def _read_last_number_series(path: str) -> List[float]:
        vals: List[float] = []
        with open(path, "r") as f:
            for line in f:
                parts = [p for p in re.split(r"[^0-9+-.eE]+", line.strip()) if p]
                if not parts:
                    continue
                try:
                    vals.append(float(parts[-1]))
                except Exception:
                    continue
        return vals

    def _cumulative_mean_after_skip(x: List[float], skip: int) -> List[float]:
        if not x:
            return []
        if skip < 0:
            skip = 0
        if skip >= len(x):
            return []

        tail = x[skip:]
        out: List[float] = []
        s = 0.0
        for i, v in enumerate(tail, start=1):
            s += v
            out.append(s / i)
        return out

    try:
        cd = _read_last_number_series(cd_out_path)
        cl = _read_last_number_series(cl_out_path)

        cd_mean = _cumulative_mean_after_skip(cd, CONV_SKIP_STEPS)
        cl_mean = _cumulative_mean_after_skip(cl, CONV_SKIP_STEPS)

        cd_slice = cd_mean[-CONV_TAIL_LENGTH:]
        cl_slice = cl_mean[-CONV_TAIL_LENGTH:]

        flag_cd = (max(cd_slice) - min(cd_slice)) < CONV_RANGE_THRESHOLD
        flag_cl = (max(cl_slice) - min(cl_slice)) < CONV_RANGE_THRESHOLD

        return flag_cd and flag_cl

    except Exception as e:
        print(f"result_is_convergence error: {e}")
        return False



class FluentWorker:
    """
    (1) 上传队列去重：同 case_key 只入队一次
    (2) Z盘不可用时不刷屏/不疯狂失败：直接睡眠，保留队列等待恢复
    (3) 云端表体现：uploading / uploaded / last_error / uploaded_at
    (5) 原子上传：先拷贝到临时目录，再 rename 到最终目录
    (6) UI 可查询：待上传数量 + 最近一次上传信息
    """

    def __init__(self):
        self.offline_mode = False
        self.solver = None
        self.mesh_root: Optional[Path] = None
        self.result_root: Optional[Path] = None
        self.node_name: str = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "Node"

        self.current_msh_path: Optional[Path] = None

        # 上传队列：(case_key, files, local_case_dir, rel_dir_under_result_root)
        self._upload_queue: List[Tuple[str, List[Path], Path, Path]] = []
        self._queued_case_keys = set()  # (1) 去重

        self._q_lock = threading.Lock()
        self._q_cv = threading.Condition(self._q_lock)

        self._last_upload_case = ""
        self._last_upload_msg = ""
        self._last_upload_ts = 0

        self._log_callback = None

        self._upload_thread = threading.Thread(target=self._upload_worker_loop, daemon=True)
        self._upload_thread.start()

        self._pending_deletes = set()
        self._del_lock = threading.Lock()
        self._delete_thread = threading.Thread(target=self._delete_worker_loop, daemon=True)
        self._delete_thread.start()

        self._recovery_status = ""  # "", "running", "done"
        self._recovery_count = 0

    # ---------------- UI status (6) ----------------
    def set_offline_mode(self, flag: bool):
        self.offline_mode = bool(flag)

    def get_upload_status(self) -> Dict[str, Any]:
        with self._q_lock:
            qlen = len(self._upload_queue)
            pending = len(self._pending_deletes)
        return {
            "queue_len": qlen,
            "last_case": self._last_upload_case,
            "last_msg": self._last_upload_msg,
            "last_ts": self._last_upload_ts,
            "pending_deletes": pending,
            "recovery_status": self._recovery_status,
            "recovery_count": self._recovery_count,
        }
    
    def set_log_callback(self, callback):
        """设置日志回调，UI 用来接收上传进度"""
        self._log_callback = callback

    def _upload_log(self, msg: str):
        """内部日志方法：调用回调"""
        if self._log_callback:
            self._log_callback(msg)

    # ---------------- Basic setup ----------------
    def update_paths(self, mesh_root: str, result_root: str, node_name: Optional[str] = None):
        self.mesh_root = Path(mesh_root)
        self.result_root = Path(result_root)
        if node_name:
            self.node_name = node_name
        self.start_recovery_thread()

    def launch_fluent(self):
        if self.solver is None:
            print("Launching Fluent...")
            procs = FLUENT_PROCESSORS
            if not procs or procs <= 0:
                try:
                    cores = min(8, psutil.cpu_count(logical=False) or psutil.cpu_count())
                except Exception:
                    cores = os.cpu_count()
                procs = cores or 1

            self.solver = pyfluent.launch_fluent(
                dimension=FLUENT_DIMENSION,
                precision="double",
                processor_count=int(procs),
                mode="solver",
                ui_mode="gui" if GUI_FLAG else "hidden_gui"
            )

    # ---------------- Upload helpers ----------------
    def _nas_available(self) -> bool:
        """检查SFTP连接是否可用"""
        if self.offline_mode:
            return False

        try:
            sftp = _connect()
            sftp.stat('.')  # 简单测试
            return True
        except Exception:
            return False

    def _sftp_upload_with_retry(self, local_path: Path, remote_path: str) -> None:
        """SFTP上传，带重试"""
        last_err = None
        for attempt in range(1, NAS_UPLOAD_RETRIES + 1):
            try:
                sftp_upload_file(str(local_path), remote_path)
                return
            except Exception as e:
                last_err = e
                backoff = NAS_UPLOAD_BASE_BACKOFF_SEC * (2 ** (attempt - 1))
                time.sleep(backoff)
        raise last_err

    def _filter_files(self, files: List[Path]) -> List[Path]:
        files = [p for p in files if p.exists()]
        if not NAS_UPLOAD_EXT_WHITELIST:
            return files

        wl = [e.lower() for e in NAS_UPLOAD_EXT_WHITELIST]
        keep: List[Path] = []
        for p in files:
            name = p.name.lower()
            ext_all = "".join(Path(name).suffixes)  # 支持 .cas.h5 这种
            if ext_all in wl or p.suffix.lower() in wl:
                keep.append(p)
        return keep

    def _safe_key(self, case_key: str) -> str:
        return case_key.replace("/", "__").replace("\\", "__").replace(":", "_").replace(" ", "_")

    def _report_nas(self, case_key: str, **kw):
        if self.offline_mode:
            return

        if not NAS_ENABLE:
            return
        try:
            payload = {"action": "REPORT_NAS", "node_name": self.node_name, "case_key": case_key}
            payload.update(kw)
            request(SERVER_HOST, SERVER_PORT, payload)
        except Exception:
            print(f"_report_nas failed for case_key={case_key} and info={kw}")

    def _enqueue_upload(self, case_key: str, files: List[Path], local_case_dir: Path, rel_dir: Path):
        if self.offline_mode:
            return

        if not NAS_ENABLE:
            return

        files = self._filter_files(files)
        if not files:
            return

        # (1) 去重：同 case_key 只入队一次
        with self._q_cv:
            if case_key in self._queued_case_keys:
                return
            self._queued_case_keys.add(case_key)
            self._upload_queue.append((case_key, files, local_case_dir, rel_dir))
            self._q_cv.notify()

        # (3) 入队即标记 uploading=1
        self._report_nas(case_key, uploading=1, uploaded=0, last_error="")

    def _cleanup_local_case(self, files: List[Path], local_case_dir: Path):
        if not NAS_DELETE_LOCAL_AFTER_UPLOAD:
            return

        for f in files:
            self._unlink_with_retry_or_defer(f)

        # 删除空目录（不删除 result_root 根）
        if not self.result_root:
            return
        cur = Path(local_case_dir)
        while cur != self.result_root and cur.exists():
            try:
                cur.rmdir()
            except OSError:
                break
            cur = cur.parent

    def _unlink_with_retry_or_defer(self, f: Path, retries: int = 4, base_sleep: float = 0.2):
        """
        先小幅重试删除（应对短暂占用），仍失败则加入延迟删除集合，
        由后台 _delete_worker_loop 周期性再删。
        """
        if not f:
            return
        if not f.exists():
            return

        last_err = None
        for i in range(retries):
            try:
                if f.exists():
                    f.unlink()
                return
            except Exception as e:
                last_err = e
                time.sleep(base_sleep * (2 ** i))

        # 仍失败：加入延迟删除队列（常见就是 WinError 32 占用）
        with self._del_lock:
            self._pending_deletes.add(f)
        self._last_upload_msg = f"cleanup deferred: {f.name} ({type(last_err).__name__})"

    def _delete_worker_loop(self):
        """
        后台循环：每隔几秒尝试删除 pending 集合里的文件。
        """
        while True:
            time.sleep(5.0)

            try:
                with self._del_lock:
                    pending = list(self._pending_deletes)
                if not pending:
                    continue

                still = set()
                for f in pending:
                    try:
                        if f.exists():
                            f.unlink()
                    except Exception:
                        still.add(f)

                with self._del_lock:
                    self._pending_deletes = still
            except Exception:
                continue

    def _upload_one_case(self, case_key: str, files: List[Path], local_case_dir: Path, rel_dir: Path):
        """通过SFTP上传单个case的结果文件"""
        
        # 1. 计算 NAS 上的远程路径
        # NAS_RESULTS_PATH 例如 "/vol1/1007/fluent_cases/c2_FluentResults"
        remote_dir = f"{NAS_RESULTS_PATH}/{self.node_name}/{rel_dir}".replace("\\", "/")
        # 清理多余斜杠
        while "//" in remote_dir:
            remote_dir = remote_dir.replace("//", "/")
        
        existing_files = [f for f in files if f.exists()]
        total_files = len(existing_files)
        
        if total_files == 0:
            return

        with self._q_lock:
            remaining = len(self._upload_queue)
        
        self._upload_log(f"[Upload] Start: {case_key} -> {remote_dir}")

        try:
            # 确保远程目录存在
            sftp = _connect()
            _sftp_makedirs(sftp, remote_dir)
            
            # 上传每个文件（先传到 .tmp，再 rename）
            for i, f in enumerate(existing_files, 1):
                remote_file = f"{remote_dir}/{f.name}"
                remote_tmp = f"{remote_file}.tmp"
                
                # 上传到临时文件
                self._sftp_upload_with_retry(f, remote_tmp)
                
                # 原子提交：rename
                try:
                    sftp_remove_file(remote_file)  # 删旧的（如果有）
                except:
                    pass
                sftp_rename(remote_tmp, remote_file)
                
                if total_files > 3:
                    self._upload_log(f"[Upload] {case_key}: {i}/{total_files} files uploaded")

            # 2. 上报成功
            now = int(time.time())
            self._report_nas(
                case_key, 
                uploaded=1, 
                uploading=0, 
                uploaded_at=now, 
                last_error="", 
                nas_path=remote_dir
            )

            self._cleanup_local_case(existing_files, local_case_dir)

            self._last_upload_case = case_key
            self._last_upload_msg = "uploaded ok"
            self._last_upload_ts = now

            with self._q_lock:
                remaining = len(self._upload_queue)
            
            self._upload_log(f"[Upload] Done: {case_key}. Remaining: {remaining}")
            
        except Exception as e:
            raise e  # 让外层处理重试

    def _upload_worker_loop(self):
        while True:
            # (2) Z盘不可用：不动队列，直接睡
            if not self._nas_available():
                time.sleep(NAS_UPLOAD_IDLE_SLEEP_SEC)
                continue

            with self._q_cv:
                if not self._upload_queue:
                    self._q_cv.wait(timeout=NAS_UPLOAD_IDLE_SLEEP_SEC)
                    continue
                job = self._upload_queue.pop(0)

            case_key, files, local_case_dir, rel_dir = job

            existing = [p for p in files if isinstance(p, Path) and p.exists()]
            missing_cnt = len(files) - len(existing)

            if not existing:
                # 没有任何可上传文件：不要无限重试
                self._report_nas(case_key, uploading=0, uploaded=0,
                                last_error="skip upload: no local files exist")
                with self._q_lock:
                    self._queued_case_keys.discard(case_key)
                continue

            # 可选：记录一下缺失信息（不阻断上传）
            if missing_cnt > 0:
                self._last_upload_msg = f"uploading with missing files: {missing_cnt}"

            # 用 existing 去上传（不要用原来的 files）
            self._upload_one_case(case_key, existing, local_case_dir, rel_dir)

            try:
                with self._q_cv:
                    self._queued_case_keys.discard(case_key)
            except Exception as e:
                self._last_upload_case = case_key
                self._last_upload_msg = f"failed: {e}"
                self._last_upload_ts = int(time.time())

                # ✅ 添加错误日志
                self._upload_log(f"[Upload] Failed: {case_key} - {e}")

                self._report_nas(case_key, uploading=1, uploaded=0, last_error=str(e)[:500])

                with self._q_cv:
                    self._upload_queue.append(job)

                time.sleep(NAS_UPLOAD_IDLE_SLEEP_SEC)

    def start_recovery_thread(self):
        """
        异步恢复：从 DB 找到“本机已完成但未上传”的 case，重新入队上传。
        放线程里跑，避免卡 UI / 主流程。
        """
        if self.offline_mode:
            return

        if not NAS_ENABLE:
            return
        if getattr(self, "_recovery_started", False):
            return
        self._recovery_started = True

        t = threading.Thread(target=self.recover_pending_uploads, daemon=True)
        t.start()

    def recover_pending_uploads(self, limit: int = 5000):
        """
        恢复上传队列：
        1. 扫描本地 processed 目录 -> 得到已完成的 case_keys
        2. 查云端已上传的 case_keys
        3. 差集 = 需要上传的
        4. 检查本地结果文件存在 -> 入队
        """
        self._recovery_status = "running"
        self._recovery_count = 0

        try:
            node = getattr(self, "node_name", "") or ""
            mesh_root = Path(getattr(self, "mesh_root", "") or "")
            result_root = Path(getattr(self, "result_root", "") or "")
            if not node or not mesh_root.exists() or not result_root.exists():
                self._recovery_status = "done"
                return

            # ========== 第一步：扫描本地 processed 目录 ==========
            local_done_keys = set()
            try:
                for processed_dir in mesh_root.rglob("processed"):
                    if not processed_dir.is_dir():
                        continue
                    for msh_file in processed_dir.glob("*.msh"):
                        # case_key = 相对 mesh_root，去掉 processed
                        # mesh_root/a1/processed/xxx.msh -> a1/xxx.msh
                        parent = processed_dir.parent
                        try:
                            rel_parent = parent.relative_to(mesh_root)
                        except ValueError:
                            rel_parent = Path(".")
                        case_key = str(rel_parent / msh_file.name).replace("\\", "/")
                        local_done_keys.add(case_key)
            except Exception as e:
                print(f"[recover] scan processed dirs failed: {e}")

            print(f"[recover] found {len(local_done_keys)} cases in processed dirs")

            if not local_done_keys:
                self._recovery_status = "done"
                return

            # ========== 第二步：查云端已上传的 ==========
            uploaded_keys = set()
            try:
                resp = request(SERVER_HOST, SERVER_PORT, {
                    "action": "LIST_JOBS",
                    "node_name": node,
                    "limit": int(limit),
                    "offset": 0,
                    "status": "COMPLETED",
                    "nas": "done",
                    "q": "",
                    "order": "updated",
                })
                if resp.get("ok"):
                    for j in resp.get("jobs", []):
                        k = j.get("case_key", "")
                        if k:
                            uploaded_keys.add(k)
            except Exception as e:
                print(f"[recover] query uploaded keys failed: {e}")

            # ========== 第三步：差集 = 需要上传的 ==========
            need_upload = local_done_keys - uploaded_keys
            print(f"[recover] need upload: {len(need_upload)} cases")

            requeued = 0
            for case_key in need_upload:
                try:
                    rel_mesh = Path(case_key)
                    stem = rel_mesh.stem

                    out_dir = result_root / rel_mesh.parent
                    if out_dir == result_root:
                        rel_dir = Path(".")
                    else:
                        try:
                            rel_dir = out_dir.relative_to(result_root)
                        except ValueError:
                            rel_dir = rel_mesh.parent

                    local_files = build_fluent_result_files(out_dir, stem)
                    existing = [f for f in local_files if f.exists()]
                    if existing:
                        self._enqueue_upload(case_key, local_files, out_dir, rel_dir)
                        requeued += 1
                except Exception:
                    continue

            self._recovery_count = requeued
            self._recovery_status = "done"
            print(f"[recover] requeued {requeued} cases for upload")

        except Exception as e:
            print(f"[recover] failed: {e}")
            self._recovery_count = requeued
            self._recovery_status = "done"

            if requeued > 0:
                self._upload_log(f"[Upload] Recovery done: {requeued} cases re-queued for upload")

            print(f"[recover] requeued {requeued} cases for upload")

    # ---------------- Main: process one mesh ----------------
    def process_case(self, msh_path: str):
        if not self.mesh_root or not self.result_root:
            raise RuntimeError("Call update_paths(mesh_root, result_root) before process_case().")

        self.current_msh_path = Path(msh_path)

        # case_key = 相对 mesh_root 的路径（与 client_core.make_case_key 一致）
        try:
            rel_mesh = self.current_msh_path.relative_to(self.mesh_root)
            case_key = str(rel_mesh).replace("\\", "/")
        except Exception:
            rel_mesh = Path(self.current_msh_path.name)
            case_key = self.current_msh_path.name

        out_dir = self.result_root / rel_mesh.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = rel_mesh.stem
        cas_path = out_dir / f"{stem}.cas"
        plt_path = out_dir / f"{stem}.plt"
        yplus_path = out_dir / f"{stem}.yplus"
        ascii_path = out_dir / f"{stem}.ascii"
        cd_base = out_dir / f"{stem}_cd"
        cl_base = out_dir / f"{stem}_cl"

        self.launch_fluent()
        s = self.solver

        try:
            s.file.read(file_type="mesh", file_name=str(self.current_msh_path))
            s.settings.mesh.check()
            if GUI_FLAG:
                s.tui.display.mesh_outline()

            s.settings.setup.general.solver.time = "unsteady-1st-order"
            s.settings.setup.boundary_conditions.velocity_inlet["inlet"] = {"momentum": {"velocity": {"value": 8}}}
            s.tui.report.reference_values.compute.velocity_inlet("inlet")
            s.settings.solution.initialization.hybrid_initialize()

            all_zones = s.settings.setup.boundary_conditions.wall.get_object_names()
            monitor_zones = [z for z in all_zones if ("building" in z or "wall" in z)]
            try:
                monitor_building = max((z for z in all_zones if z.startswith("building")), key=lambda x: int(x[8:]))
            except ValueError:
                monitor_building = ["wall_____"]

            s.settings.solution.report_definitions.drag["cd-wall"] = {"zones": monitor_building, "force_vector": [1, 0]}
            s.settings.solution.report_definitions.lift["cl-wall"] = {"zones": monitor_building, "force_vector": [0, 1]}
            s.settings.solution.monitor.report_files[str(cd_base)] = {"report_defs": ["cd-wall"]}
            s.settings.solution.monitor.report_files[str(cl_base)] = {"report_defs": ["cl-wall"]}
            if GUI_FLAG:
                s.settings.solution.monitor.report_plots["cd-wall"]={"report_defs":["cd-wall"]}
                s.settings.solution.monitor.report_plots["cl-wall"]={"report_defs":["cl-wall"]}

            # 阶段1：预计算
            s.settings.solution.run_calculation.data_sampling.enabled = False
            s.settings.solution.run_calculation.transient_controls.time_step_size = TIME_STEP_SIZE
            s.settings.solution.run_calculation.transient_controls.time_step_count = WARM_STEPS
            s.settings.solution.run_calculation.reporting_interval = WARM_STEPS
            s.settings.solution.run_calculation.calculate()

            # 阶段2：采样计算
            s.settings.solution.run_calculation.data_sampling.enabled = True
            s.settings.solution.run_calculation.transient_controls.time_step_count = SAMPLING_STEPS_INIT
            s.settings.solution.run_calculation.calculate()

            # 阶段3：收敛检查循环
            max_retries = 15
            for _i in range(max_retries):
                if result_is_convergence(str(cd_base) + ".out", str(cl_base) + ".out"):
                    break
                s.settings.solution.run_calculation.transient_controls.time_step_count = SAMPLING_STEPS_INTERVAL
                s.settings.solution.run_calculation.calculate()

            # 确保目录存在
            out_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存结果（本地）
            s.settings.file.write(file_type="case-data", file_name=str(cas_path))
            s.settings.file.export.tecplot(
                file_name = plt_path, surfaces = [], 
                cell_func_domain_export = [
                    "rmse-velocity-magnitude", "mean-y-velocity", "mean-x-velocity", "mean-velocity-magnitude",
                    "mean-pressure-coefficient", "rmse-pressure", "mean-pressure"]
            )
            s.settings.file.export.ascii(
                file_name = yplus_path,
                surface_name_list = monitor_zones, delimiter = "comma", 
                cell_func_domain = ["y-plus"], location = "node"
            )
            s.settings.file.export.ascii(
                file_name = ascii_path, surface_name_list = [], delimiter = "comma", 
                cell_func_domain = [
                    "mean-y-velocity", "mean-x-velocity",
                    "mean-pressure"], location = "node"
            )
            s.settings.solution.run_calculation.data_sampling.enabled = False

        except Exception as e:
            self.handle_error(e)
            return False

        moved = False
        companion_info_src = None  # 与 .msh 同目录生成的同名 .dat -> .info（用于随结果上传）
        companion_dat = self.current_msh_path.with_suffix(".dat")
        if MOVE_MESH_AFTER_RUN and self.current_msh_path.exists():
            processed_dir = self.current_msh_path.parent / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            # 1) 先移动 .msh
            shutil.move(self.current_msh_path, processed_dir / self.current_msh_path.name)
            moved = True
            # 2) 如果存在与 .msh 同名的伴随 .dat（文本信息），一起移动到 processed
            if companion_dat.exists():
                shutil.move(companion_dat, processed_dir / companion_dat.name)
                companion_info_src = processed_dir / companion_dat.name
        else:
            # 不移动 mesh 的情况下：如果伴随 .dat 存在，仍然复制为 .info 上传（不改动原文件）
            if companion_dat.exists():
                companion_info_src = companion_dat

        # 将伴随 .dat 复制到本次结果目录，避免与 Fluent 输出的同名 .dat 冲突
        companion_info_dst = out_dir / f"{stem}.info"
        if companion_info_src and Path(companion_info_src).exists():
            shutil.copy2(companion_info_src, companion_info_dst)

        # 收集输出（兼容 .cas/.dat 与 .cas.h5/.dat.h5）
        local_files = build_fluent_result_files(out_dir, stem)
        rel_dir = out_dir.relative_to(self.result_root)
        self._enqueue_upload(case_key, local_files, out_dir, rel_dir)

        # (Auto) 写入“case已完成”信号，供 client_app 轮询触发下一个case
        token = f"{int(time.time())}\t{case_key}\n"
        p = Path(CASE_DONE_SIGNAL_FILE)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(token, encoding="utf-8")
        os.replace(str(tmp), str(p))  # 原子替换，避免 client 读到半截

        return {"ok": True, "moved": moved, "enqueued_upload": bool(NAS_ENABLE)}

    # ---------------- Error Handling ----------------
    def handle_error(self, e):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        msg = f"[{ts}] ERROR: {e}"
        print(msg)
        with open("failed_cases.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")

        if self.current_msh_path and self.current_msh_path.exists():
            quarantine_dir = self.current_msh_path.parent / "error_quarantine"
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(self.current_msh_path, quarantine_dir / self.current_msh_path.name)

            if self.current_msh_path.with_suffix(".dat").exists():
                shutil.move(
                    self.current_msh_path.with_suffix(".dat"),
                    quarantine_dir / self.current_msh_path.with_suffix(".dat").name
                )

        if self.solver:
            self.solver.exit()
        self.solver = None
        time.sleep(5)