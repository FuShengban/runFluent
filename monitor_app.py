# monitor_app.py
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, simpledialog, filedialog
from tkinter.scrolledtext import ScrolledText
from datetime import datetime

from client_core import ClientCore, ClientState, default_node_name


class Monitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fluent Cluster Monitor")
        self.geometry("1600x800")

        # 监控客户端
        self.core = ClientCore(ClientState(node_name=default_node_name() + "_MON"))

        # ===== 顶部：控制区 =====
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        self.btn_refresh = tk.Button(top, text="刷新(统计+明细)", command=self.refresh_all)
        self.btn_refresh.pack(side="left")

        # 删除按钮
        self.btn_delete = tk.Button(top, text="🗑 删除选中", command=self.delete_selected,
                            bg="#FFCDD2", fg="#B71C1C")
        self.btn_delete.pack(side="left", padx=10)
        
        # 自动刷新按钮
        self.btn_auto = tk.Button(top, text="▶ 开启自动刷新", command=self.toggle_auto, 
                                   bg="#4CAF50", fg="white", width=14)
        self.btn_auto.pack(side="left", padx=8)

        # Ping 按钮
        self.btn_ping = tk.Button(top, text="Ping Server", command=self.on_ping)
        self.btn_ping.pack(side="left", padx=8)

        self.offline_var = tk.BooleanVar(value=False)
        self.offline_db_path = tk.StringVar(value="")

        tk.Checkbutton(top, text="离线DB模式", variable=self.offline_var,
                    command=self.on_toggle_offline).pack(side="left", padx=(10, 4))

        self.btn_pick_db = tk.Button(top, text="选择DB文件", command=self.pick_offline_db)
        self.btn_pick_db.pack(side="left", padx=6)

        self.lbl_db = tk.Label(top, textvariable=self.offline_db_path, fg="#666")
        self.lbl_db.pack(side="left", padx=6)

        # 状态指示器
        self.auto_status_var = tk.StringVar(value="")
        self.lbl_auto_status = tk.Label(top, textvariable=self.auto_status_var, 
                                         font=("Consolas", 10), fg="#666")
        self.lbl_auto_status.pack(side="left", padx=10)

        # 上次刷新时间
        self.last_refresh_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.last_refresh_var, fg="#888").pack(side="right")

        # ===== 筛选区 =====
        filt = tk.Frame(self)
        filt.pack(fill="x", padx=10)

        tk.Label(filt, text="Status:").pack(side="left")
        self.var_status = tk.StringVar(value="")
        self.cb_status = ttk.Combobox(filt, textvariable=self.var_status, width=12, 
                                       values=["", "PENDING", "ASSIGNED", "COMPLETED", "FAILED"])
        self.cb_status.pack(side="left", padx=6)

        tk.Label(filt, text="NAS:").pack(side="left")
        self.var_nas = tk.StringVar(value="")
        self.cb_nas = ttk.Combobox(filt, textvariable=self.var_nas, width=12, 
                                    values=["", "done", "uploading", "error"])
        self.cb_nas.pack(side="left", padx=6)

        tk.Label(filt, text="Query:").pack(side="left")
        self.var_q = tk.StringVar(value="")
        tk.Entry(filt, textvariable=self.var_q, width=30).pack(side="left", padx=6)

        tk.Label(filt, text="Limit:").pack(side="left")
        self.var_limit = tk.IntVar(value=500)
        tk.Entry(filt, textvariable=self.var_limit, width=6).pack(side="left", padx=6)

        tk.Button(filt, text="查询", command=self.refresh_jobs).pack(side="left", padx=8)

        # ===== 中间：统计文本 (保留 LabelFrame，因为这里只有一层，不丑) =====
        stat_frame = tk.LabelFrame(self, text="Stats")
        stat_frame.pack(fill="x", padx=10, pady=8)

        self.stats_text = tk.StringVar(value="")
        tk.Label(stat_frame, textvariable=self.stats_text, anchor="w", justify="left", 
                 font=("Consolas", 11)).pack(fill="x", padx=8, pady=6)

        # 1. 扁平化 PanedWindow
        paned = tk.PanedWindow(self, orient="vertical", sashwidth=6, sashrelief="flat", bg="#d9d9d9")
        paned.pack(fill="both", expand=True, padx=10, pady=8)

        # ---------------- 上半部分：列表 ----------------
        list_pane = tk.Frame(paned) 
        paned.add(list_pane, minsize=150)

        # 添加标题栏
        lbl_list_title = tk.Label(list_pane, text="Jobs (双击复制 case_key)", anchor="w", font=("TkDefaultFont", 9, "bold"))
        lbl_list_title.pack(fill="x", pady=(0, 2))

        # 列表容器
        tree_container = tk.Frame(list_pane)
        tree_container.pack(fill="both", expand=True)

        self.columns_config = [
            ("id", "ID", 30),
            ("case_key", "CASE_KEY", 200),
            ("case_name", "CASE_NAME", 100),
            ("status", "STATUS", 100),
            ("compute_node", "COMPUTE_NODE", 100),
            ("duration", "DURATION", 80),
            ("nas_status", "NAS", 80),
            ("result_path", "RESULT_PATH", 200),
            ("nas_path", "NAS_PATH", 200),
            ("created", "CREATED", 120),
            ("updated", "UPDATED", 120),
            ("nas_error", "NAS_ERROR", 200),
        ]
        columns = [c[0] for c in self.columns_config]
        
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=20)
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        for col_id, col_name, col_width in self.columns_config:
            self.tree.heading(col_id, text=col_name, anchor="w", command=lambda c=col_id: self._sort_column(c))
            self.tree.column(col_id, width=col_width, minwidth=50, anchor="w")
        self.tree.bind("<Double-1>", self._on_double_click)

        # ---------------- 下半部分：日志 ----------------
        log_pane = tk.Frame(paned)
        paned.add(log_pane, minsize=80)

        # 日志标题
        lbl_log_title = tk.Label(log_pane, text="Log", anchor="w", font=("TkDefaultFont", 9, "bold"))
        lbl_log_title.pack(fill="x", pady=(4, 2)) # pady 让标题和上面的分割线保持距离

        # 日志框
        self.log_box = ScrolledText(log_pane, height=8)
        self.log_box.pack(fill="both", expand=True)

        # 初始化变量
        self.auto = False
        self._auto_interval = 10000
        self._sort_reverse = {}
        self._countdown = 10
        self.refresh_all()

    def pick_offline_db(self):
        p = filedialog.askopenfilename(
            title="选择离线DB（offline_project.db）",
            filetypes=[("SQLite DB", "*.db"), ("All Files", "*.*")]
        )
        if not p:
            return
        self.offline_db_path.set(p)
        # 如果当前已经是离线模式，立刻切换到该DB
        if bool(self.offline_var.get()):
            self.core.set_offline_mode(True, db_path=p)
            self._apply_offline_ui_state(True)
            self.refresh_all()

    def on_toggle_offline(self):
        flag = bool(self.offline_var.get())
        if flag:
            dbp = self.offline_db_path.get().strip()
            if not dbp:
                # 让用户选一次
                self.pick_offline_db()
                # pick_offline_db 里会 refresh；这里直接 return
                return
            self.core.set_offline_mode(True, db_path=dbp)
        else:
            self.core.set_offline_mode(False)
        self._apply_offline_ui_state(flag)
        self.refresh_all()

    def _apply_offline_ui_state(self, offline: bool):
        # 离线：禁用删除 + ping（刷新/自动刷新保留）
        state = "disabled" if offline else "normal"
        self.btn_delete.config(state=state)
        self.btn_ping.config(state=state)

    def _fmt_ts(self, ts):
        """时间戳格式化为可读时间"""
        if not ts:
            return ""
        try:
            dt = datetime.fromtimestamp(int(ts))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)

    def _fmt_duration(self, sec):
        """格式化时长"""
        if not sec:
            return ""
        try:
            sec = float(sec)
            if sec < 60:
                return f"{sec:.1f}s"
            elif sec < 3600:
                return f"{sec/60:.1f}m"
            else:
                return f"{sec/3600:.2f}h"
        except Exception:
            return str(sec)

    def on_ping(self):
        try:
            resp = self.core.ping()
            self.log(f"Ping: {resp}")
        except Exception as e:
            messagebox.showerror("Ping Failed", str(e))

    def _nas_state(self, row: dict) -> str:
        if row.get("nas_uploaded"):
            return "✅ DONE"
        if row.get("nas_uploading"):
            return "⏳ UPLOADING"
        if row.get("nas_last_error"):
            return "❌ ERROR"
        return "-"

    def _status_display(self, status: str) -> str:
        """状态显示"""
        icons = {
            "PENDING": "⏸ PENDING",
            "ASSIGNED": "🔄 ASSIGNED",
            "COMPLETED": "✅ COMPLETED",
            "FAILED": "❌ FAILED",
        }
        return icons.get(status, status or "-")

    def log(self, s: str):
        self.log_box.insert("end", s + "\n")
        self.log_box.see("end")

    def refresh_stats(self):
        try:
            st = self.core.get_stats()
        except Exception as e:
            self.log(f"Stats error: {e}")
            st = {}
        
        if isinstance(st, set):
            st = list(st)

        total = st.get("total", 0)
        done = st.get("done", 0)
        failed = st.get("failed", 0)
        avg = st.get("avg_sec", 0.0)
        pool_pending = st.get("pool_pending", 0)
        nas_done = st.get("nas_done", 0)
        nas_uploading = st.get("nas_uploading", 0)
        eta_h = (st.get("eta_sec", 0.0) or 0.0) / 3600.0

        # 计算进度百分比
        progress = (done / total * 100) if total > 0 else 0

        self.stats_text.set(
            f"TOTAL: {total}   |   ✅ DONE: {done} ({progress:.1f}%)   |   ❌ FAILED: {failed}   |   ⏱ AVG: {self._fmt_duration(avg)}\n"
            f"📦 POOL_PENDING: {pool_pending}   |   📤 NAS_DONE: {nas_done}   |   ⏳ NAS_UPLOADING: {nas_uploading}   |   🕐 ETA: {eta_h:.2f}h"
        )

    def refresh_jobs(self):
        # 清表
        for item in self.tree.get_children():
            self.tree.delete(item)

        limit = int(self.var_limit.get() or 200)
        status = self.var_status.get().strip()
        nas = self.var_nas.get().strip()
        q = self.var_q.get().strip()

        try:
            rows = self.core.get_jobs(limit=limit, status=status, nas=nas, q=q, order="updated")
        except Exception as e:
            self.log(f"Query error: {e}")
            rows = []
            
        if isinstance(rows, set):
            rows = list(rows)

        for r in rows:
            self.tree.insert(
                "",
                "end",
                values=(
                    r.get("id", ""),
                    r.get("case_key", ""),
                    r.get("case_name", ""),
                    self._status_display(r.get("status", "")),
                    r.get("compute_node", "") or "-",
                    self._fmt_duration(r.get("duration_sec")),
                    self._nas_state(r),
                    r.get("result_path", "") or "-",
                    r.get("nas_path", "") or "-",
                    self._fmt_ts(r.get("created_at")),
                    self._fmt_ts(r.get("updated_at")),
                    (r.get("nas_last_error") or "")[:100],
                ),
            )

        self.log(f"Loaded {len(rows)} jobs  (status='{status}', nas='{nas}', q='{q}', limit={limit})")

    def refresh_all(self):
        # ✅ 确保离线模式下 core 已绑定到指定DB
        if bool(self.offline_var.get()):
            dbp = self.offline_db_path.get().strip()
            if dbp:
                self.core.set_offline_mode(True, db_path=dbp)
                self._apply_offline_ui_state(True)
        
        self.refresh_stats()
        self.refresh_jobs()
        
        # 显示上次刷新时间
        now = datetime.now().strftime("%H:%M:%S")
        self.last_refresh_var.set(f"Last: {now}")

    def toggle_auto(self):
        """切换自动刷新状态"""
        if self.auto:
            self.stop_auto()
        else:
            self.start_auto()

    def start_auto(self):
        """开启自动刷新"""
        self.auto = True
        self._countdown = 10
        
        # 更新按钮样式
        self.btn_auto.configure(text="⏹ 停止自动刷新", bg="#f44336")
        self.lbl_auto_status.configure(fg="#4CAF50")
        
        self.log("Auto refresh started (every 10s)")
        self._tick()

    def stop_auto(self):
        """停止自动刷新"""
        self.auto = False
        
        # 更新按钮样式
        self.btn_auto.configure(text="▶ 开启自动刷新", bg="#4CAF50")
        self.auto_status_var.set("⏸ 已停止")
        self.lbl_auto_status.configure(fg="#888")
        
        self.log("Auto refresh stopped")

    def _tick(self):
        if not self.auto:
            return
        
        # 更新倒计时显示
        self.auto_status_var.set(f"🔄 {self._countdown}s 后刷新")
        
        if self._countdown <= 0:
            # 执行刷新
            self.refresh_all()
            self._countdown = 10  # 重置
        else:
            self._countdown -= 1
        
        # 每秒调用一次
        self.after(1000, self._tick)

    def _sort_column(self, col):
        """点击列标题排序"""
        reverse = self._sort_reverse.get(col, False)
        
        items = [(self.tree.set(item, col), item) for item in self.tree.get_children("")]
        
        # 尝试数字排序
        try:
            items.sort(key=lambda x: float(x[0].replace("s","").replace("m","").replace("h","").replace("✅","").replace("❌","").replace("⏸","").replace("🔄","").replace("⏳","").strip()) if x[0] and x[0][0].isdigit() else 0, reverse=reverse)
        except:
            items.sort(key=lambda x: x[0], reverse=reverse)
        
        for idx, (_, item) in enumerate(items):
            self.tree.move(item, "", idx)
        
        self._sort_reverse[col] = not reverse

    def _on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, "values")
        if not vals:
            return
        case_key = vals[1]
        try:
            self.clipboard_clear()
            self.clipboard_append(case_key)
            self.log(f"Copied case_key: {case_key}")
        except Exception as e:
            self.log(f"Copy failed: {e}")

    def delete_selected(self):
        """处理删除按钮点击事件"""
        if bool(self.offline_var.get()):
            messagebox.showinfo("离线模式", "离线DB模式下不支持删除（仅用于总览/统计）。")
            return

        # 1. 获取当前选中的行
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先在表格中选择要删除的条目！\n(支持按住 Ctrl 或 Shift 多选)")
            return

        # 2. 提取 case_key
        keys_to_delete = []
        for item in selected_items:
            vals = self.tree.item(item, "values")
            if vals and len(vals) > 1:
                keys_to_delete.append(vals[1])
        
        if not keys_to_delete:
            return

        # 3. 确认警告
        msg = (
            f"你选中了 {len(keys_to_delete)} 个任务。\n\n"
            f"删除操作将执行以下动作：\n"
            f"1. 从云端数据库永久移除这些任务的记录。\n"
            f"2. 从NAS端删除这些任务对应的物理文件。\n\n"
            f"该操作不可恢复，确定要继续吗？"
        )
        if not messagebox.askyesno("危险操作警告", msg, icon='warning'):
            return

        # 4. 输入管理员密码
        pwd = simpledialog.askstring("管理员验证", "请输入删除密码进行确认:", show="*")
        if not pwd:
            return

        # 5. 调用云服务器接口（服务器会处理数据库删除 + SSH删除NAS文件）
        try:
            resp = self.core.delete_jobs(case_keys=keys_to_delete, password=pwd)
            
            if not resp.get("ok"):
                err_msg = resp.get("error", "未知错误")
                self.log(f"删除失败: {err_msg}")
                messagebox.showerror("操作失败", f"服务器拒绝了删除请求：\n{err_msg}")
                return
            
            # 汇总结果
            deleted_db = resp.get("deleted_count", 0)
            deleted_files = resp.get("deleted_files", 0)
            ssh_errors = resp.get("ssh_errors", [])
            
            log_msg = f"删除完成: 数据库 -{deleted_db} 条, NAS文件 -{deleted_files} 个"
            if ssh_errors:
                log_msg += f"\n⚠ SSH错误: {len(ssh_errors)} 个"
                for err in ssh_errors[:3]:
                    log_msg += f"\n  - {err}"
            
            self.log(log_msg)
            messagebox.showinfo("完成", log_msg)
            
            # 自动刷新列表
            self.refresh_all()

        except Exception as e:
            self.log(f"通信错误: {e}")
            messagebox.showerror("通信错误", str(e))


if __name__ == "__main__":
    Monitor().mainloop()
