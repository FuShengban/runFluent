# server_service.py
import os
import time
import threading
import socket
from typing import Dict, Any

from config import SERVER_BIND_HOST, SERVER_PORT, POOL_LIMIT
from protocol import recv_json, send_json
from db_manager import JobDB

DB_PATH = os.environ.get("JOB_DB_PATH", "project.db")
db = JobDB(DB_PATH)

def handle(req: Dict[str, Any]) -> Dict[str, Any]:
    action = req.get("action")
    node = req.get("node_name", "Unknown")

    if action == "PING":
        return {"ok": True, "pong": True, "server_time": int(time.time())}

    if action == "REGISTER_CASES":
        cases = req.get("cases", [])
        mesh_root = req.get("mesh_root", "")
        new_count = db.register_cases(node=node, mesh_root=mesh_root, cases=cases)
        return {"ok": True, "new_count": new_count}

    if action == "GET_POOL_STATUS":
        return {"ok": True, "pool_pending": db.pool_count(), "pool_limit": POOL_LIMIT}

    if action == "PUT_IN_POOL":
        # 客户端传 case_keys，服务端按 pool_limit 截断允许进入池子的数量
        case_keys = req.get("case_keys", [])
        pool_pending = db.pool_count()
        quota = max(POOL_LIMIT - pool_pending, 0)
        allow = case_keys[:quota]
        updated = db.mark_in_pool(allow, in_pool=1)
        return {"ok": True, "requested": len(case_keys), "allowed": len(allow), "marked": updated, "pool_pending": db.pool_count()}

    if action == "ASSIGN_FROM_POOL":
        n = int(req.get("n", 1))
        jobs = db.assign_from_pool(node=node, n=n)
        return {"ok": True, "jobs": jobs}

    if action == "REPORT_STARTED":
        db.report_started(node=node,
                          case_key=req["case_key"],
                          compute_path=req.get("compute_path", ""),
                          result_path=req.get("result_path", ""))
        return {"ok": True}

    if action == "REPORT_DONE":
        db.report_done(node=node, case_key=req["case_key"], duration_sec=float(req.get("duration_sec", 0)))
        return {"ok": True}

    if action == "REPORT_FAILED":
        db.report_failed(node=node, case_key=req["case_key"])
        return {"ok": True}

    if action == "REPORT_NAS":
        db.report_nas(case_key=req["case_key"], uploaded=int(req.get("uploaded", 1)))
        return {"ok": True}

    if action == "GET_STATS":
        return {"ok": True, "stats": db.stats()}

    if action == "EXPORT_CSV":
        out = req.get("csv_path", "jobs_export.csv")
        db.export_csv(out)
        return {"ok": True, "csv_path": out}

    return {"ok": False, "error": f"Unknown action: {action}"}

def serve_forever():
    print(f"[Server] DB={DB_PATH}")
    print(f"[Server] Listening on {SERVER_BIND_HOST}:{SERVER_PORT}  POOL_LIMIT={POOL_LIMIT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((SERVER_BIND_HOST, SERVER_PORT))
        server.listen(50)

        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=client_thread, args=(conn, addr), daemon=True)
            t.start()

def client_thread(conn: socket.socket, addr):
    with conn:
        try:
            req = recv_json(conn)
            resp = handle(req) if req else {"ok": False, "error": "Empty request"}
        except Exception as e:
            resp = {"ok": False, "error": str(e)}
        send_json(conn, resp)

if __name__ == "__main__":
    serve_forever()
