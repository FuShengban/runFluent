# db_manager.py
import sqlite3
import time
from typing import Dict, List, Optional, Tuple, Any

class JobDB:
    def __init__(self, db_path: str = "project.db"):
        self.db_path = db_path
        self._init_db()
        self._ensure_columns()

    def _conn(self) -> sqlite3.Connection:
        # timeout 提高一些，避免多线程/多进程短暂锁冲突
        return sqlite3.connect(self.db_path, timeout=30)

    def _init_db(self) -> None:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_key TEXT UNIQUE,           -- 用相对路径/文件名 作为唯一键
                case_name TEXT,                 -- 文件名（展示用）
                origin_node TEXT,
                origin_path TEXT,               -- 源机器上的mesh路径（记录）
                status TEXT,                    -- PENDING / ASSIGNED / COMPLETED / FAILED
                compute_node TEXT,
                compute_path TEXT,              -- 计算机器上的mesh路径（记录）
                result_path TEXT,               -- 结果目录（记录）
                in_pool INTEGER DEFAULT 0,      -- 是否在服务器池子等待分配

                nas_uploaded INTEGER DEFAULT 0, -- 是否已上传NAS(完成)
                nas_uploading INTEGER DEFAULT 0,-- 是否正在上传/已入队
                nas_uploaded_at INTEGER,        -- 上传完成时间戳
                nas_last_error TEXT,            -- 最近一次上传错误

                duration_sec REAL DEFAULT 0,
                created_at INTEGER,
                updated_at INTEGER
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_pool ON jobs(in_pool, status)")
            conn.commit()

    def _ensure_columns(self) -> None:
        """兼容旧数据库：自动补列"""
        want_cols = {
            "nas_uploading": "INTEGER DEFAULT 0",
            "nas_uploaded_at": "INTEGER",
            "nas_last_error": "TEXT",
            "nas_path": "TEXT",
        }
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("PRAGMA table_info(jobs)")
            existing = {row[1] for row in c.fetchall()}
            for col, decl in want_cols.items():
                if col not in existing:
                    c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
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
                    """, (it["case_key"], it.get("case_name", it["case_key"]), node, it.get("origin_path", ""), now, now))
                    if c.rowcount == 1:
                        new_count += 1
                except Exception:
                    continue
            conn.commit()
        return new_count

    # ---------- 池子 ----------
    def pool_count(self) -> int:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM jobs WHERE in_pool=1 AND status='PENDING'")
            return int(c.fetchone()[0])

    def mark_in_pool(self, case_key: str, in_pool: int = 1) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("UPDATE jobs SET in_pool=?, updated_at=? WHERE case_key=?", (int(in_pool), now, case_key))
            conn.commit()

    def assign_from_pool(self, n: int) -> List[str]:
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT case_key FROM jobs
                WHERE in_pool=1 AND status='PENDING'
                ORDER BY id ASC LIMIT ?
            """, (int(n),))
            keys = [r[0] for r in c.fetchall()]
            if keys:
                now = int(time.time())
                placeholders = ",".join(["?"] * len(keys))
                c.execute(f"UPDATE jobs SET in_pool=0, updated_at=? WHERE case_key IN ({placeholders})", (now, *keys))
                conn.commit()
            return keys

    # ---------- 任务状态上报 ----------
    def report_started(self, node: str, case_key: str, compute_path: str = "", result_path: str = "") -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs
                SET status='ASSIGNED',
                    compute_node=?, compute_path=?, result_path=?,
                    updated_at=?
                WHERE case_key=?
            """, (node, compute_path, result_path, now, case_key))
            conn.commit()

    def report_done(self, node: str, case_key: str, duration_sec: float) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs
                SET status='COMPLETED', compute_node=?, duration_sec=?, updated_at=?
                WHERE case_key=?
            """, (node, float(duration_sec), now, case_key))
            conn.commit()

    def report_failed(self, node: str, case_key: str) -> None:
        now = int(time.time())
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE jobs
                SET status='FAILED', compute_node=?, updated_at=?
                WHERE case_key=?
            """, (node, now, case_key))
            conn.commit()

    # ---------- NAS 上传状态（改进 3） ----------
    def report_nas(
        self,
        case_key: str,
        uploaded: Optional[int] = None,
        uploading: Optional[int] = None,
        last_error: Optional[str] = None,
        uploaded_at: Optional[int] = None,
        nas_path: Optional[str] = None,
    ) -> None:
        """向后兼容：如果只传 uploaded，也能正常工作。"""
        now = int(time.time())
        fields = []
        vals: List[Any] = []

        if uploaded is not None:
            fields.append("nas_uploaded=?")
            vals.append(int(uploaded))
        if uploading is not None:
            fields.append("nas_uploading=?")
            vals.append(int(uploading))
        if last_error is not None:
            fields.append("nas_last_error=?")
            vals.append(str(last_error))
        if uploaded_at is not None:
            fields.append("nas_uploaded_at=?")
            vals.append(int(uploaded_at))
        if nas_path is not None:
            fields.append("nas_path=?")
            vals.append(str(nas_path))


        fields.append("updated_at=?")
        vals.append(now)
        vals.append(case_key)

        with self._conn() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE case_key=?", tuple(vals))
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

            c.execute("SELECT AVG(duration_sec) FROM jobs WHERE status='COMPLETED'")
            avg = float(c.fetchone()[0] or 0.0)

            c.execute("SELECT COUNT(*) FROM jobs WHERE in_pool=1 AND status='PENDING'")
            pool_pending = int(c.fetchone()[0])

            c.execute("SELECT COUNT(*) FROM jobs WHERE nas_uploaded=1")
            nas_done = int(c.fetchone()[0])

            c.execute("SELECT COUNT(*) FROM jobs WHERE nas_uploading=1")
            nas_uploading = int(c.fetchone()[0])

            eta = 0.0
            if avg > 0:
                eta = (total - done - failed) * avg

            return {
                "total": total,
                "done": done,
                "failed": failed,
                "avg_sec": avg,
                "pool_pending": pool_pending,
                "eta_sec": eta,
                "nas_done": nas_done,
                "nas_uploading": nas_uploading,
            }

    def export_csv(self, out_path: str = "jobs_export.csv") -> None:
        import csv
        with self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM jobs ORDER BY id ASC")
            rows = c.fetchall()
            headers = [d[0] for d in c.description]

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows(rows)
    
    def list_jobs(
        self,
        limit: int = 200,
        offset: int = 0,
        status: str = "",
        nas: str = "",
        q: str = "",
        order: str = "updated"
    ) -> List[Dict[str, Any]]:
        where = []
        params: List[Any] = []

        if status:
            where.append("status=?")
            params.append(status)

        if nas == "done":
            where.append("nas_uploaded=1")
        elif nas == "uploading":
            where.append("nas_uploading=1")
        elif nas == "error":
            where.append("(nas_last_error IS NOT NULL AND nas_last_error!='')")

        if q:
            where.append("(case_key LIKE ? OR compute_node LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        if order == "id":
            order_sql = " ORDER BY id DESC"
        else:
            order_sql = " ORDER BY COALESCE(updated_at, 0) DESC, id DESC"

        sql = f"""
            SELECT
            id, case_key, case_name, status,
            compute_node, compute_path, result_path, nas_path,
            duration_sec, created_at, updated_at,
            nas_uploaded, nas_uploading, nas_uploaded_at, nas_last_error
            FROM jobs
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
        """

        params.extend([int(limit), int(offset)])

        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(sql, tuple(params))
            rows = c.fetchall()
            return [dict(r) for r in rows]
        
    # ---------- 删除相关 ----------
    def get_paths_by_keys(self, case_keys: List[str]) -> List[Dict[str, str]]:
        if not case_keys:
            return []

        placeholders = ",".join(["?"] * len(case_keys))
        sql = f"SELECT case_key, result_path, compute_path, nas_path FROM jobs WHERE case_key IN ({placeholders})"
        
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(sql, tuple(case_keys))
            rows = c.fetchall()
            return [dict(r) for r in rows]

    def delete_jobs(self, case_keys: List[str]) -> int:
        """从数据库物理删除记录"""
        if not case_keys:
            return 0
            
        placeholders = ",".join(["?"] * len(case_keys))
        sql = f"DELETE FROM jobs WHERE case_key IN ({placeholders})"
        
        with self._conn() as conn:
            c = conn.cursor()
            c.execute(sql, tuple(case_keys))
            conn.commit()
            return c.rowcount

    # ================= 灾难恢复/冷启动扫描入库 =================
    def recover_from_nas_scan(self, case_keys: List[str]) -> int:
        """
        将扫描到的 NAS 文件恢复到数据库。
        如果 case_key 已存在，忽略；
        如果不存在，插入并标记为 in_pool=1, status='PENDING'。
        """
        now = int(time.time())
        new_count = 0
        with self._conn() as conn:
            c = conn.cursor()
            for key in case_keys:
                try:
                    # 尝试插入。注意这里直接设为 in_pool=1，因为是从 NAS 池子扫出来的
                    # nas_uploaded=1 是为了标记源文件在 NAS 上是好的（虽然语义上 nas_uploaded 指结果，但这里指源）
                    # 但为了逻辑统一，我们主要关注 in_pool=1
                    c.execute("""
                    INSERT OR IGNORE INTO jobs
                    (case_key, case_name, origin_node, status, in_pool, created_at, updated_at)
                    VALUES (?, ?, 'Recovered', 'PENDING', 1, ?, ?)
                    """, (key, key, now, now))
                    
                    if c.rowcount == 1:
                        new_count += 1
                except Exception:
                    continue
            conn.commit()
        return new_count