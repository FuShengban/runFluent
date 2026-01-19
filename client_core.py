# client_core.py
import os
import time
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List
from pathlib import Path

from config import (
    SERVER_HOST, SERVER_PORT, DEFAULT_NODE_NAME, 
    CASE_DONE_SIGNAL_FILE, NAS_POOL_PATH,
)
from sftp_utils import (
    sftp_upload_file, sftp_download_file,
    sftp_exists, sftp_remove_file, _connect
)
from protocol import request
from db_manager import JobDB


def default_node_name() -> str:
    if DEFAULT_NODE_NAME:
        return DEFAULT_NODE_NAME
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "Node"

def list_msh(mesh_root: str, recursive: bool = True) -> List[str]:
    msh_files = []
    if recursive:
        for root, _, files in os.walk(mesh_root):
            # 跳过 processed 和 error_quarantine 文件夹中的内容
            if any(name.lower() == 'processed' or name.lower() == 'error_quarantine' 
                   for name in root.replace("\\", "/").split("/")):
                continue
            for f in files:
                if f.lower().endswith(".msh"):
                    msh_files.append(os.path.join(root, f))
    else:
        for f in os.listdir(mesh_root):
            if f.lower().endswith(".msh"):
                msh_files.append(os.path.join(mesh_root, f))
    return msh_files

def make_case_key(mesh_root: str, msh_path: str) -> str:
    rel = os.path.relpath(msh_path, mesh_root)
    rel = rel.replace("\\", "/")
    return rel

@dataclass
class ClientState:
    node_name: str
    mesh_root: str = ""
    result_root: str = ""
    offline_mode: bool = False

class ClientCore:
    def __init__(self, state: ClientState):
        self.state = state
        self._uploading_to_pool_locks = set()
        self._current_computing_key = None
        self._is_auto_assigning = False
        self._is_auto_replenishing = False
        self.offline_mode = bool(getattr(state, "offline_mode", False))
        self.local_db: JobDB | None = None

    def set_offline_mode(self, flag: bool, db_path: str = ""):
        self.offline_mode = bool(flag)
        if hasattr(self.state, "offline_mode"):
            self.state.offline_mode = self.offline_mode

        # 离线DB放到 result_root 下面：方便你最后“拷结果目录”时把DB一起带走
        if self.offline_mode:
            root = self.state.result_root or ""
            if not root:
                # 兜底：没选 result_root 时就放当前目录
                root = "."
            os.makedirs(root, exist_ok=True)
            final_db = db_path or os.path.join(root, "offline_project.db")
            if self.local_db is None or getattr(self.local_db, "db_path", "") != final_db:
                self.local_db = JobDB(final_db)

    def _ensure_local_job(self, case_key: str, origin_path: str = ""):
        if not self.local_db:
            return
        # 用 register_cases 的 INSERT OR IGNORE 达到“存在则不动，不存在则插入”
        self.local_db.register_cases(
            node=self.state.node_name,
            mesh_root=self.state.mesh_root,
            cases=[{
                "case_key": case_key,
                "case_name": os.path.basename(case_key),
                "origin_path": origin_path or ""
            }]
        )

    def robust_copy(self, src: Path, dst: Path):
        """
        使用 Windows Robocopy 替代 shutil，解决学校机房 SMB 握手慢/断连问题。
        支持 /Z 断点续传。
        """
        src = Path(src)
        dst = Path(dst)
        
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")

        dst_parent = dst.parent
        dst_parent.mkdir(parents=True, exist_ok=True)
        
        # Robocopy 只能按原名复制。如果 dst 文件名和 src 不同（如 xxx.tmp），
        # 我们需要先复制到一个隐蔽的临时文件夹，再 rename 出来。
        # 这样防止在本地目录直接生成 "case.msh" 导致 Auto Mode 误判。
        needs_rename = (src.name != dst.name)
        
        if needs_rename:
            staging_dir = dst_parent / ".robo_staging"
            staging_dir.mkdir(exist_ok=True)
            target_dir = str(staging_dir)
            src_in_staging = staging_dir / src.name
        else:
            staging_dir = None
            target_dir = str(dst_parent)
            src_in_staging = None

        # 构造 Robocopy 命令
        # /Z: 断点续传 (关键！)
        # /J: 使用未缓冲I/O (大文件加速)
        # /R:3 /W:5: 失败重试3次，每次间隔5秒
        # /NJH...: 静默模式，不输出废话
        cmd = [
            "robocopy",
            str(src.parent),
            target_dir,
            src.name,
            "/Z", "/J", "/R:3", "/W:5",
            "/NJH", "/NJS", "/NDL", "/NC", "/NS"
        ]
        
        try:
            # 隐藏 CMD 黑框
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Robocopy 返回值 0-7 都是成功，>=8 才是失败
            proc = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
            if proc.returncode >= 8:
                # 失败则抛错，触发下面 except 里的 shutil 降级
                raise RuntimeError(f"Robocopy failed code={proc.returncode}")

            # 如果用了中转目录，现在把文件移出来并改名
            if needs_rename:
                if src_in_staging.exists():
                    if dst.exists():
                        os.remove(dst)
                    os.replace(src_in_staging, dst)
                else:
                    raise FileNotFoundError("Robocopy ok but file missing")

        except Exception as e:
            print(f"[Warn] Robocopy failed ({e}), fallback to shutil...")
            shutil.copy2(src, dst)
        finally:
            # 清理中转目录
            if staging_dir and staging_dir.exists():
                staging_dir.rmdir() # 只有空了才能删，安全

    # ---- 服务端通信 ----
    def ping(self) -> Dict:
        if self.offline_mode:
            return {"ok": True, "pong": True, "node": self.state.node_name, "offline": True}
        return request(SERVER_HOST, SERVER_PORT, {"action": "PING", "node_name": self.state.node_name})
    
    def _log_proxy(self, msg: str, callback=None):
        if callback:
            callback(msg)
        else:
            print(msg)

    def register_mesh_root(self, mesh_root: str, result_root: str = "") -> None:
        self.state.mesh_root = mesh_root
        self.state.result_root = result_root or ""

    def scan_and_register(self, recursive: bool = True) -> Dict:
        if not self.state.mesh_root:
            raise ValueError("mesh_root not set")
        paths = list_msh(self.state.mesh_root, recursive=recursive)
        cases = []
        for p in paths:
            cases.append({
                "case_key": make_case_key(self.state.mesh_root, p),
                "case_name": os.path.basename(p),
                "origin_path": p
            })
        payload = {
            "action": "REGISTER_CASES",
            "node_name": self.state.node_name,
            "mesh_root": self.state.mesh_root,
            "cases": cases
        }
        if self.offline_mode:
            self.set_offline_mode(True)  # 确保 local_db 已初始化
            n = self.local_db.register_cases(
                node=self.state.node_name,
                mesh_root=self.state.mesh_root,
                cases=cases
            )
            return {"ok": True, "new_count": n, "offline": True}

        return request(SERVER_HOST, SERVER_PORT, payload)

    def get_pool_status(self) -> Dict:
        if self.offline_mode:
            raise RuntimeError("Offline mode: pool/assign/delete requires server+NAS, disabled.")

        return request(SERVER_HOST, SERVER_PORT, {"action": "GET_POOL_STATUS", "node_name": self.state.node_name})

    def put_selected_in_pool(self, case_keys: List[str], log_callback=None) -> Dict:
        if self.offline_mode:
            raise RuntimeError("Offline mode: pool/assign/delete requires server+NAS, disabled.")

        if not self.state.mesh_root:
            raise ValueError("mesh_root not set")
        
        # 1. 过滤正在计算的任务
        valid_keys = []
        for k in case_keys:
            if k == self._current_computing_key:
                self._log_proxy(f"[Pool Skip] 任务正在计算中，跳过补货: {k}", log_callback)
                continue
            valid_keys.append(k)
            
        if not valid_keys:
            return {"ok": False, "error": "No valid keys"}

        local_root = Path(self.state.mesh_root)
        success_keys = []
        
        for k in valid_keys:
            self._uploading_to_pool_locks.add(k)

        try:
            total = len(valid_keys)
            for i, key in enumerate(valid_keys, 1):
                try:
                    local_msh = local_root / key
                    local_dat = local_msh.with_suffix(".dat")
                    
                    # NAS 远程路径
                    remote_msh = f"{NAS_POOL_PATH}/{key}"
                    remote_dat = remote_msh.rsplit('.', 1)[0] + ".dat"
                    
                    # 检查 NAS 上是否已存在
                    if sftp_exists(remote_msh) and sftp_exists(remote_dat):
                        self._log_proxy(f"[Pool] ({i}/{total}) NAS已存在，跳过上传: {key}", log_callback)
                        if local_msh.exists(): os.remove(local_msh)
                        if local_dat.exists(): os.remove(local_dat)
                        success_keys.append(key)
                        continue

                    # SFTP 上传
                    self._log_proxy(f"[Pool] ({i}/{total}) 正在上传(SFTP): {key} ...", log_callback)
                    
                    # 先传到 .tmp，再改名（原子提交）
                    remote_msh_tmp = remote_msh + ".tmp"
                    remote_dat_tmp = remote_dat + ".tmp"
                    
                    if local_msh.exists():
                        sftp_upload_file(str(local_msh), remote_msh_tmp)
                    if local_dat.exists():
                        sftp_upload_file(str(local_dat), remote_dat_tmp)
                    
                    # 原子提交：rename
                    sftp = _connect()
                    if sftp_exists(remote_msh_tmp):
                        try:
                            sftp.remove(remote_msh)  # 删旧的（如果有）
                        except:
                            pass
                        sftp.rename(remote_msh_tmp, remote_msh)
                    if sftp_exists(remote_dat_tmp):
                        try:
                            sftp.remove(remote_dat)
                        except:
                            pass
                        sftp.rename(remote_dat_tmp, remote_dat)
                    
                    # 校验并删本地
                    if sftp_exists(remote_msh):
                        if local_msh.exists(): os.remove(local_msh)
                        if local_dat.exists(): os.remove(local_dat)
                        self._log_proxy(f"[Pool] ({i}/{total}) 上传成功: {key}", log_callback)
                        success_keys.append(key)
                    else:
                        self._log_proxy(f"[Pool Error] NAS校验失败: {key}", log_callback)

                except Exception as e:
                    self._log_proxy(f"[Pool Error] 处理失败 {key}: {e}", log_callback)
        finally:
            for k in valid_keys:
                self._uploading_to_pool_locks.discard(k)

        if not success_keys:
            return {"ok": False, "error": "所有文件处理失败"}

        # 向服务器注册
        self._log_proxy(f"[Pool] 正在向服务器注册 {len(success_keys)} 个任务...", log_callback)
        
        payload = {
            "action": "PUT_IN_POOL",
            "node_name": self.state.node_name,
            "case_keys": success_keys
        }
        resp = request(SERVER_HOST, SERVER_PORT, payload)
        self._log_proxy(f"[Pool] 注册完成: {resp}", log_callback)
        return resp
    
    def assign_from_pool(self, n: int, log_callback=None) -> List[str]:
        if self.offline_mode:
            raise RuntimeError("Offline mode: pool/assign/delete requires server+NAS, disabled.")

        payload = {"action": "ASSIGN_FROM_POOL", "node_name": self.state.node_name, "n": int(n)}
        resp = request(SERVER_HOST, SERVER_PORT, payload)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "assign failed"))
        
        assigned_jobs = resp.get("jobs", [])
        if not assigned_jobs:
            self._log_proxy("[Pool] 服务器暂时没有可领取的任务。", log_callback)
            return []

        if not self.state.mesh_root:
            raise ValueError("mesh_root not set")

        local_root = Path(self.state.mesh_root)
        downloaded_jobs = []
        
        self._log_proxy(f"[Pool] 已锁定 {len(assigned_jobs)} 个任务，开始下载 (SFTP)...", log_callback)
        
        total = len(assigned_jobs)
        for i, key in enumerate(assigned_jobs, 1):
            local_msh_tmp = None
            local_dat_tmp = None
            try:
                self._log_proxy(f"[Pool] ({i}/{total}) 正在下载: {key} ...", log_callback)

                # NAS 远程路径
                remote_msh = f"{NAS_POOL_PATH}/{key}"
                remote_dat = remote_msh.rsplit('.', 1)[0] + ".dat"
                
                # 本地路径
                local_msh = local_root / key
                local_dat = local_msh.with_suffix(".dat")
                local_msh_tmp = local_msh.parent / (local_msh.name + ".tmp")
                local_dat_tmp = local_dat.parent / (local_dat.name + ".tmp")
                
                local_msh.parent.mkdir(parents=True, exist_ok=True)
                
                # 1. 下载到临时文件
                if not sftp_exists(remote_msh):
                    self._log_proxy(f"[Pool Warn] NAS源缺失: {remote_msh}", log_callback)
                    continue
                
                sftp_download_file(remote_msh, str(local_msh_tmp))
                
                if sftp_exists(remote_dat):
                    sftp_download_file(remote_dat, str(local_dat_tmp))
                
                # 2. 原子提交
                if local_dat_tmp.exists():
                    os.replace(local_dat_tmp, local_dat)
                if local_msh_tmp.exists():
                    os.replace(local_msh_tmp, local_msh)
                
                downloaded_jobs.append(key)
                
                # 3. 清理 NAS 源文件
                try:
                    sftp_remove_file(remote_msh)
                    sftp_remove_file(remote_dat)
                except Exception as e:
                    self._log_proxy(f"[Pool Warn] 清理NAS源失败: {e}", log_callback)
                
                self._log_proxy(f"[Pool] ({i}/{total}) 下载成功: {key}", log_callback)
                
            except Exception as e:
                self._log_proxy(f"[Pool Error] 下载失败 {key}: {e}", log_callback)
                if local_msh_tmp and local_msh_tmp.exists(): 
                    os.remove(local_msh_tmp)
                if local_dat_tmp and local_dat_tmp.exists(): 
                    os.remove(local_dat_tmp)
        
        self._log_proxy(f"[Pool] 全部处理完毕。本地准备好 {len(downloaded_jobs)} 个新任务。", log_callback)
        return downloaded_jobs
                
    def report_started(self, case_key: str, compute_path: str, result_path: str) -> None:
        if self.offline_mode:
            self.set_offline_mode(True)
            self._ensure_local_job(case_key, origin_path=compute_path)
            self.local_db.report_started(self.state.node_name, case_key, compute_path=compute_path, result_path=result_path)
            return
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_STARTED",
            "node_name": self.state.node_name,
            "case_key": case_key,
            "compute_path": compute_path,
            "result_path": result_path
        })

    def report_done(self, case_key: str, duration_sec: float) -> None:
        if self.offline_mode:
            self.set_offline_mode(True)
            self._ensure_local_job(case_key)
            self.local_db.report_done(self.state.node_name, case_key, float(duration_sec))
            return
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_DONE",
            "node_name": self.state.node_name,
            "case_key": case_key,
            "duration_sec": duration_sec
        })


    def report_failed(self, case_key: str) -> None:
        if self.offline_mode:
            self.set_offline_mode(True)
            self._ensure_local_job(case_key)
            self.local_db.report_failed(self.state.node_name, case_key)
            return
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_FAILED",
            "node_name": self.state.node_name,
            "case_key": case_key
        })

    def report_nas(self, case_key: str, uploaded: int = 1) -> None:
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_NAS",
            "node_name": self.state.node_name,
            "case_key": case_key,
            "uploaded": int(uploaded)
        })

    def get_stats(self) -> Dict:
        if self.offline_mode:
            self.set_offline_mode(True)
            return self.local_db.stats() if self.local_db else {}
        resp = request(SERVER_HOST, SERVER_PORT, {"action": "GET_STATS", "node_name": self.state.node_name})
        return resp.get("stats", {}) if resp.get("ok") else {}

    def scan_and_recover_nas_pool(self) -> Dict:
        """
        让服务器通过 SSH 扫描 NAS_POOL_PATH 下的 .msh，并把DB里缺失的case补入库
        返回: {"ok": True, "found": N, "recovered": M, ...}
        """
        if self.offline_mode:
            return {"ok": True, "offline": True, "msg": "offline mode skip"}
        return request(SERVER_HOST, SERVER_PORT, {
            "action": "SCAN_AND_RECOVER",
            "node_name": self.state.node_name
        })

    # ---- 计算动作 ----
    def compute_one_local(self, msh_path: str, fluent_worker=None) -> Dict:
        """
        fluent_worker 需要提供：process_case(msh_path) -> bool 或返回包含详细信息的 dict
        """
        if not self.state.mesh_root:
            raise ValueError("mesh_root not set")

        case_key = make_case_key(self.state.mesh_root, msh_path)
        compute_path = msh_path
        result_path = self.state.result_root or ""
        
        # --- 锁检查 ---
        if case_key in self._uploading_to_pool_locks:
            print(f"[SKIP] 该任务正在上传到服务器池，跳过本地计算: {case_key}")
            return {
                "ok": True,
                "case_key": case_key, 
                "skipped": True, 
                "reason": "uploading_to_pool"
            }
        
        # 使用 try...finally 确保计算标记一定会被清除
        self._current_computing_key = case_key
        try:
            if not self.offline_mode:
                # ===== 跑前查云端是否已经完成 =====
                jobs = self.get_jobs(limit=1, status="COMPLETED", q=case_key)
                if jobs:
                    print(f"[SKIP] case already COMPLETED on server: {case_key}")
                    # ... (移动文件到 processed 的逻辑) ...
                    companion_dat = msh_path.with_suffix(".dat")
                    try:
                        processed_dir = msh_path.parent / "processed"
                        processed_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(msh_path, processed_dir / msh_path.name)
                        if companion_dat.exists():
                            shutil.move(companion_dat, processed_dir / companion_dat.name)
                    except Exception as e:
                        print(f"[WARN] move to processed failed: {e}")

                    try:
                        token = f"{int(time.time())}\t{case_key}\n"
                        p = Path(CASE_DONE_SIGNAL_FILE)
                        tmp = p.with_suffix(p.suffix + ".tmp")
                        tmp.write_text(token, encoding="utf-8")
                        os.replace(str(tmp), str(p))
                    except Exception as e:
                        print(f"[WARN] write done signal failed: {e}")

                    return {
                        "ok": True,
                        "case_key": case_key,
                        "skipped": True,
                        "reason": "already_completed_on_server"
                    }

            # ===== 正常计算流程 =====
            self.report_started(case_key, compute_path=compute_path, result_path=result_path)

            t0 = time.time()
            result_details: Dict = {}
            ok = False
            try:
                if fluent_worker is None:
                    time.sleep(0.2)
                    ok = True
                else:
                    outcome = fluent_worker.process_case(msh_path)
                    if outcome is True or outcome is None or isinstance(outcome, bool):
                        ok = bool(outcome)
                        result_details = {}
                    elif isinstance(outcome, dict):
                        ok = bool(outcome.get("ok", True))
                        result_details = outcome
                    else:
                        ok = bool(outcome)
                        result_details = {}
            except Exception:
                ok = False
                result_details = {}

            dt = time.time() - t0
            if ok:
                self.report_done(case_key, dt)
                resp = {"ok": True, "case_key": case_key, "duration_sec": dt}
                for k, v in result_details.items():
                    if k not in ["ok", "case_key", "duration_sec"]:
                        resp[k] = v
                return resp
            else:
                self.report_failed(case_key)
                return {"ok": False, "case_key": case_key, "duration_sec": dt}
                
        finally:
            self._current_computing_key = None
        
    def get_jobs(self, limit: int = 200, offset: int = 0, status: str = "", nas: str = "", q: str = "", order: str = "updated") -> list:
        if self.offline_mode:
            self.set_offline_mode(True)
            return self.local_db.list_jobs(limit=limit, offset=offset, status=status, nas=nas, q=q, order=order) if self.local_db else []
        resp = request(SERVER_HOST, SERVER_PORT, {
            "action": "LIST_JOBS",
            "node_name": self.state.node_name,
            "limit": limit,
            "offset": offset,
            "status": status,
            "nas": nas,
            "q": q,
            "order": order
        })
        return resp.get("jobs", []) if resp.get("ok") else []

    def delete_jobs(self, case_keys: List[str], password: str) -> Dict:
        """
        发送删除任务请求，要求服务器删除数据库记录及对应文件
        """
        if self.offline_mode:
            raise RuntimeError("Offline mode: pool/assign/delete requires server+NAS, disabled.")

        payload = {
            "action": "DELETE_JOBS",
            "node_name": self.state.node_name,
            "case_keys": case_keys,
            "password": password
        }
        # 发送请求并返回结果
        return request(SERVER_HOST, SERVER_PORT, payload)