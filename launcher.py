# launcher.py
import tkinter as tk
from tkinter import messagebox

def start_monitor():
    import monitor_app  # 会触发 monitor_app.py 的 __main__ 逻辑吗？不会，所以我们直接调用
    monitor_app.Monitor().mainloop()

def start_client():
    import client_app
    client_app.App().mainloop()

def main():
    root = tk.Tk()
    root.title("Fluent Cluster Launcher")
    root.geometry("420x200")
    root.resizable(False, False)

    tk.Label(root, text="请选择启动模式", font=("微软雅黑", 14)).pack(pady=20)

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)

    tk.Button(btn_frame, text="看板模式（Monitor）", width=18, height=2, command=lambda: (root.destroy(), start_monitor())).grid(row=0, column=0, padx=10)
    tk.Button(btn_frame, text="计算节点（Client）", width=18, height=2, command=lambda: (root.destroy(), start_client())).grid(row=0, column=1, padx=10)

    tk.Label(root, text="服务器请在云端运行 server_service.py", fg="gray").pack(side="bottom", pady=10)

    root.mainloop()

if __name__ == "__main__":
    main()
