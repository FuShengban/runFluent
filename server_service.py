# server_service.py
import os
import threading
import socket
from typing import Dict, Any
from pathlib import Path

from config import FLUENT_RESULT_FILE_PATTERNS, SERVER_BIND_HOST, SERVER_PORT, POOL_LIMIT, NAS_POOL_PATH
from config_pass import ADMIN_PASSWORD, NAS_SSH_HOST, NAS_SSH_PORT, NAS_SSH_USER, NAS_SSH_PASSWORD, NAS_SSH_KEYFILE, NAS_SSH_TIMEOUT
from protocol import recv_json, send_json
from db_manager import JobDB

DB_PATH = os.environ.get("JOB_DB_PATH", "project.db")
db = JobDB(DB_PATH)


def _ssh_delete_nas_files(paths_to_delete: list) -> tuple:
    """
    通过SSH连接NAS删除文件
    paths_to_delete: [{"case_key": "...", "nas_path": "/vol1/1007/..."}]
    返回: (成功删除文件数, 错误列表)
    """
    try:
        import paramiko
    except ImportError:
        return 0, ["paramiko not installed on server"]

    deleted_count = 0
    errors = []
    
    if not paths_to_delete:
        return 0, []
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 连接NAS
        if NAS_SSH_KEYFILE:
            ssh.connect(
                NAS_SSH_HOST, 
                port=NAS_SSH_PORT, 
                username=NAS_SSH_USER,
                key_filename=NAS_SSH_KEYFILE, 
                timeout=NAS_SSH_TIMEOUT
            )
        else:
            ssh.connect(
                NAS_SSH_HOST, 
                port=NAS_SSH_PORT, 
                username=NAS_SSH_USER,
                password=NAS_SSH_PASSWORD, 
                timeout=NAS_SSH_TIMEOUT
            )
        
        for item in paths_to_delete:
            nas_dir = item.get("nas_path", "")
            case_key = item.get("case_key", "")
            
            if not nas_dir or not case_key:
                continue
            
            stem = Path(case_key).stem
            patterns = [p.format(stem=stem) for p in FLUENT_RESULT_FILE_PATTERNS]
            for name in patterns:
                fp = f"{nas_dir}/{name}"
                cmd = f"rm -f '{fp}'"
                try:
                    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=10)
                    exit_code = stdout.channel.recv_exit_status()
                    if exit_code == 0:
                        deleted_count += 1
                except Exception as e:
                    errors.append(f"{fp}: {e}")
        
        ssh.close()
        
    except Exception as e:
        errors.append(f"SSH connection failed: {e}")
    
    return deleted_count, errors

def _ssh_scan_nas_files() -> list:
    """
    通过 SSH 连接 NAS，执行 find 命令扫描中的所有 .msh 文件，
    并计算出 case_key (相对路径)。
    """
    try:
        import paramiko
    except ImportError:
        print("[Error] paramiko not installed")
        return []

    from config_pass import (
        NAS_SSH_HOST, NAS_SSH_PORT, NAS_SSH_USER, 
        NAS_SSH_PASSWORD, NAS_SSH_KEYFILE, NAS_SSH_TIMEOUT
    )

    # 扫描目录
    scan_path = f"{NAS_POOL_PATH}"
    
    found_keys = []
    ssh = None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {
            "hostname": NAS_SSH_HOST,
            "port": NAS_SSH_PORT,
            "username": NAS_SSH_USER,
            "timeout": NAS_SSH_TIMEOUT
        }
        if NAS_SSH_KEYFILE:
            connect_kwargs["key_filename"] = NAS_SSH_KEYFILE
        else:
            connect_kwargs["password"] = NAS_SSH_PASSWORD
            
        ssh.connect(**connect_kwargs)

        print(f"[Server] SSH scanning NAS path: {scan_path} ...")
        cmd = f"find '{scan_path}' -type f -name '*.msh'"
        
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        
        for line in stdout:
            full_path = line.strip()
            if not full_path:
                continue

            # 将绝对路径转换为 case_key (相对于 scan_path 的路径)
            if full_path.startswith(scan_path):
                rel_path = full_path[len(scan_path):].lstrip("/")
                if rel_path:
                    found_keys.append(rel_path)
        
        err_msg = stderr.read().decode().strip()
        if err_msg:
            print(f"[Warn] SSH find command stderr: {err_msg}")

    except Exception as e:
        print(f"[Error] SSH scan failed: {e}")
    finally:
        if ssh:
            ssh.close()
            
    return found_keys

def handle(req: Dict[str, Any]) -> Dict[str, Any]:
    action = req.get("action")
    node = req.get("node_name", "Unknown")

    if action == "PING":
        return {"ok": True, "pong": True, "node": node}

    if action == "DELETE_JOBS":
        # 1. 验证密码
        pwd = req.get("password", "")
        if pwd != ADMIN_PASSWORD:
            return {"ok": False, "error": "Invalid password"}
        
        case_keys = req.get("case_keys", [])
        if not case_keys:
            return {"ok": True, "deleted_count": 0, "deleted_files": 0, "ssh_errors": []}

        # 2. 获取文件路径信息
        targets = db.get_paths_by_keys(case_keys)
        paths_to_delete = []
        for item in targets:
            nas_dir = item.get("nas_path")
            case_key = item.get("case_key")
            if nas_dir and case_key:
                paths_to_delete.append({"case_key": case_key, "nas_path": nas_dir})
        
        # 3. 删除数据库记录
        count = db.delete_jobs(case_keys)
        
        # 4. 通过SSH删除NAS文件（在服务器端执行）
        deleted_files, ssh_errors = _ssh_delete_nas_files(paths_to_delete)
        
        return {
            "ok": True, 
            "deleted_count": count, 
            "deleted_files": deleted_files,
            "ssh_errors": ssh_errors[:5]  # 最多返回5个错误
        }

    if action == "REGISTER" or action == "REGISTER_CASES":
        items = req.get("cases") or req.get("items") or []
        new_count = db.register_cases(node=node, mesh_root=req.get("mesh_root",""), cases=items)
        return {"ok": True, "new_count": new_count}
    
    if action == "GET_POOL_STATUS":
        return {"ok": True, "pool_pending": db.pool_count()}

    if action == "PUT_IN_POOL":
        keys = req.get("case_keys", [])
        pending = db.pool_count()
        can_put = max(0, int(POOL_LIMIT) - int(pending))
        put_keys = keys[:can_put]
        for k in put_keys:
            db.mark_in_pool(k, 1)
        return {"ok": True, "put": len(put_keys), "pool_pending": db.pool_count()}

    if action == "ASSIGN_FROM_POOL":
        n = int(req.get("n", 1))
        jobs = db.assign_from_pool(n)
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
        uploaded = req.get("uploaded", None)
        uploading = req.get("uploading", None)
        uploaded_at = req.get("uploaded_at", None)
        last_error = req.get("last_error", None)
        nas_path = req.get("nas_path", None)

        def to_int_or_none(x):
            if x is None:
                return None
            try:
                return int(x)
            except Exception:
                return None

        db.report_nas(
            case_key=req["case_key"],
            uploaded=to_int_or_none(uploaded),
            uploading=to_int_or_none(uploading),
            uploaded_at=to_int_or_none(uploaded_at),
            last_error=last_error,
            nas_path=nas_path,
        )
        return {"ok": True}

    if action == "GET_STATS":
        return {"ok": True, "stats": db.stats()}

    if action == "EXPORT_CSV":
        out = req.get("csv_path", "jobs_export.csv")
        db.export_csv(out)
        return {"ok": True, "csv_path": out}

    if action == "LIST_JOBS":
        limit = int(req.get("limit", 200))
        offset = int(req.get("offset", 0))
        status = req.get("status", "") or ""
        nas = req.get("nas", "") or ""
        q = req.get("q", "") or ""
        order = req.get("order", "updated") or "updated"
        jobs = db.list_jobs(limit=limit, offset=offset, status=status, nas=nas, q=q, order=order)
        return {"ok": True, "jobs": jobs}

    if action == "SCAN_AND_RECOVER":
        # 1. 远程扫描
        keys = _ssh_scan_nas_files() # <--- 改用这个函数
        
        if not keys:
            return {"ok": True, "msg": "No files found via SSH", "recovered": 0}
        
        # 2. 调用 DB 恢复 (这个你刚才在 db_manager 里加过了)
        recovered_count = db.recover_from_nas_scan(keys)
        
        # 3. 强制“激活”所有在 NAS 池中扫描到的文件
        activated_count = 0
        try:
            for k in keys:
                # 无论之前是什么状态，只要现在文件躺在 NAS 池子里，就标记为可分发
                db.mark_in_pool(k, 1)
                activated_count += 1
        except Exception as e:
            print(f"[Warn] Error activating jobs: {e}")

        print(f"[Server] SSH Scan: Found {len(keys)} files, Recovered {recovered_count} new jobs.")
        return {"ok": True, "found": len(keys), "recovered": recovered_count}

    return {"ok": False, "error": f"Unknown action: {action}"}

def serve_forever():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((SERVER_BIND_HOST, SERVER_PORT))
    s.listen(64)
    print(f"[server] listening on {SERVER_BIND_HOST}:{SERVER_PORT}")

    while True:
        conn, addr = s.accept()
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
    print("--- Server Starting... ---")
    
    # 启动时自动执行一次 SSH 扫描恢复
    # 放在这里是为了防止 DB 是空的但 NAS 是满的
    print("[Init] Attempting NAS Recovery via SSH...")
    try:
        keys = _ssh_scan_nas_files()
        if keys:
            n = db.recover_from_nas_scan(keys)
            print(f"[Init] Recovery Done: {n} jobs restored from NAS.")
        else:
            print("[Init] No files found in NAS pool.")
    except Exception as e:
        print(f"[Init] Recovery Failed: {e}")

    # 启动服务
    serve_forever()
