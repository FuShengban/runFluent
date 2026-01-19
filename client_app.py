import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from pathlib import Path

from client_core import ClientCore, ClientState, default_node_name, list_msh, make_case_key
from config import (
    ASSIGN_BATCH_DEFAULT, UPLOAD_BATCH_DEFAULT, UI_UPLOAD_STATUS_REFRESH_MS, 
    AUTO_POLL_MS, CASE_DONE_SIGNAL_FILE,
    POOL_TARGET_SIZE, AUTO_UPLOAD_BATCH, AUTO_ASSIGN_BATCH, 
    AUTO_ASSIGN_TRIGGER_THRESHOLD, PRODUCER_MIN_LOCAL_COUNT,
    SERVER_HOST, SERVER_PORT,
)
from fluent_worker import FluentWorker


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fluent Cluster Client")
        self.geometry("1540x650")

        self.state = ClientState(node_name=default_node_name())
        self.core = ClientCore(self.state)
        self.worker = FluentWorker()

        self.worker.set_log_callback(self._ui_log)

        self.auto_running = False
        self._auto_last_sig = None
        self._auto_poll_ms = AUTO_POLL_MS

        self._computing_lock = threading.Lock()
        self._is_computing = False

        self.offline_var = tk.BooleanVar(value=False)
        self._build_ui()

        # (6) 定时刷新上传队列状态（不会卡UI）
        self.after(UI_UPLOAD_STATUS_REFRESH_MS, self._refresh_upload_status)

        self.btn_ping = getattr(self, "btn_ping", None)
        self.btn_assign = getattr(self, "btn_assign", None)
        self.btn_put = getattr(self, "btn_put", None)
        self.entry_assign_n = getattr(self, "entry_assign_n", None)
        self.entry_upload_n = getattr(self, "entry_upload_n", None)

    def _build_ui(self):
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        tk.Checkbutton(
            top,
            text="离线模式（不连云服务器/不走NAS）",
            variable=self.offline_var,
            command=self.on_toggle_offline
        ).pack(side="left", padx=10)

        tk.Label(top, text="Node Name:").pack(side="left")
        self.node_var = tk.StringVar(value=self.state.node_name)
        tk.Entry(top, textvariable=self.node_var, width=20).pack(side="left", padx=6)

        self.btn_ping = tk.Button(top, text="Ping Server", command=self.on_ping)
        self.btn_ping.pack(side="left", padx=6)

        tk.Button(top, text="选择 msh 根目录", command=self.on_choose_mesh_root).pack(side="left", padx=6)
        self.mesh_root_var = tk.StringVar(value="")
        tk.Entry(top, textvariable=self.mesh_root_var, width=60).pack(side="left", padx=6)

        # 上传队列状态栏
        self.upload_status_var = tk.StringVar(value="UploadQueue: 0 | Last: -")
        tk.Label(top, textvariable=self.upload_status_var).pack(side="right")

        mid = tk.Frame(self)
        mid.pack(fill="x", padx=10, pady=6)

        self.btn_scan = tk.Button(mid, text="刷新并注册（热更新）", command=self.on_scan_register)
        self.btn_scan.pack(side="left", padx=6)

        # ✅ 计算放后台线程：避免 GUI 卡死
        self.btn_compute = tk.Button(mid, text="算下一个", command=self.on_compute_next_async)
        self.btn_compute.pack(side="left", padx=6)

        tk.Label(mid, text="拉任务数量:").pack(side="left", padx=(20, 4))
        self.assign_n_var = tk.IntVar(value=ASSIGN_BATCH_DEFAULT)
        self.entry_assign_n = tk.Entry(mid, textvariable=self.assign_n_var, width=5)
        self.entry_assign_n.pack(side="left")
        self.btn_assign = tk.Button(mid, text="从服务器池拉任务", command=self.on_assign_from_pool)
        self.btn_assign.pack(side="left", padx=6)

        tk.Label(mid, text="补货数量:").pack(side="left", padx=(20, 4))
        self.upload_n_var = tk.IntVar(value=UPLOAD_BATCH_DEFAULT)
        self.entry_upload_n = tk.Entry(mid, textvariable=self.upload_n_var, width=5)
        self.entry_upload_n.pack(side="left")
        self.btn_put = tk.Button(mid, text="补货到服务器池（限流）", command=self.on_put_in_pool)
        self.btn_put.pack(side="left", padx=6)

        auto = tk.Frame(self)
        auto.pack(fill="x", padx=10, pady=6)

        tk.Button(auto, text="启动自动模式", command=self.on_auto_start).pack(side="left", padx=6)
        tk.Button(auto, text="停止自动模式", command=self.on_auto_stop).pack(side="left", padx=6)

        tk.Label(auto, text="轮询间隔(秒):").pack(side="left", padx=(20, 4))
        self.auto_poll_sec_var = tk.DoubleVar(value=self._auto_poll_ms / 1000.0)
        tk.Entry(auto, textvariable=self.auto_poll_sec_var, width=6).pack(side="left")

        tk.Label(auto, text=f"信号文件: {CASE_DONE_SIGNAL_FILE}").pack(side="left", padx=(20, 4))

        tk.Button(auto, text="刷新统计（本机拉服务端）", command=self.on_show_stats).pack(side="left", padx=20)

        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="本地 msh 列表（双击可设为下一个计算）").pack(anchor="w")
        self.listbox = tk.Listbox(left, height=22)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", self.on_pick_one)

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        tk.Label(right, text="日志").pack(anchor="w")
        self.log = ScrolledText(right, height=22)
        self.log.pack(fill="both", expand=True)

        self._log("GUI Ready. 先选择 msh 根目录，然后点“刷新并注册”。")
        self._log("结果先落本机 c2_FluentResults；Z盘可用时后台逐 case 上传到 NAS；成功后删本地并上报云端。")
        self._log("（现在计算在后台线程执行，UI 不会卡住）")

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _ui_log(self, msg: str):
        # 允许后台线程安全地写日志
        self.after(0, lambda: self._log(msg))

    def _refresh_listbox(self):
        self.listbox.delete(0, "end")
        root = self.mesh_root_var.get().strip()
        if not root or not os.path.isdir(root):
            return
        for p in list_msh(root, recursive=True):
            self.listbox.insert("end", p)

    def _infer_result_root(self, mesh_root: str) -> str:
        # 优先保持你原来的规则：c1 -> c2
        if "c1_SpaceclaimModels" in mesh_root:
            return mesh_root.replace("c1_SpaceclaimModels", "c2_FluentResults")
        # 否则：mesh_root 同级目录下的 c2_FluentResults
        return os.path.join(os.path.dirname(mesh_root), "c2_FluentResults")

    def _normalize_project_roots(self, chosen: str) -> tuple[str, str]:
        """
        归一化路径：无论用户选择
          - 项目 root（含 c1_SpaceclaimModels / c2_FluentResults / ...）
          - c1_SpaceclaimModels
          - c1_SpaceclaimModels/a1
        都强制得到：
          mesh_root = <项目root>/c1_SpaceclaimModels
          result_root = <项目root>/c2_FluentResults
        """
        if not chosen:
            return "", ""

        p = Path(chosen)
        try:
            # strict=False(默认)；即使部分路径不存在也尽量规整
            p = p.resolve()
        except Exception:
            p = Path(os.path.abspath(chosen))

        c1_dir = "c1_SpaceclaimModels"
        c2_dir = "c2_FluentResults"

        # 情况1：用户直接选中了 c1 或 c1 的子目录（不依赖磁盘存在性，纯路径分析）
        parts_lower = [x.lower() for x in p.parts]
        if c1_dir.lower() in parts_lower:
            idx = parts_lower.index(c1_dir.lower())
            project_root = Path(*p.parts[:idx])
            mesh_root = project_root / c1_dir
            result_root = project_root / c2_dir
            return str(mesh_root), str(result_root)

        # 情况2：用户选了项目root，或任意目录但其祖先里有项目root（依赖磁盘判断）
        cur = p
        while True:
            if (cur / c1_dir).is_dir():
                project_root = cur
                mesh_root = project_root / c1_dir
                result_root = project_root / c2_dir
                return str(mesh_root), str(result_root)

            if cur.parent == cur:
                break
            cur = cur.parent

        # 兜底：找不到项目结构就保持原逻辑（保证旧用法不崩）
        mesh_root = str(p)
        result_root = self._infer_result_root(mesh_root)
        return mesh_root, result_root

    def _set_computing(self, val: bool):
        state = "disabled" if val else "normal"
        self.btn_compute.configure(state=state)
        self.btn_scan.configure(state=state)

    # -------- 上传状态刷新（6）--------
    def _refresh_upload_status(self):
        try:
            st = self.worker.get_upload_status()
            q = st.get("queue_len", 0)
            last = st.get("last_case") or "-"
            msg = st.get("last_msg") or "-"
            
            # 新增：显示恢复状态
            rec = st.get("recovery_status", "")
            rec_n = st.get("recovery_count", 0)
            rec_str = ""
            if rec == "running":
                rec_str = " | Recovery: running..."
            elif rec == "done" and rec_n > 0:
                rec_str = f" | Recovered: {rec_n}"
            
            self.upload_status_var.set(f"UploadQueue: {q} | Last: {last} ({msg}){rec_str}")
        except Exception as e:
            print(f"上传状态刷新失败：{str(e)}")
        finally:
            self.after(UI_UPLOAD_STATUS_REFRESH_MS, self._refresh_upload_status)

    # -------- handlers --------
    def on_toggle_offline(self):
        flag = bool(self.offline_var.get())
        self.core.set_offline_mode(flag)
        self.worker.set_offline_mode(flag)

        # ✅ 离线：禁用需要服务器/NAS 的控件；在线：恢复
        def _set_widget_state(w, state: str):
            try:
                if w is not None:
                    w.config(state=state)
            except Exception:
                pass

        online_state = "disabled" if flag else "normal"
        _set_widget_state(getattr(self, "btn_ping", None), online_state)
        _set_widget_state(getattr(self, "btn_assign", None), online_state)
        _set_widget_state(getattr(self, "btn_put", None), online_state)
        _set_widget_state(getattr(self, "entry_assign_n", None), online_state)
        _set_widget_state(getattr(self, "entry_upload_n", None), online_state)

        if flag:
            self._log("[Offline] 已开启：不再与云服务器通信，不再进行NAS上传/下载。将仅计算本机已有case，并维护本地DB。")
        else:
            self._log("[Offline] 已关闭：恢复在线模式（云端调度 + NAS上传/下载）。")

    def on_ping(self):
        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name
        try:
            resp = self.core.ping()
            self._log(f"Ping: {resp}")
        except Exception as e:
            messagebox.showerror("Ping Failed", str(e))

    def on_choose_mesh_root(self):
        d = filedialog.askdirectory(title="选择 msh 根目录（包含.msh的文件夹）")
        if not d:
            return

        # 归一化：无论用户选项目root / c1 / c1/a1，都锁定到 c1 & c2
        mesh_root, res_root = self._normalize_project_roots(d)
        if not mesh_root:
            messagebox.showwarning("Invalid path", "无法定位项目结构（需要包含 c1_SpaceclaimModels）")
            return

        # UI 展示真正生效的 mesh_root（c1）
        self.mesh_root_var.set(mesh_root)

        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name

        self.core.register_mesh_root(mesh_root=mesh_root, result_root=res_root)
        self.core.set_offline_mode(bool(self.offline_var.get()))
        self.worker.set_offline_mode(bool(self.offline_var.get()))
        self.worker.update_paths(mesh_root=mesh_root, result_root=res_root, node_name=self.state.node_name)

        self._refresh_listbox()
        self._log(f"Chosen: {d}")
        self._log(f"Mesh root set: {mesh_root}")
        self._log(f"Result root set: {res_root}")

    def on_scan_register(self):
        chosen = self.mesh_root_var.get().strip()
        if not chosen:
            messagebox.showwarning("No mesh root", "请先选择 msh 根目录")
            return

        # 二次归一化：防止用户手动改输入框/历史值导致漂移
        mesh_root, res_root = self._normalize_project_roots(chosen)
        if not mesh_root:
            messagebox.showwarning("Invalid path", "无法定位项目结构（需要包含 c1_SpaceclaimModels）")
            return
        self.mesh_root_var.set(mesh_root)

        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name

        self.core.register_mesh_root(mesh_root=mesh_root, result_root=res_root)
        self.core.set_offline_mode(bool(self.offline_var.get()))
        self.worker.set_offline_mode(bool(self.offline_var.get()))
        self.worker.update_paths(mesh_root=mesh_root, result_root=res_root, node_name=self.state.node_name)

        try:
            resp = self.core.scan_and_register(recursive=True)
            self._refresh_listbox()
            self._log(f"Register done. new_count={resp.get('new_count')} total_local={self.listbox.size()}")
        except Exception as e:
            messagebox.showerror("Register Failed", str(e))

    def _silent_scan(self):
        """静默扫描：刷新列表但不输出日志"""
        chosen = self.mesh_root_var.get().strip()
        if not chosen:
            return

        mesh_root, res_root = self._normalize_project_roots(chosen)
        if not mesh_root:
            return

        self.mesh_root_var.set(mesh_root)
        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name

        self.core.register_mesh_root(mesh_root=mesh_root, result_root=res_root)
        self.worker.update_paths(mesh_root=mesh_root, result_root=res_root, node_name=self.state.node_name)

        try:
            self.core.scan_and_register(recursive=True)
            self._refresh_listbox()
        except Exception:
            pass

    def on_pick_one(self, _evt=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        path = self.listbox.get(sel[0])
        self._log(f"Picked: {path}")

    def on_compute_next_async(self):
        chosen = self.mesh_root_var.get().strip()
        if not chosen:
            messagebox.showwarning("No mesh root", "请先选择 msh 根目录")
            return

        # 二次归一化：防止用户选项目root/c1子目录或手动改输入框
        mesh_root, res_root = self._normalize_project_roots(chosen)
        if not mesh_root:
            messagebox.showwarning("Invalid path", "无法定位项目结构（需要包含 c1_SpaceclaimModels）")
            return
        self.mesh_root_var.set(mesh_root)

        if self.listbox.size() == 0:
            self._log("No local msh.")
            return

        with self._computing_lock:
            if self._is_computing:
                self._log("Already computing, please wait...")
                return
            self._is_computing = True

        self._set_computing(True)

        msh_path = self.listbox.get(0)
        node_name = self.node_var.get().strip() or self.state.node_name

        def job():
            t0 = time.time()
            try:
                self.state.node_name = node_name
                self.core.state.node_name = node_name

                # 确保 core/worker 根路径一致（mesh_root 固定为 c1，result_root 固定为 c2）
                self.core.register_mesh_root(mesh_root=mesh_root, result_root=res_root)
                self.worker.update_paths(mesh_root=mesh_root, result_root=res_root, node_name=node_name)

                self._ui_log(f"Compute start: {msh_path}")
                resp = self.core.compute_one_local(msh_path=msh_path, fluent_worker=self.worker)
                dt = time.time() - t0
                self._ui_log(f"Compute done ({dt/60:.1f} min): {resp}")
            except Exception as e:
                self._ui_log(f"[Compute ERROR] {e}")
            finally:
                self.after(0, self._on_compute_finished)

        threading.Thread(target=job, daemon=True).start()

    def _on_compute_finished(self):
        with self._computing_lock:
            self._is_computing = False
        self._set_computing(False)
        self._refresh_listbox()

    def on_put_in_pool(self):
        # 1. 在主线程获取 UI 变量 (GUI控件不能在子线程访问)
        chosen = self.mesh_root_var.get().strip()
        if not chosen:
            messagebox.showwarning("No mesh root", "请先选择 msh 根目录")
            return
            
        mesh_root, res_root = self._normalize_project_roots(chosen)
        if not mesh_root:
            messagebox.showwarning("Invalid path", "无法定位项目结构")
            return
        self.mesh_root_var.set(mesh_root) # 回显

        # 同步状态
        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name
        self.core.register_mesh_root(mesh_root=mesh_root, result_root=res_root)
        self.worker.update_paths(mesh_root=mesh_root, result_root=res_root, node_name=self.state.node_name)

        n = int(self.upload_n_var.get() or 1)
        if self.listbox.size() == 0:
            self._log("No local msh to put in pool.")
            return

        # 构造要上传的任务列表
        pick = []
        for i in range(min(n, self.listbox.size())):
            p = self.listbox.get(i)
            pick.append(make_case_key(mesh_root, p))

        # 2. 定义后台任务函数
        def upload_job():
            try:
                self._ui_log(f"=== 开始后台上传 {len(pick)} 个任务到 NAS ===")
                
                # 关键：传入 self._ui_log 作为回调
                self.core.put_selected_in_pool(pick, log_callback=self._ui_log)
                
                self._ui_log("=== 上传及注册全部完成 ===")
            except Exception as e:
                self._ui_log(f"[Upload Error] {e}")
            finally:
                # 3. 任务结束后，必须在主线程刷新 Listbox (因为文件被删了)
                self.after(0, self._refresh_listbox)

        # 3. 启动线程
        threading.Thread(target=upload_job, daemon=True).start()

    def on_assign_from_pool(self):
        # 1. 获取变量
        n = int(self.assign_n_var.get() or 1)

        # 2. 定义后台任务
        def assign_job():
            try:
                self._ui_log(f"=== 开始从服务器拉取 {n} 个任务 ===")
                
                # 关键：传入 self._ui_log
                jobs = self.core.assign_from_pool(n, log_callback=self._ui_log)
                
                # 如果拉到了任务，且之前列表是空的，可能需要提醒一下自动模式
                if jobs and self.auto_running:
                     self._ui_log("[Auto] 监测到新任务入库，自动模式将接管...")
                     
            except Exception as e:
                self._ui_log(f"[Assign Error] {e}")
            finally:
                # 3. 刷新列表显示新下载的文件
                self.after(0, self._refresh_listbox)

        # 3. 启动线程
        threading.Thread(target=assign_job, daemon=True).start()

    def on_show_stats(self):
        try:
            # 先让服务端扫描NAS并把“黑户case”补入DB
            rec = self.core.scan_and_recover_nas_pool()
            if rec and rec.get("ok") and (rec.get("found") is not None):
                self._log(f"[Recover] NAS scan found={rec.get('found')} recovered={rec.get('recovered')}")

            # 再拉统计（此时stats会包含刚恢复的case）
            st = self.core.get_stats()
            s = st.get("stats", st)
            self._log(
                f"STATS: total={s.get('total')} done={s.get('done')} failed={s.get('failed')} "
                f"avg={s.get('avg_sec'):.2f}s pool={s.get('pool_pending')} "
                f"nas_done={s.get('nas_done', '?')} nas_uploading={s.get('nas_uploading', '?')} "
                f"ETA={s.get('eta_sec')/3600:.2f}h"
            )
        except Exception as e:
            messagebox.showerror("Stats Failed", str(e))

    # ---- auto mode ----
    def on_auto_start(self):
        if self.auto_running:
            return
        self.auto_running = True
        
        sec = float(self.auto_poll_sec_var.get() or (self._auto_poll_ms / 1000.0))
        self._auto_poll_ms = max(500, int(sec * 1000))  # 最小 0.5s，避免刷爆

        # 首次点击不需要读last_sigonal，直接启动
        self._auto_last_sig = None

        self._log(f"Auto mode started. poll={self._auto_poll_ms/1000:.1f}s (signal-driven)")
        self.after(100, self._auto_tick)

    def on_auto_stop(self):
        self.auto_running = False
        self._log("Auto mode stopped.")

    def _auto_tick(self):
        if not self.auto_running:
            return
        
        try:
            # 1) 列表维护：如果显示为空，尝试静默扫描一次，以防是 UI 没刷新
            if self.mesh_root_var.get().strip() and self.listbox.size() == 0:
                self._silent_scan()

            current_count = self.listbox.size()

            # --- 逻辑 A: 消费者自动续杯 (Consumer Auto-Pull) ---
            # 触发条件：本地任务快没了且 当前没有正在拉取
            if current_count <= AUTO_ASSIGN_TRIGGER_THRESHOLD:
                if not self.core._is_auto_assigning:
                    threading.Thread(target=self._auto_consumer_job, daemon=True).start()

            # --- 逻辑 B: 生产者自动补货 (Producer Auto-Push) ---
            # 触发条件：本地任务充裕 (>= 20) 且 当前没有正在补货
            elif current_count >= PRODUCER_MIN_LOCAL_COUNT:
                if not self.core._is_auto_replenishing:
                    threading.Thread(target=self._auto_producer_job, daemon=True).start()

            # --- 逻辑 C: 计算任务调度 ---
            # 检查计算锁
            with self._computing_lock:
                is_computing = self._is_computing

            # 只有当列表有货，且当前没在计算时，才尝试启动计算
            if not is_computing and current_count > 0:
                # 信号检查：防止重复跑同一个 case
                sig = self._read_done_signal()
                should_run = False
                
                # 获取当前列表排第一的任务名
                current_top_path = self.listbox.get(0)
                # 注意：确保 make_case_key 已从 client_core 导入
                current_top_key = make_case_key(self.mesh_root_var.get(), current_top_path)
                
                # 解析上次完成的任务名 (从 self._auto_last_sig[1] 里解析)
                last_done_key = None
                if self._auto_last_sig and self._auto_last_sig[1]:
                    parts = self._auto_last_sig[1].split('\t')
                    if len(parts) >= 2:
                        last_done_key = parts[1].strip()

                # 【判定逻辑】
                # 1. 刚启动 -> 跑
                if self._auto_last_sig is None:
                    should_run = True
                # 2. 信号文件变了 -> 跑
                elif sig != self._auto_last_sig:
                    should_run = True
                # 3. 信号没变，但排第一的任务换人了 -> 说明上一个被Skip了或者被移走了 -> 强制跑下一个
                elif current_top_key != last_done_key:
                    should_run = True
                
                if should_run:
                    # 只有信号真正变了才打日志，避免 SKIP 重试时刷屏
                    if sig != self._auto_last_sig:
                        if sig and sig[1]:
                            self._log(f"[Auto] done detected: {sig[1]}")
                    
                    self._auto_last_sig = sig
                    self.on_compute_next_async()

        except Exception as e:
            # 避免日志刷屏，只在控制台打印关键错误
            print(f"[Auto Tick Error] {e}")

        finally:
            if self.auto_running:
                self.after(self._auto_poll_ms, self._auto_tick)

    # -------- 后台任务：自动消费者 (从池拉取) --------
    def _auto_consumer_job(self):
        # 1. 上锁
        self.core._is_auto_assigning = True
        try:
            # 2. 调用拉取逻辑 (直接复用 core 方法，log_callback 传 UI日志)
            new_jobs = self.core.assign_from_pool(AUTO_ASSIGN_BATCH, log_callback=self._ui_log)
            
            if new_jobs:
                self._ui_log(f"[Auto] 自动续杯成功: 拉取了 {len(new_jobs)} 个新任务")
                # 3. 必须刷新 UI，否则主循环看不到新文件，不会触发计算
                self.after(0, self._refresh_listbox)
                time.sleep(1)

        except Exception as e:
            self._ui_log(f"[Auto Consumer Error] {e}")
        finally:
            self.core._is_auto_assigning = False

    # -------- 后台任务：自动生产者 (向池补货) --------
    def _auto_producer_job(self):
        # ✅ 离线模式：自动补货（服务器池）无意义，直接跳过，避免刷屏
        if bool(getattr(self, "offline_var", None) and self.offline_var.get()):
            if not getattr(self, "_offline_auto_producer_warned", False):
                self._offline_auto_producer_warned = True
                self._ui_log("[Auto] 离线模式：已禁用自动补货到服务器池。")
            return
        
        # 1. 上锁
        self.core._is_auto_replenishing = True
        try:
            # 2. 询问服务器池子状态
            status = self.core.get_pool_status() # {"ok": True, "pool_pending": 50}
            if not status or not status.get("ok"):
                return

            pool_pending = int(status.get("pool_pending", 9999))
            
            # 3. 判断水位
            if pool_pending < POOL_TARGET_SIZE:
                needed = POOL_TARGET_SIZE - pool_pending
                batch = min(needed, AUTO_UPLOAD_BATCH)
                
                if batch > 0:
                    self._ui_log(f"[Auto] 池子缺货 ({pool_pending}/{POOL_TARGET_SIZE})，我是大户，开始自动补货 {batch} 个...")
                    
                    # 4. 获取补货列表
                    root = self.mesh_root_var.get()
                    if not root: 
                        return
                    all_files = list_msh(root, recursive=True)
                    all_keys = [make_case_key(root, f) for f in all_files]
                    
                    # 取后 N 个 (防止跟计算线程冲突)
                    pick_keys = all_keys[-batch:]
                    
                    if pick_keys:
                        # 执行补货 (原子上传)
                        self.core.put_selected_in_pool(pick_keys, log_callback=self._ui_log)
                        # 补货完成后刷新列表（因为本地文件被移走了）
                        self.after(0, self._refresh_listbox)
            
        except Exception as e:
            self._ui_log(f"[Auto Producer Error] {e}")
        finally:
            # 5. 解锁
            self.core._is_auto_replenishing = False

    def _read_done_signal(self):
        try:
            if not os.path.exists(CASE_DONE_SIGNAL_FILE):
                return None
            # 用 mtime + 内容双保险（mtime足够，内容用来显示case_key更直观）
            m = os.path.getmtime(CASE_DONE_SIGNAL_FILE)
            with open(CASE_DONE_SIGNAL_FILE, "r", encoding="utf-8") as f:
                s = f.read().strip()
            return (m, s)
        except Exception:
            return None


if __name__ == "__main__":
    App().mainloop()
