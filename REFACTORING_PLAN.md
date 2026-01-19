# runFluent 项目重构架构规划方案

## 一、现状分析

### 1.1 当前项目结构
```
runFluent/
├── server_service.py      # 服务端：任务调度、客户端协调
├── client_app.py          # 客户端GUI：任务接收、执行管理
├── client_core.py         # 客户端核心逻辑
├── fluent_worker.py       # Fluent仿真执行器
├── db_manager.py          # SQLite数据库管理
├── sftp_utils.py          # SFTP文件传输
├── protocol.py            # 自定义JSON-over-TCP协议
├── config.py              # 配置文件
├── config_pass.py         # 敏感配置（密码等）
├── monitor_app.py         # 监控看板GUI
├── launcher.py            # 启动器
└── requirements.txt       # 依赖清单
```

### 1.2 当前架构优点
✅ **功能完整**：覆盖分布式CFD计算的核心需求  
✅ **实用性强**：针对实际场景优化（离线模式、断线恢复）  
✅ **错误处理完善**：有隔离目录、重试机制、恢复逻辑  
✅ **自定义收敛检测**：通过监控文件实现智能判定  

### 1.3 存在的问题
❌ **缺乏分层设计**：业务逻辑、UI、数据访问混杂  
❌ **模块职责不清**：单个文件承担过多责任  
❌ **配置管理混乱**：硬编码、敏感信息未加密  
❌ **缺乏测试**：无单元测试、集成测试  
❌ **代码复用性差**：重复逻辑多（如路径处理）  
❌ **难以扩展**：添加新功能需修改多处代码  
❌ **协议耦合**：JSON-over-TCP协议与业务逻辑耦合  

---

## 二、重构架构设计

### 2.1 分层架构（Clean Architecture）

```
┌─────────────────────────────────────────────────────────┐
│                   Presentation Layer                     │
│   (GUI: client_app, monitor_app, launcher)              │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                  Application Layer                       │
│  (Use Cases: ComputeJobUseCase, UploadResultUseCase)   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    Domain Layer                          │
│  (Entities: Job, Client, Result; Services: Scheduler)   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                Infrastructure Layer                      │
│  (DB: JobRepository; Network: RPCClient; File: SFTP)    │
└─────────────────────────────────────────────────────────┘
```

### 2.2 推荐的目录结构

```
runFluent/
├── src/
│   ├── domain/                    # 领域层（核心业务逻辑）
│   │   ├── entities/
│   │   │   ├── job.py            # Job实体（状态机）
│   │   │   ├── client.py         # Client实体
│   │   │   └── result.py         # Result实体
│   │   ├── services/
│   │   │   ├── scheduler.py      # 任务调度服务
│   │   │   └── convergence.py    # 收敛检测服务
│   │   └── repositories/         # 数据访问接口（抽象）
│   │       └── job_repository.py
│   │
│   ├── application/               # 应用层（用例/业务流程）
│   │   ├── use_cases/
│   │   │   ├── compute_job.py    # 计算任务用例
│   │   │   ├── upload_result.py  # 上传结果用例
│   │   │   ├── assign_job.py     # 分配任务用例
│   │   │   └── monitor_jobs.py   # 监控任务用例
│   │   └── dto/                  # 数据传输对象
│   │       └── job_dto.py
│   │
│   ├── infrastructure/            # 基础设施层（技术实现）
│   │   ├── database/
│   │   │   ├── sqlite_repository.py  # SQLite实现
│   │   │   └── migrations/          # 数据库迁移脚本
│   │   ├── network/
│   │   │   ├── rpc/
│   │   │   │   ├── server.py        # RPC服务端
│   │   │   │   ├── client.py        # RPC客户端
│   │   │   │   └── protocol.py      # 协议定义
│   │   │   └── sftp/
│   │   │       └── sftp_client.py   # SFTP客户端
│   │   ├── compute/
│   │   │   └── fluent_executor.py   # Fluent执行器
│   │   └── config/
│   │       ├── settings.py          # 配置管理（环境变量）
│   │       └── secrets.py           # 密钥管理（加密）
│   │
│   ├── presentation/              # 表示层（UI）
│   │   ├── gui/
│   │   │   ├── client_window.py     # 客户端窗口
│   │   │   ├── monitor_window.py    # 监控窗口
│   │   │   └── launcher_window.py   # 启动器
│   │   └── cli/                    # 命令行接口（可选）
│   │       └── commands.py
│   │
│   └── common/                    # 公共工具
│       ├── logging.py             # 日志配置
│       ├── exceptions.py          # 自定义异常
│       └── utils.py               # 通用工具函数
│
├── tests/                         # 测试目录
│   ├── unit/                      # 单元测试
│   │   ├── domain/
│   │   ├── application/
│   │   └── infrastructure/
│   ├── integration/               # 集成测试
│   └── e2e/                       # 端到端测试
│
├── scripts/                       # 运维脚本
│   ├── start_server.py
│   ├── start_client.py
│   └── migrate_db.py
│
├── config/                        # 配置文件目录
│   ├── server.yaml
│   ├── client.yaml
│   └── .env.example
│
├── docs/                          # 文档
│   ├── architecture.md
│   ├── api.md
│   └── deployment.md
│
├── requirements/
│   ├── base.txt                   # 基础依赖
│   ├── dev.txt                    # 开发依赖
│   └── test.txt                   # 测试依赖
│
├── README.md
├── setup.py                       # 安装脚本
├── pyproject.toml                 # 项目元数据
└── .gitignore
```

---

## 三、核心模块重构设计

### 3.1 领域层（Domain Layer）

#### 3.1.1 Job实体（状态机设计）
```python
# src/domain/entities/job.py
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

class JobStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPUTING = "computing"
    COMPLETED = "completed"
    FAILED = "failed"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"

@dataclass
class Job:
    """任务实体（聚合根）"""
    case_key: str
    case_name: str
    status: JobStatus
    origin_node: Optional[str] = None
    compute_node: Optional[str] = None
    duration_sec: float = 0.0
    created_at: datetime = None
    updated_at: datetime = None
    
    # NAS上传状态
    nas_uploaded: bool = False
    nas_uploading: bool = False
    nas_path: Optional[str] = None
    
    def assign_to(self, node_name: str):
        """分配任务给节点"""
        if self.status != JobStatus.PENDING:
            raise ValueError(f"Cannot assign job in status {self.status}")
        self.status = JobStatus.ASSIGNED
        self.compute_node = node_name
        self.updated_at = datetime.now()
    
    def start_computing(self):
        """开始计算"""
        if self.status != JobStatus.ASSIGNED:
            raise ValueError(f"Cannot start computing in status {self.status}")
        self.status = JobStatus.COMPUTING
        self.updated_at = datetime.now()
    
    def mark_completed(self, duration_sec: float):
        """标记完成"""
        self.status = JobStatus.COMPLETED
        self.duration_sec = duration_sec
        self.updated_at = datetime.now()
    
    def mark_failed(self):
        """标记失败"""
        self.status = JobStatus.FAILED
        self.updated_at = datetime.now()
```

#### 3.1.2 任务调度服务
```python
# src/domain/services/scheduler.py
from typing import List
from ..entities.job import Job, JobStatus
from ..repositories.job_repository import JobRepository

class JobScheduler:
    """任务调度服务（领域服务）"""
    
    def __init__(self, job_repo: JobRepository, pool_limit: int = 100):
        self.job_repo = job_repo
        self.pool_limit = pool_limit
    
    def assign_jobs(self, node_name: str, count: int) -> List[Job]:
        """为节点分配任务"""
        # 1. 从池中获取待分配任务
        pending_jobs = self.job_repo.get_pending_jobs(limit=count)
        
        # 2. 分配任务
        assigned = []
        for job in pending_jobs:
            job.assign_to(node_name)
            self.job_repo.save(job)
            assigned.append(job)
        
        return assigned
    
    def can_add_to_pool(self) -> bool:
        """检查是否可以添加任务到池"""
        current_count = self.job_repo.count_pooled_jobs()
        return current_count < self.pool_limit
```

#### 3.1.3 收敛检测服务
```python
# src/domain/services/convergence.py
from pathlib import Path
from typing import List, Tuple

class ConvergenceDetector:
    """收敛检测服务（领域服务）"""
    
    def __init__(self, skip_steps: int = 200, tail_length: int = 150, 
                 threshold: float = 0.02):
        self.skip_steps = skip_steps
        self.tail_length = tail_length
        self.threshold = threshold
    
    def is_converged(self, cd_file: Path, cl_file: Path) -> bool:
        """判断是否收敛"""
        cd_series = self._read_series(cd_file)
        cl_series = self._read_series(cl_file)
        
        cd_mean = self._cumulative_mean(cd_series, self.skip_steps)
        cl_mean = self._cumulative_mean(cl_series, self.skip_steps)
        
        cd_stable = self._is_stable(cd_mean[-self.tail_length:], self.threshold)
        cl_stable = self._is_stable(cl_mean[-self.tail_length:], self.threshold)
        
        return cd_stable and cl_stable
    
    def _read_series(self, file: Path) -> List[float]:
        """从输出文件读取数值序列"""
        # ... 实现细节
        pass
    
    def _cumulative_mean(self, series: List[float], skip: int) -> List[float]:
        """计算累积均值"""
        # ... 实现细节
        pass
    
    def _is_stable(self, series: List[float], threshold: float) -> bool:
        """判断序列是否稳定"""
        if not series:
            return False
        return (max(series) - min(series)) < threshold
```

### 3.2 应用层（Application Layer）

#### 3.2.1 计算任务用例
```python
# src/application/use_cases/compute_job.py
from pathlib import Path
from ...domain.entities.job import Job
from ...domain.repositories.job_repository import JobRepository
from ...infrastructure.compute.fluent_executor import FluentExecutor

class ComputeJobUseCase:
    """计算任务用例"""
    
    def __init__(self, job_repo: JobRepository, executor: FluentExecutor):
        self.job_repo = job_repo
        self.executor = executor
    
    def execute(self, case_key: str, mesh_path: Path) -> Job:
        """执行计算任务"""
        # 1. 获取任务
        job = self.job_repo.get_by_case_key(case_key)
        
        # 2. 开始计算
        job.start_computing()
        self.job_repo.save(job)
        
        # 3. 执行Fluent仿真
        try:
            duration = self.executor.run(mesh_path)
            job.mark_completed(duration)
        except Exception as e:
            job.mark_failed()
            raise
        finally:
            self.job_repo.save(job)
        
        return job
```

#### 3.2.2 上传结果用例
```python
# src/application/use_cases/upload_result.py
from pathlib import Path
from typing import List
from ...domain.entities.job import Job
from ...domain.repositories.job_repository import JobRepository
from ...infrastructure.network.sftp.sftp_client import SFTPClient

class UploadResultUseCase:
    """上传结果用例"""
    
    def __init__(self, job_repo: JobRepository, sftp_client: SFTPClient):
        self.job_repo = job_repo
        self.sftp_client = sftp_client
    
    def execute(self, case_key: str, local_files: List[Path], 
                remote_dir: str) -> Job:
        """上传计算结果到NAS"""
        # 1. 获取任务
        job = self.job_repo.get_by_case_key(case_key)
        
        # 2. 标记上传中
        job.nas_uploading = True
        self.job_repo.save(job)
        
        # 3. 上传文件
        try:
            for file in local_files:
                remote_path = f"{remote_dir}/{file.name}"
                self.sftp_client.upload(file, remote_path)
            
            job.nas_uploaded = True
            job.nas_uploading = False
            job.nas_path = remote_dir
        except Exception as e:
            job.nas_uploading = False
            raise
        finally:
            self.job_repo.save(job)
        
        return job
```

### 3.3 基础设施层（Infrastructure Layer）

#### 3.3.1 仓储实现
```python
# src/infrastructure/database/sqlite_repository.py
import sqlite3
from typing import List, Optional
from ...domain.entities.job import Job, JobStatus
from ...domain.repositories.job_repository import JobRepository

class SQLiteJobRepository(JobRepository):
    """SQLite仓储实现"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def get_by_case_key(self, case_key: str) -> Optional[Job]:
        """根据case_key获取任务"""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM jobs WHERE case_key = ?",
                (case_key,)
            )
            row = cursor.fetchone()
            return self._map_to_entity(row) if row else None
    
    def save(self, job: Job) -> None:
        """保存任务"""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO jobs 
                (case_key, case_name, status, compute_node, duration_sec, 
                 nas_uploaded, nas_uploading, nas_path, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.case_key, job.case_name, job.status.value,
                job.compute_node, job.duration_sec,
                job.nas_uploaded, job.nas_uploading, job.nas_path,
                job.updated_at
            ))
            conn.commit()
    
    def get_pending_jobs(self, limit: int) -> List[Job]:
        """获取待分配任务"""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE status = ? AND in_pool = 1
                ORDER BY created_at ASC
                LIMIT ?
            """, (JobStatus.PENDING.value, limit))
            rows = cursor.fetchall()
            return [self._map_to_entity(row) for row in rows]
    
    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=30)
    
    def _map_to_entity(self, row) -> Job:
        """将数据库行映射为实体"""
        # ... 映射逻辑
        pass
```

#### 3.3.2 RPC通信（替代原有JSON-over-TCP）
```python
# src/infrastructure/network/rpc/server.py
from typing import Any, Callable, Dict
import socket
import json
import threading

class RPCServer:
    """RPC服务端（支持多种协议）"""
    
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.handlers: Dict[str, Callable] = {}
    
    def register_handler(self, action: str, handler: Callable):
        """注册处理器"""
        self.handlers[action] = handler
    
    def start(self):
        """启动服务"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(64)
        
        print(f"[RPC Server] Listening on {self.host}:{self.port}")
        
        while True:
            conn, addr = sock.accept()
            thread = threading.Thread(
                target=self._handle_client,
                args=(conn, addr),
                daemon=True
            )
            thread.start()
    
    def _handle_client(self, conn: socket.socket, addr):
        """处理客户端请求"""
        try:
            # 接收请求
            request = self._recv_json(conn)
            action = request.get("action")
            
            # 查找处理器
            handler = self.handlers.get(action)
            if not handler:
                response = {"ok": False, "error": f"Unknown action: {action}"}
            else:
                response = handler(request)
            
            # 发送响应
            self._send_json(conn, response)
        except Exception as e:
            response = {"ok": False, "error": str(e)}
            self._send_json(conn, response)
        finally:
            conn.close()
    
    def _send_json(self, sock, obj):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        sock.sendall(data)
    
    def _recv_json(self, sock):
        buf = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\n" in chunk:
                break
        line = buf.split(b"\n", 1)[0].decode("utf-8").strip()
        return json.loads(line) if line else {}
```

#### 3.3.3 配置管理（环境变量 + YAML）
```python
# src/infrastructure/config/settings.py
from pydantic import BaseSettings, Field
from typing import Optional

class ServerConfig(BaseSettings):
    """服务端配置（从环境变量读取）"""
    host: str = Field("0.0.0.0", env="SERVER_HOST")
    port: int = Field(8000, env="SERVER_PORT")
    db_path: str = Field("project.db", env="DB_PATH")
    pool_limit: int = Field(100, env="POOL_LIMIT")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

class ClientConfig(BaseSettings):
    """客户端配置"""
    server_host: str = Field("127.0.0.1", env="SERVER_HOST")
    server_port: int = Field(8000, env="SERVER_PORT")
    node_name: Optional[str] = Field(None, env="NODE_NAME")
    mesh_root: str = Field("", env="MESH_ROOT")
    result_root: str = Field("", env="RESULT_ROOT")
    
    class Config:
        env_file = ".env"

class FluentConfig(BaseSettings):
    """Fluent配置"""
    dimension: int = Field(2, env="FLUENT_DIMENSION")
    processors: int = Field(0, env="FLUENT_PROCESSORS")
    time_step_size: float = Field(0.005, env="TIME_STEP_SIZE")
    warm_steps: int = Field(200, env="WARM_STEPS")
    gui_mode: bool = Field(False, env="FLUENT_GUI")
    
    class Config:
        env_file = ".env"

class NASConfig(BaseSettings):
    """NAS配置"""
    sftp_host: str = Field(..., env="NAS_SFTP_HOST")
    sftp_port: int = Field(22, env="NAS_SFTP_PORT")
    sftp_user: str = Field(..., env="NAS_SFTP_USER")
    sftp_key_path: str = Field(..., env="NAS_SFTP_KEY_PATH")
    pool_path: str = Field(..., env="NAS_POOL_PATH")
    results_path: str = Field(..., env="NAS_RESULTS_PATH")
    
    class Config:
        env_file = ".env"
```

---

## 四、数据库迁移策略

### 4.1 使用Alembic进行版本化管理
```python
# src/infrastructure/database/migrations/versions/001_initial.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('case_key', sa.String(500), unique=True, nullable=False),
        sa.Column('case_name', sa.String(255)),
        sa.Column('status', sa.String(50)),
        sa.Column('origin_node', sa.String(100)),
        sa.Column('compute_node', sa.String(100)),
        sa.Column('duration_sec', sa.Float, default=0.0),
        sa.Column('nas_uploaded', sa.Boolean, default=False),
        sa.Column('nas_uploading', sa.Boolean, default=False),
        sa.Column('nas_path', sa.String(1000)),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
    )
    op.create_index('idx_jobs_status', 'jobs', ['status'])
    op.create_index('idx_jobs_pool', 'jobs', ['status', 'in_pool'])

def downgrade():
    op.drop_table('jobs')
```

---

## 五、测试策略

### 5.1 单元测试
```python
# tests/unit/domain/test_job.py
import pytest
from src.domain.entities.job import Job, JobStatus

def test_job_assign():
    """测试任务分配"""
    job = Job(case_key="test.msh", case_name="test", status=JobStatus.PENDING)
    job.assign_to("node1")
    assert job.status == JobStatus.ASSIGNED
    assert job.compute_node == "node1"

def test_job_cannot_assign_twice():
    """测试任务不能重复分配"""
    job = Job(case_key="test.msh", case_name="test", status=JobStatus.ASSIGNED)
    with pytest.raises(ValueError):
        job.assign_to("node2")
```

### 5.2 集成测试
```python
# tests/integration/test_compute_workflow.py
import pytest
from src.application.use_cases.compute_job import ComputeJobUseCase
from src.infrastructure.database.sqlite_repository import SQLiteJobRepository

def test_compute_workflow():
    """测试完整的计算工作流"""
    # Setup
    repo = SQLiteJobRepository(":memory:")
    use_case = ComputeJobUseCase(repo, mock_executor)
    
    # Execute
    job = use_case.execute("test.msh", Path("/tmp/test.msh"))
    
    # Assert
    assert job.status == JobStatus.COMPLETED
    assert job.duration_sec > 0
```

---

## 六、部署和运维改进

### 6.1 Docker化部署
```dockerfile
# Dockerfile.server
FROM python:3.11-slim

WORKDIR /app
COPY requirements/base.txt .
RUN pip install -r base.txt

COPY src/ ./src/
COPY scripts/ ./scripts/

ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000

CMD ["python", "scripts/start_server.py"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  server:
    build:
      context: .
      dockerfile: Dockerfile.server
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - DB_PATH=/app/data/project.db
      - POOL_LIMIT=100
```

### 6.2 日志管理（结构化日志）
```python
# src/common/logging.py
import logging
import structlog

def configure_logging():
    """配置结构化日志"""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

---

## 七、分阶段实施计划

### 阶段1：准备工作（1-2周）
- [ ] 搭建新的目录结构
- [ ] 配置依赖管理（Poetry或pip-tools）
- [ ] 设置CI/CD（GitHub Actions）
- [ ] 编写测试框架脚手架

### 阶段2：领域层重构（2-3周）
- [ ] 提取Job实体及状态机
- [ ] 实现领域服务（Scheduler、ConvergenceDetector）
- [ ] 编写单元测试（覆盖率>80%）

### 阶段3：基础设施层重构（2-3周）
- [ ] 重构数据库访问（Repository模式）
- [ ] 重构网络通信（RPC抽象）
- [ ] 重构配置管理（环境变量+YAML）
- [ ] 编写集成测试

### 阶段4：应用层重构（1-2周）
- [ ] 实现用例（ComputeJob、UploadResult等）
- [ ] 编写用例测试

### 阶段5：表示层重构（1-2周）
- [ ] 将GUI与业务逻辑解耦
- [ ] 使用依赖注入连接各层
- [ ] 端到端测试

### 阶段6：迁移和上线（1周）
- [ ] 数据库迁移脚本
- [ ] 部署文档
- [ ] 用户培训
- [ ] 灰度发布

---

## 八、风险评估与缓解措施

| 风险项 | 可能性 | 影响 | 缓解措施 |
|--------|--------|------|----------|
| 重构期间系统不可用 | 中 | 高 | 增量重构，保持向后兼容 |
| 测试覆盖不足导致回归 | 高 | 高 | 先补充测试，再重构 |
| 团队学习成本高 | 中 | 中 | 编写详细文档，定期培训 |
| 依赖库升级冲突 | 低 | 中 | 锁定依赖版本，谨慎升级 |

---

## 九、技术选型建议

### 9.1 依赖注入框架
- **推荐**：`dependency-injector` 或 `punq`
- **原因**：解耦模块，便于测试

### 9.2 配置管理
- **推荐**：`pydantic-settings` + YAML
- **原因**：类型安全，环境变量支持

### 9.3 数据库迁移
- **推荐**：`alembic`
- **原因**：版本化管理，可回滚

### 9.4 异步框架（可选）
- **推荐**：`asyncio` + `aiofiles`
- **原因**：提升文件上传性能

### 9.5 API文档（如需要REST API）
- **推荐**：`FastAPI`
- **原因**：自动生成文档，类型安全

---

## 十、关键设计原则

1. **单一职责原则（SRP）**：每个类只负责一件事
2. **依赖倒置原则（DIP）**：依赖抽象而非具体实现
3. **开闭原则（OCP）**：对扩展开放，对修改封闭
4. **接口隔离原则（ISP）**：客户端不应依赖不需要的接口
5. **领域驱动设计（DDD）**：业务逻辑独立于技术实现

---

## 十一、总结

### 重构收益
✅ **可维护性**：分层清晰，修改一处不影响全局  
✅ **可测试性**：每层独立测试，覆盖率提升  
✅ **可扩展性**：添加新功能只需新增用例和实现  
✅ **可读性**：代码组织合理，新人上手快  
✅ **稳定性**：充分测试，减少线上故障  

### 注意事项
⚠️ **渐进式重构**：不要一次性推翻重写  
⚠️ **保持兼容性**：数据库和协议需向后兼容  
⚠️ **测试先行**：先补充测试，再重构  
⚠️ **团队共识**：确保团队理解新架构  

---

## 附录：参考资料

- **Clean Architecture** (Robert C. Martin)
- **Domain-Driven Design** (Eric Evans)
- **Python Design Patterns** (Brandon Rhodes)
- **Refactoring** (Martin Fowler)

---

**作者**：AI助手  
**创建日期**：2026-01-19  
**版本**：v1.0  
**状态**：讨论稿
