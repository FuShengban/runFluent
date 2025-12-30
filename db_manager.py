# db_manager.py
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

class JobDB:
    def __init__(self, db_path: str = "project.db"):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_key TEXT UNIQUE,           -- 建议用 相对路径/文件名 作为唯一键
                case_name TEXT,                 -- 文件名（展示用）
                origin_node TEXT,
                origin_path TEXT,               -- origin机器上的mesh路径（仅记录）
                status TEXT,                    -- PENDING / ASSIGNED / COMPLETED / FAILED
                compute_node TEXT,
                compute_path TEXT,              -- compute机器上的mesh路径（仅记录）
                result_path TEXT,               -- 结果目录（仅记录）
                in_pool INTEGER DEFAULT 0,      -- 是否“在服务器池子里”等待被领取（逻辑概念）
                nas_uploaded INTEGER DEFAULT 0,
                duration_sec REAL DEFAULT 0,
                created_at INTEGER,
                updated_at INTEGER
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_pool ON jobs(in_pool, status)")
            conn.commit()

    # ---------- 注册 ----------
    def register_cases(self, node: str, mesh_root: str, cases: List[Dict]) -> int:
        """
        cases: [{"case_key": "...", "case_name": "...", "origin_path": "..."}]
        """
        now = int(time.time())
        new_count = 0
        with self._conn() as conn:
            c = conn.cursor()
            for it in cases:
                try:
                    c.execute("""
                    INSERT OR IGNORE INTO jobs
                    (case_key, case_name, origin_node, origin_path, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'PENDING', ?, ?)
                    """, (it["case_key"], it["case_name"], node, it.get("origin_path", ""), now, now))
                    if c.rowcount > 0:
                        new_count += 1
                except Exception:
                    pass
            conn.commit()
        return new_count

    # ---------- 池子 ----------
    def pool_count(self) -> int:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM jobs WHERE in_pool=1 AND status='PENDING'")
            return int(c.fetchone()[0])

    def mark_in_pool(self, case_keys: List[str], in_pool: int) -> int:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.executemany("""
                UPDATE jobs SET in_pool=?, updated_at=? 
                WHERE case_key=? AND status='PENDING'
            """, [(in_pool, now, k) for k in case_keys])
            conn.commit()
            return c.rowcount

    # ---------- 分配 ----------
    def assign_from_pool(self, node: str, n: int) -> List[Dict]:
        """
        从 pool 里挑 PENDING 的分配给 node，并标记 ASSIGNED + in_pool=0
        """
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT case_key, case_name FROM jobs
                WHERE in_pool=1 AND status='PENDING'
                LIMIT ?
            """, (n,))
            rows = c.fetchall()

            case_keys = [r[0] for r in rows]
            if case_keys:
                c.executemany("""
                    UPDATE jobs 
                    SET status='ASSIGNED', compute_node=?, in_pool=0, updated_at=?
                    WHERE case_key=?
                """, [(node, now, k) for k in case_keys])
                conn.commit()

            return [{"case_key": r[0], "case_name": r[1]} for r in rows]

    # ---------- 状态汇报 ----------
    def report_started(self, node: str, case_key: str, compute_path: str, result_path: str) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs SET status='ASSIGNED', compute_node=?, compute_path=?, result_path=?, updated_at=?
                WHERE case_key=?
            """, (node, compute_path, result_path, now, case_key))
            conn.commit()

    def report_done(self, node: str, case_key: str, duration_sec: float) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs SET status='COMPLETED', compute_node=?, duration_sec=?, updated_at=?
                WHERE case_key=?
            """, (node, duration_sec, now, case_key))
            conn.commit()

    def report_failed(self, node: str, case_key: str) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs SET status='FAILED', compute_node=?, updated_at=?
                WHERE case_key=?
            """, (node, now, case_key))
            conn.commit()

    def report_nas(self, case_key: str, uploaded: int = 1) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs SET nas_uploaded=?, updated_at=? WHERE case_key=?
            """, (uploaded, now, case_key))
            conn.commit()

    # ---------- 统计 ----------
    def stats(self) -> Dict:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM jobs")
            total = int(c.fetchone()[0])

            c.execute("SELECT COUNT(*) FROM jobs WHERE status='COMPLETED'")
            done = int(c.fetchone()[0])

            c.execute("SELECT COUNT(*) FROM jobs WHERE status='FAILED'")
            failed = int(c.fetchone()[0])

            c.execute("SELECT AVG(duration_sec) FROM jobs WHERE status='COMPLETED' AND duration_sec>0")
            avg_sec = c.fetchone()[0] or 0.0

            c.execute("SELECT COUNT(*) FROM jobs WHERE nas_uploaded=1 AND status='COMPLETED'")
            nas_done = int(c.fetchone()[0])

            c.execute("""
                SELECT compute_node, COUNT(*) 
                FROM jobs 
                WHERE status='COMPLETED' AND compute_node IS NOT NULL
                GROUP BY compute_node
                ORDER BY COUNT(*) DESC
            """)
            by_node = [{"node": r[0], "completed": int(r[1])} for r in c.fetchall()]

            pool_pending = self.pool_count()

        remaining = max(total - done - failed, 0)
        # 简单 ETA：remaining * avg / active_nodes
        active_nodes = max(len(by_node), 1)
        eta_sec = (remaining * avg_sec / active_nodes) if avg_sec > 0 else 0.0

        return {
            "total": total,
            "done": done,
            "failed": failed,
            "avg_sec": float(avg_sec),
            "nas_done": nas_done,
            "pool_pending": pool_pending,
            "active_nodes": active_nodes,
            "eta_sec": float(eta_sec),
            "by_node": by_node,
        }

    def export_csv(self, csv_path: str) -> None:
        import csv
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM jobs ORDER BY id ASC")
            rows = c.fetchall()
            headers = [d[0] for d in c.description]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows(rows)
