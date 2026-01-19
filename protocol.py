# protocol.py
import json
import socket
from typing import Any, Dict

ENCODING = "utf-8"

def send_json(sock: socket.socket, obj: Dict[str, Any]) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode(ENCODING)
    sock.sendall(data)

def recv_json(sock: socket.socket, max_bytes: int = 10_000_000) -> Dict[str, Any]:
    """
    一次读取一条JSON（以换行符分隔）。
    """
    buf = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf.extend(chunk)
        if b"\n" in chunk:
            break
        if len(buf) > max_bytes:
            raise ValueError("Incoming message too large.")
    line = buf.split(b"\n", 1)[0].decode(ENCODING).strip()
    if not line:
        return {}
    return json.loads(line)

def request(host: str, port: int, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect((host, port))
        send_json(s, payload)
        return recv_json(s)
