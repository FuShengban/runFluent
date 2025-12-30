# client_app.py
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from client_core import ClientCore, ClientState, default_node_name, list_msh, make_case_key
from config import ASSIGN_BATCH_DEFAULT, UPLOAD_BATCH_DEFAULT

# 如果你已有 fluent_worker.py，就取消注释并保证有 process_case(msh_path)
# from fluent_worker import FluentWorker

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fluent Cluster Client (Tkinter)")
        self.geometry("980x620")

        self.state = ClientState(node_name=default_node_name())
        self.core = ClientCore(self.state)

        # self.worker = FluentWorker()  # 接入Fluent
        self.worker = None             # 先不接也能跑通“登记/看板/调度”

        self.auto_running = False
        self.auto_interval_ms = 5 * 60 * 1000  # 默认5分钟跑一次（你可在UI改）

        self._build_ui()

    def _build_ui(self):
        # ---- 顶部配置区 ----
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Node Name:").pack(side="left")
        self.node_var = tk.StringVar(value=self.state.node_name)
        tk.Entry(top, textvariable=self.node_var, width=20).pack(side="left", padx=6)

        tk.Button(top, text="Ping Server", command=self.on_ping).pack(side="left", padx=6)

        tk.Button(top, text="选择 msh 根目录", command=self.on_choose_mesh_root).pack(side="left", padx=6)
        self.mesh_root_var = tk.StringVar(value="")
        tk.Entry(top, textvariable=self.mesh_root_var, width=55).pack(side="left", padx=6)

        # ---- 动作区 ----
        mid = tk.Frame(self)
        mid.pack(fill="x", padx=10, pady=6)

        tk.Button(mid, text="刷新并注册（热更新）", command=self.on_scan_register).pack(side="left", padx=6)

        tk.Button(mid, text="算下一个（本地）", command=self.on_compute_next).pack(side="left", padx=6)

        tk.Label(mid, text="拉任务数量:").pack(side="left", padx=(20, 4))
        self.assign_n_var = tk.IntVar(value=ASSIGN_BATCH_DEFAULT)
        tk.Entry(mid, textvariable=self.assign_n_var, width=5).pack(side="left")
        tk.Button(mid, text="从服务器池拉任务", command=self.on_assign_from_pool).pack(side="left", padx=6)

        tk.Label(mid, text="补货数量:").pack(side="left", padx=(20, 4))
        self.upload_n_var = tk.IntVar(value=UPLOAD_BATCH_DEFAULT)
        tk.Entry(mid, textvariable=self.upload_n_var, width=5).pack(side="left")
        tk.Button(mid, text="补货到服务器池（限流）", command=self.on_put_in_pool).pack(side="left", padx=6)

        # ---- 自动模式 ----
        auto = tk.Frame(self)
        auto.pack(fill="x", padx=10, pady=6)

        tk.Button(auto, text="启动自动模式", command=self.on_auto_start).pack(side="left", padx=6)
        tk.Button(auto, text="停止自动模式", command=self.on_auto_stop).pack(side="left", padx=6)

        tk.Label(auto, text="自动间隔(分钟):").pack(side="left", padx=(20,4))
        self.auto_min_var = tk.IntVar(value=5)
        tk.Entry(auto, textvariable=self.auto_min_var, width=5).pack(side="left")

        tk.Button(auto, text="刷新统计（本机拉服务端）", command=self.on_show_stats).pack(side="left", padx=20)

        # ---- 左侧：本地文件列表 ----
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="本地 msh 列表（双击可设为下一个计算）").pack(anchor="w")
        self.listbox = tk.Listbox(left, height=18)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", self.on_pick_one)

        # ---- 右侧：日志 ----
        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10,0))

        tk.Label(right, text="日志").pack(anchor="w")
        self.log = ScrolledText(right, height=18)
        self.log.pack(fill="both", expand=True)

        self._log("GUI Ready. 先选择 msh 根目录，然后点“刷新并注册”。")

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _refresh_listbox(self):
        self.listbox.delete(0, "end")
        root = self.mesh_root_var.get().strip()
        if not root or not os.path.isdir(root):
            return
        for p in list_msh(root, recursive=True):
            self.listbox.insert("end", p)

    # ---- handlers ----
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
        self.mesh_root_var.set(d)
        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name
        self.core.register_mesh_root(mesh_root=d)
        self._refresh_listbox()
        self._log(f"Mesh root set: {d}")

    def on_scan_register(self):
        root = self.mesh_root_var.get().strip()
        if not root:
            messagebox.showwarning("No mesh root", "请先选择 msh 根目录")
            return
        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name
        self.core.register_mesh_root(mesh_root=root)
        try:
            resp = self.core.scan_and_register(recursive=True)
            self._refresh_listbox()
            self._log(f"Register done. new_count={resp.get('new_count')} total_local={self.listbox.size()}")
        except Exception as e:
            messagebox.showerror("Register Failed", str(e))

    def on_pick_one(self, _evt=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        path = self.listbox.get(sel[0])
        self._log(f"Picked: {path}")

    def on_compute_next(self):
        root = self.mesh_root_var.get().strip()
        if not root:
            messagebox.showwarning("No mesh root", "请先选择 msh 根目录")
            return
        if self.listbox.size() == 0:
            self._log("No local msh. 你可以点“从服务器池拉任务”或手动拷贝后点“刷新并注册”。")
            return

        msh_path = self.listbox.get(0)
        self.state.node_name = self.node_var.get().strip() or self.state.node_name
        self.core.state.node_name = self.state.node_name
        self.core.register_mesh_root(mesh_root=root)

        self._log(f"Compute local: {msh_path}")
        resp = self.core.compute_one_local(msh_path=msh_path, fluent_worker=self.worker)

        # 这里你可按项目需求：算完就把 msh 移走/删除；我先不强制操作，避免误删
        # 建议：算完后移动到 processed/，你想要我也可以给你加“移动策略”下拉框。

        self._log(f"Compute result: {resp}")
        # 刷新列表（如果你手动移动/删除了，它也能更新）
        self._refresh_listbox()

    def on_put_in_pool(self):
        root = self.mesh_root_var.get().strip()
        if not root:
            messagebox.showwarning("No mesh root", "请先选择 msh 根目录")
            return
        n = int(self.upload_n_var.get() or 1)
        if self.listbox.size() == 0:
            self._log("No local msh to put in pool.")
            return

        # 选择前n个作为“补货候选”（你也可以改成“选中项”）
        pick = []
        for i in range(min(n, self.listbox.size())):
            p = self.listbox.get(i)
            pick.append(make_case_key(root, p))

        try:
            status = self.core.get_pool_status()
            self._log(f"Pool status before: {status}")
            resp = self.core.put_selected_in_pool(pick)
            self._log(f"Put in pool: {resp}")
            self._log("注意：这里是‘标记进入池子’，真正文件传输（.msh上云）你可以后续接SSH/或手动传。")
        except Exception as e:
            messagebox.showerror("Put In Pool Failed", str(e))

    def on_assign_from_pool(self):
        n = int(self.assign_n_var.get() or 1)
        try:
            jobs = self.core.assign_from_pool(n)
            self._log(f"Assigned {len(jobs)} jobs: {jobs}")
            self._log("提示：这里拿到的是池子分配结果。若你要自动下载.msh到本机，需要再接你原来的 ssh.py 下载逻辑。")
        except Exception as e:
            messagebox.showerror("Assign Failed", str(e))

    def on_show_stats(self):
        try:
            st = self.core.get_stats()
            self._log(f"STATS: total={st.get('total')} done={st.get('done')} failed={st.get('failed')} "
                      f"avg={st.get('avg_sec'):.2f}s pool={st.get('pool_pending')} "
                      f"ETA={st.get('eta_sec')/3600:.2f}h nodes={st.get('active_nodes')}")
        except Exception as e:
            messagebox.showerror("Stats Failed", str(e))

    # ---- auto mode ----
    def on_auto_start(self):
        if self.auto_running:
            return
        mins = int(self.auto_min_var.get() or 5)
        self.auto_interval_ms = max(mins, 1) * 60 * 1000
        self.auto_running = True
        self._log(f"Auto mode started. interval={mins} min")
        self.after(100, self._auto_tick)

    def on_auto_stop(self):
        self.auto_running = False
        self._log("Auto mode stopped.")

    def _auto_tick(self):
        if not self.auto_running:
            return
        try:
            # 自动模式做的事（分钟级，不会几秒轮询）：
            # 1) 刷新登记（热更新）
            if self.mesh_root_var.get().strip():
                self.on_scan_register()
            # 2) 如果本地有就算一个
            if self.listbox.size() > 0:
                self.on_compute_next()
            # 3) 你也可以加：自动NAS同步、自动拉任务等（需要你确认策略）
        except Exception as e:
            self._log(f"[Auto] error: {e}")
        finally:
            self.after(self.auto_interval_ms, self._auto_tick)

if __name__ == "__main__":
    App().mainloop()
