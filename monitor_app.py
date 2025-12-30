# monitor_app.py
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

from client_core import ClientCore, ClientState, default_node_name

class Monitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Fluent Cluster Monitor (Tkinter)")
        self.geometry("820x520")

        self.core = ClientCore(ClientState(node_name=default_node_name() + "_MON"))

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        tk.Button(top, text="刷新统计", command=self.refresh).pack(side="left")
        tk.Button(top, text="每10秒自动刷新", command=self.auto_10s).pack(side="left", padx=8)
        tk.Button(top, text="停止自动刷新", command=self.stop_auto).pack(side="left")

        self.text = ScrolledText(self, height=24)
        self.text.pack(fill="both", expand=True, padx=10, pady=8)

        self.auto = False
        self.refresh()

    def log(self, s: str):
        self.text.delete("1.0", "end")
        self.text.insert("end", s)
        self.text.see("end")

    def refresh(self):
        st = self.core.get_stats()
        lines = []
        lines.append(f"TOTAL: {st.get('total')}   DONE: {st.get('done')}   FAILED: {st.get('failed')}")
        lines.append(f"AVG(sec/case): {st.get('avg_sec'):.2f}   POOL_PENDING: {st.get('pool_pending')}   NAS_DONE: {st.get('nas_done')}")
        lines.append(f"ACTIVE_NODES: {st.get('active_nodes')}   ETA(hours): {st.get('eta_sec')/3600:.2f}")
        lines.append("")
        lines.append("---- Node Ranking (Completed) ----")
        for it in st.get("by_node", []):
            lines.append(f"{it['node']:<25} {it['completed']}")
        self.log("\n".join(lines))

    def auto_10s(self):
        self.auto = True
        self._tick()

    def stop_auto(self):
        self.auto = False

    def _tick(self):
        if not self.auto:
            return
        self.refresh()
        self.after(10_000, self._tick)

if __name__ == "__main__":
    Monitor().mainloop()
