# client_core.py
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from config import SERVER_HOST, SERVER_PORT, DEFAULT_NODE_NAME
from protocol import request

def default_node_name() -> str:
    if DEFAULT_NODE_NAME:
        return DEFAULT_NODE_NAME
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "Node"

def list_msh(mesh_root: str, recursive: bool = True) -> List[str]:
    msh_files = []
    if recursive:
        for root, _, files in os.walk(mesh_root):
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
    return rel  # 用“相对路径”作唯一键：更稳（避免同名冲突）

@dataclass
class ClientState:
    node_name: str
    mesh_root: str = ""
    result_root: str = ""
    # 你可以自己扩展：NAS路径等

class ClientCore:
    def __init__(self, state: ClientState):
        self.state = state

    # ---- 服务端通信 ----
    def ping(self) -> Dict:
        return request(SERVER_HOST, SERVER_PORT, {"action": "PING", "node_name": self.state.node_name})

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
        return request(SERVER_HOST, SERVER_PORT, payload)

    def get_pool_status(self) -> Dict:
        return request(SERVER_HOST, SERVER_PORT, {"action": "GET_POOL_STATUS", "node_name": self.state.node_name})

    def put_selected_in_pool(self, case_keys: List[str]) -> Dict:
        payload = {
            "action": "PUT_IN_POOL",
            "node_name": self.state.node_name,
            "case_keys": case_keys
        }
        return request(SERVER_HOST, SERVER_PORT, payload)

    def assign_from_pool(self, n: int) -> List[Dict]:
        payload = {"action": "ASSIGN_FROM_POOL", "node_name": self.state.node_name, "n": int(n)}
        resp = request(SERVER_HOST, SERVER_PORT, payload)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "assign failed"))
        return resp.get("jobs", [])

    def report_started(self, case_key: str, compute_path: str, result_path: str) -> None:
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_STARTED",
            "node_name": self.state.node_name,
            "case_key": case_key,
            "compute_path": compute_path,
            "result_path": result_path
        })

    def report_done(self, case_key: str, duration_sec: float) -> None:
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_DONE",
            "node_name": self.state.node_name,
            "case_key": case_key,
            "duration_sec": float(duration_sec)
        })

    def report_failed(self, case_key: str) -> None:
        request(SERVER_HOST, SERVER_PORT, {
            "action": "REPORT_FAILED",
            "node_name": self.state.node_name,
            "case_key": case_key
        })

    def get_stats(self) -> Dict:
        resp = request(SERVER_HOST, SERVER_PORT, {"action": "GET_STATS", "node_name": self.state.node_name})
        return resp.get("stats", {}) if resp.get("ok") else {}

    # ---- 计算动作（你把 fluent_worker 接进来即可） ----
    def compute_one_local(self, msh_path: str, fluent_worker=None) -> Dict:
        """
        fluent_worker 需要提供：process_case(msh_path)->bool
        """
        if not self.state.mesh_root:
            raise ValueError("mesh_root not set")

        case_key = make_case_key(self.state.mesh_root, msh_path)
        compute_path = msh_path
        result_path = self.state.result_root or ""

        self.report_started(case_key, compute_path=compute_path, result_path=result_path)

        t0 = time.time()
        ok = False
        try:
            if fluent_worker is None:
                # 没接Fluent时，先做“空跑”测试
                time.sleep(0.2)
                ok = True
            else:
                ok = bool(fluent_worker.process_case(msh_path))
        except Exception:
            ok = False

        dt = time.time() - t0
        if ok:
            self.report_done(case_key, dt)
            return {"ok": True, "case_key": case_key, "duration_sec": dt}
        else:
            self.report_failed(case_key)
            return {"ok": False, "case_key": case_key, "duration_sec": dt}
