# runFluent 重构实施快速指南

## 目标读者
本文档面向准备实施重构的开发者，提供具体的操作步骤和代码示例。

---

## 前置准备

### 1. 开发环境设置
```bash
# 1. 克隆仓库
git clone https://github.com/FuShengban/runFluent.git
cd runFluent

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装开发依赖（新增）
pip install pytest pytest-cov black flake8 mypy pydantic alembic
```

### 2. 创建 .gitignore（新增项）
```gitignore
# 环境变量文件（敏感信息）
.env
.env.local
config_pass.py

# 虚拟环境
venv/
.venv/

# IDE
.vscode/
.idea/
*.swp

# 数据库
*.db
*.db-journal

# 日志
*.log

# 测试覆盖率
.coverage
htmlcov/
.pytest_cache/

# 临时文件
__pycache__/
*.pyc
*.pyo
.DS_Store
```

---

## 阶段 1：搭建新目录结构（第1周）

### 步骤1.1：创建目录骨架
```bash
# 在项目根目录执行
mkdir -p src/domain/entities
mkdir -p src/domain/services
mkdir -p src/domain/repositories

mkdir -p src/application/use_cases
mkdir -p src/application/dto

mkdir -p src/infrastructure/database/migrations
mkdir -p src/infrastructure/network/rpc
mkdir -p src/infrastructure/network/sftp
mkdir -p src/infrastructure/compute
mkdir -p src/infrastructure/config

mkdir -p src/presentation/gui
mkdir -p src/presentation/cli

mkdir -p src/common

mkdir -p tests/unit/domain
mkdir -p tests/unit/application
mkdir -p tests/unit/infrastructure
mkdir -p tests/integration
mkdir -p tests/e2e

mkdir -p scripts
mkdir -p config
mkdir -p docs
```

### 步骤1.2：创建 __init__.py 文件
```bash
# 让Python识别为包
find src -type d -exec touch {}/__init__.py \;
find tests -type d -exec touch {}/__init__.py \;
```

### 步骤1.3：移动旧代码到 legacy 目录
```bash
# 保留旧代码作为参考
mkdir legacy
git mv *.py legacy/
git mv requirements.txt legacy/

# 创建新的依赖文件
touch requirements/base.txt
touch requirements/dev.txt
touch requirements/test.txt
```

---

## 阶段 2：实现领域层（第2-4周）

### 步骤2.1：创建 Job 实体
```python
# src/domain/entities/job.py
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

class JobStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPUTING = "computing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Job:
    """
    任务实体（聚合根）
    
    职责：
    1. 维护任务状态
    2. 执行状态转换验证
    3. 记录任务生命周期
    """
    case_key: str
    case_name: str
    status: JobStatus = JobStatus.PENDING
    
    # 节点信息
    origin_node: Optional[str] = None
    compute_node: Optional[str] = None
    
    # 计算信息
    duration_sec: float = 0.0
    compute_path: Optional[str] = None
    result_path: Optional[str] = None
    
    # NAS上传状态
    nas_uploaded: bool = False
    nas_uploading: bool = False
    nas_path: Optional[str] = None
    nas_last_error: Optional[str] = None
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def assign_to(self, node_name: str) -> None:
        """
        分配任务给节点
        
        Args:
            node_name: 节点名称
            
        Raises:
            ValueError: 如果任务不处于PENDING状态
        """
        if self.status != JobStatus.PENDING:
            raise ValueError(
                f"Cannot assign job in status {self.status}. "
                f"Job must be in PENDING status."
            )
        
        self.status = JobStatus.ASSIGNED
        self.compute_node = node_name
        self.updated_at = datetime.now()
    
    def start_computing(self) -> None:
        """开始计算"""
        if self.status != JobStatus.ASSIGNED:
            raise ValueError(
                f"Cannot start computing in status {self.status}. "
                f"Job must be in ASSIGNED status."
            )
        
        self.status = JobStatus.COMPUTING
        self.updated_at = datetime.now()
    
    def mark_completed(self, duration_sec: float) -> None:
        """
        标记任务完成
        
        Args:
            duration_sec: 计算耗时（秒）
        """
        if self.status != JobStatus.COMPUTING:
            raise ValueError(
                f"Cannot mark completed in status {self.status}. "
                f"Job must be in COMPUTING status."
            )
        
        self.status = JobStatus.COMPLETED
        self.duration_sec = duration_sec
        self.updated_at = datetime.now()
    
    def mark_failed(self, error_msg: Optional[str] = None) -> None:
        """
        标记任务失败
        
        Args:
            error_msg: 可选的错误信息
        """
        self.status = JobStatus.FAILED
        if error_msg:
            self.nas_last_error = error_msg
        self.updated_at = datetime.now()
    
    def start_nas_upload(self) -> None:
        """开始NAS上传"""
        self.nas_uploading = True
        self.nas_uploaded = False
        self.updated_at = datetime.now()
    
    def complete_nas_upload(self, nas_path: str) -> None:
        """
        完成NAS上传
        
        Args:
            nas_path: NAS存储路径
        """
        self.nas_uploading = False
        self.nas_uploaded = True
        self.nas_path = nas_path
        self.nas_last_error = None
        self.updated_at = datetime.now()
    
    def fail_nas_upload(self, error_msg: str) -> None:
        """
        NAS上传失败
        
        Args:
            error_msg: 错误信息
        """
        self.nas_uploading = False
        self.nas_uploaded = False
        self.nas_last_error = error_msg[:500]  # 限制长度
        self.updated_at = datetime.now()
```

### 步骤2.2：编写 Job 实体的单元测试
```python
# tests/unit/domain/test_job.py
import pytest
from datetime import datetime
from src.domain.entities.job import Job, JobStatus

class TestJobEntity:
    """测试Job实体"""
    
    def test_create_job(self):
        """测试创建任务"""
        job = Job(case_key="test.msh", case_name="test")
        
        assert job.case_key == "test.msh"
        assert job.case_name == "test"
        assert job.status == JobStatus.PENDING
        assert job.duration_sec == 0.0
    
    def test_assign_job(self):
        """测试分配任务"""
        job = Job(case_key="test.msh", case_name="test")
        job.assign_to("node1")
        
        assert job.status == JobStatus.ASSIGNED
        assert job.compute_node == "node1"
    
    def test_cannot_assign_twice(self):
        """测试不能重复分配"""
        job = Job(case_key="test.msh", case_name="test")
        job.assign_to("node1")
        
        with pytest.raises(ValueError, match="Cannot assign job"):
            job.assign_to("node2")
    
    def test_full_workflow(self):
        """测试完整工作流"""
        job = Job(case_key="test.msh", case_name="test")
        
        # 1. 分配
        job.assign_to("node1")
        assert job.status == JobStatus.ASSIGNED
        
        # 2. 开始计算
        job.start_computing()
        assert job.status == JobStatus.COMPUTING
        
        # 3. 完成计算
        job.mark_completed(120.5)
        assert job.status == JobStatus.COMPLETED
        assert job.duration_sec == 120.5
        
        # 4. 开始上传
        job.start_nas_upload()
        assert job.nas_uploading is True
        
        # 5. 完成上传
        job.complete_nas_upload("/nas/path")
        assert job.nas_uploaded is True
        assert job.nas_path == "/nas/path"
    
    def test_job_failure(self):
        """测试任务失败"""
        job = Job(case_key="test.msh", case_name="test")
        job.assign_to("node1")
        job.start_computing()
        
        job.mark_failed("Mesh quality check failed")
        
        assert job.status == JobStatus.FAILED
        assert "Mesh quality" in job.nas_last_error
```

### 步骤2.3：运行测试
```bash
# 运行单元测试
pytest tests/unit/domain/test_job.py -v

# 查看覆盖率
pytest tests/unit/domain/test_job.py --cov=src/domain/entities --cov-report=html

# 打开覆盖率报告
# open htmlcov/index.html  # Mac
# xdg-open htmlcov/index.html  # Linux
# start htmlcov/index.html  # Windows
```

---

## 阶段 3：实现仓储接口（第5周）

### 步骤3.1：定义仓储抽象接口
```python
# src/domain/repositories/job_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional
from ..entities.job import Job, JobStatus

class JobRepository(ABC):
    """
    任务仓储接口（抽象）
    
    职责：
    1. 定义任务数据访问的契约
    2. 解耦领域层与基础设施层
    """
    
    @abstractmethod
    def get_by_case_key(self, case_key: str) -> Optional[Job]:
        """根据case_key获取任务"""
        pass
    
    @abstractmethod
    def save(self, job: Job) -> None:
        """保存任务"""
        pass
    
    @abstractmethod
    def get_pending_jobs(self, limit: int = 100) -> List[Job]:
        """获取待分配的任务"""
        pass
    
    @abstractmethod
    def count_by_status(self, status: JobStatus) -> int:
        """统计指定状态的任务数量"""
        pass
    
    @abstractmethod
    def list_jobs(
        self, 
        limit: int = 100, 
        offset: int = 0,
        status: Optional[JobStatus] = None
    ) -> List[Job]:
        """列出任务"""
        pass
```

### 步骤3.2：实现 SQLite 仓储
```python
# src/infrastructure/database/sqlite_repository.py
import sqlite3
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from src.domain.entities.job import Job, JobStatus
from src.domain.repositories.job_repository import JobRepository


class SQLiteJobRepository(JobRepository):
    """SQLite任务仓储实现"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    case_key TEXT PRIMARY KEY,
                    case_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    origin_node TEXT,
                    compute_node TEXT,
                    duration_sec REAL DEFAULT 0.0,
                    compute_path TEXT,
                    result_path TEXT,
                    nas_uploaded INTEGER DEFAULT 0,
                    nas_uploading INTEGER DEFAULT 0,
                    nas_path TEXT,
                    nas_last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON jobs(status)"
            )
            
            conn.commit()
    
    def _conn(self):
        """创建数据库连接"""
        return sqlite3.connect(self.db_path, timeout=30)
    
    def get_by_case_key(self, case_key: str) -> Optional[Job]:
        """根据case_key获取任务"""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT * FROM jobs WHERE case_key = ?",
                (case_key,)
            )
            
            row = cursor.fetchone()
            return self._row_to_entity(row) if row else None
    
    def save(self, job: Job) -> None:
        """保存任务（插入或更新）"""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs (
                    case_key, case_name, status, origin_node, compute_node,
                    duration_sec, compute_path, result_path,
                    nas_uploaded, nas_uploading, nas_path, nas_last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.case_key,
                job.case_name,
                job.status.value,
                job.origin_node,
                job.compute_node,
                job.duration_sec,
                job.compute_path,
                job.result_path,
                int(job.nas_uploaded),
                int(job.nas_uploading),
                job.nas_path,
                job.nas_last_error,
                job.created_at.isoformat(),
                job.updated_at.isoformat()
            ))
            conn.commit()
    
    def get_pending_jobs(self, limit: int = 100) -> List[Job]:
        """获取待分配的任务"""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
            """, (JobStatus.PENDING.value, limit))
            
            return [self._row_to_entity(row) for row in cursor.fetchall()]
    
    def count_by_status(self, status: JobStatus) -> int:
        """统计指定状态的任务数量"""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?",
                (status.value,)
            )
            return cursor.fetchone()[0]
    
    def list_jobs(
        self,
        limit: int = 100,
        offset: int = 0,
        status: Optional[JobStatus] = None
    ) -> List[Job]:
        """列出任务"""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if status:
                cursor.execute("""
                    SELECT * FROM jobs 
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """, (status.value, limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM jobs 
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
            return [self._row_to_entity(row) for row in cursor.fetchall()]
    
    def _row_to_entity(self, row: sqlite3.Row) -> Job:
        """将数据库行转换为实体"""
        return Job(
            case_key=row["case_key"],
            case_name=row["case_name"],
            status=JobStatus(row["status"]),
            origin_node=row["origin_node"],
            compute_node=row["compute_node"],
            duration_sec=row["duration_sec"],
            compute_path=row["compute_path"],
            result_path=row["result_path"],
            nas_uploaded=bool(row["nas_uploaded"]),
            nas_uploading=bool(row["nas_uploading"]),
            nas_path=row["nas_path"],
            nas_last_error=row["nas_last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
```

---

## 阶段 4：实现应用层用例（第6周）

### 步骤4.1：计算任务用例
```python
# src/application/use_cases/compute_job.py
from pathlib import Path
from typing import Optional

from src.domain.entities.job import Job
from src.domain.repositories.job_repository import JobRepository


class ComputeJobUseCase:
    """
    计算任务用例
    
    职责：
    1. 协调计算任务的完整流程
    2. 调用领域服务和基础设施服务
    """
    
    def __init__(
        self, 
        job_repo: JobRepository,
        fluent_executor  # 暂时用Any，后续定义接口
    ):
        self.job_repo = job_repo
        self.executor = fluent_executor
    
    def execute(self, case_key: str, mesh_path: Path) -> Job:
        """
        执行计算任务
        
        Args:
            case_key: 任务标识
            mesh_path: 网格文件路径
            
        Returns:
            完成后的Job实体
            
        Raises:
            ValueError: 任务不存在或状态不正确
            RuntimeError: 计算执行失败
        """
        # 1. 获取任务
        job = self.job_repo.get_by_case_key(case_key)
        if not job:
            raise ValueError(f"Job not found: {case_key}")
        
        # 2. 开始计算
        job.start_computing()
        self.job_repo.save(job)
        
        # 3. 执行Fluent仿真
        try:
            duration = self.executor.run(mesh_path)
            job.mark_completed(duration)
        except Exception as e:
            job.mark_failed(str(e))
            self.job_repo.save(job)
            raise RuntimeError(f"Computation failed: {e}") from e
        
        # 4. 保存结果
        self.job_repo.save(job)
        
        return job
```

---

## 阶段 5：集成测试（第7周）

### 步骤5.1：编写集成测试
```python
# tests/integration/test_compute_workflow.py
import pytest
from pathlib import Path
from unittest.mock import Mock

from src.domain.entities.job import Job, JobStatus
from src.infrastructure.database.sqlite_repository import SQLiteJobRepository
from src.application.use_cases.compute_job import ComputeJobUseCase


@pytest.fixture
def test_db():
    """测试数据库fixture"""
    db_path = ":memory:"  # 使用内存数据库
    return SQLiteJobRepository(db_path)


@pytest.fixture
def mock_executor():
    """Mock Fluent执行器"""
    executor = Mock()
    executor.run.return_value = 120.5  # 模拟耗时120.5秒
    return executor


def test_compute_workflow(test_db, mock_executor):
    """测试完整的计算工作流"""
    # 1. 准备：创建并保存任务
    job = Job(case_key="test.msh", case_name="test")
    job.assign_to("node1")
    test_db.save(job)
    
    # 2. 执行：运行用例
    use_case = ComputeJobUseCase(test_db, mock_executor)
    result_job = use_case.execute("test.msh", Path("/tmp/test.msh"))
    
    # 3. 断言：验证结果
    assert result_job.status == JobStatus.COMPLETED
    assert result_job.duration_sec == 120.5
    
    # 4. 验证：从数据库读取
    saved_job = test_db.get_by_case_key("test.msh")
    assert saved_job.status == JobStatus.COMPLETED
    assert saved_job.duration_sec == 120.5
    
    # 5. 验证：执行器被正确调用
    mock_executor.run.assert_called_once_with(Path("/tmp/test.msh"))
```

---

## 关键实施原则

### 1. 测试驱动开发（TDD）
```
写测试 → 运行失败 → 写代码 → 运行通过 → 重构
```

### 2. 小步快跑
- 每次只重构一个小模块
- 每次提交后确保测试通过
- 频繁集成到主分支

### 3. 保持向后兼容
```python
# 在迁移期间，保留旧接口的包装器
def legacy_compute_one_local(msh_path: str):
    """旧接口（兼容层）"""
    # 调用新的用例
    use_case = ComputeJobUseCase(repo, executor)
    return use_case.execute(case_key, Path(msh_path))
```

### 4. 持续集成
```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements/base.txt
          pip install -r requirements/test.txt
      - name: Run tests
        run: pytest tests/ --cov=src --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

## 常见问题（FAQ）

### Q1: 重构期间如何保证系统可用？
**A**: 采用渐进式重构：
1. 新代码放在 `src/` 目录
2. 旧代码保留在 `legacy/` 目录
3. 在入口处切换新旧实现（Feature Flag）
4. 逐步下线旧代码

### Q2: 如何处理数据库迁移？
**A**: 使用Alembic：
```bash
# 初始化迁移
alembic init src/infrastructure/database/migrations

# 创建迁移脚本
alembic revision --autogenerate -m "Initial schema"

# 执行迁移
alembic upgrade head
```

### Q3: 测试覆盖率目标是多少？
**A**: 
- 领域层：>90%
- 应用层：>80%
- 基础设施层：>70%
- 总体：>80%

### Q4: 重构期间发现Bug怎么办？
**A**: 
1. 先修Bug（紧急修复）
2. 在旧代码修复
3. 在新代码同步修复
4. 写测试防止回归

---

## 参考资料

- [Clean Architecture (Robert C. Martin)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Domain-Driven Design Quickly](https://www.infoq.com/minibooks/domain-driven-design-quickly/)
- [Python Testing with pytest](https://pragprog.com/titles/bopytest/python-testing-with-pytest/)
- [Refactoring: Improving the Design of Existing Code](https://martinfowler.com/books/refactoring.html)

---

**祝重构顺利！有任何问题随时沟通。**
