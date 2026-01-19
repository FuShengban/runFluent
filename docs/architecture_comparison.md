# runFluent 架构对比：现状 vs. 重构后

## 一、现状架构（扁平化单体）

```
┌───────────────────────────────────────────────────────────────┐
│                         当前架构                               │
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ client_app.py│  │monitor_app.py│  │launcher.py   │       │
│  │ (GUI + Logic)│  │ (GUI + Logic)│  │              │       │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘       │
│         │                  │                                   │
│         └──────────┬───────┘                                   │
│                    │                                           │
│         ┌──────────▼──────────┐                               │
│         │   client_core.py    │◄────┐                         │
│         │ (业务逻辑混杂)       │     │                         │
│         └──────────┬──────────┘     │                         │
│                    │                 │                         │
│    ┌───────────────┼─────────────────┼───────┐               │
│    │               │                 │       │               │
│    ▼               ▼                 ▼       ▼               │
│ ┌─────────┐ ┌─────────────┐ ┌──────────┐ ┌──────────┐      │
│ │fluent_  │ │db_manager.py│ │protocol  │ │sftp_     │      │
│ │worker.py│ │(SQLite直接  │ │.py       │ │utils.py  │      │
│ │         │ │ 访问)        │ │(TCP协议) │ │          │      │
│ └─────────┘ └─────────────┘ └──────────┘ └──────────┘      │
│                                                                │
│                ┌──────────────────┐                           │
│                │server_service.py │                           │
│                │(服务端:逻辑+协议)│                           │
│                └──────────────────┘                           │
└───────────────────────────────────────────────────────────────┘
```

### 问题清单
❌ **UI与业务逻辑耦合**：GUI代码里直接调用数据库和网络  
❌ **职责不清**：client_core.py 包含太多不相关的功能  
❌ **难以测试**：无法单独测试业务逻辑  
❌ **配置硬编码**：config.py里混杂各种配置  
❌ **无依赖注入**：模块间紧耦合  
❌ **缺乏抽象**：直接依赖SQLite和TCP实现  

---

## 二、重构后架构（分层清晰）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Presentation Layer (表示层)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ClientWindow  │  │MonitorWindow │  │LauncherWindow│             │
│  │(纯UI逻辑)    │  │(纯UI逻辑)    │  │              │             │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘             │
│         │                  │                                         │
│         │ 依赖注入         │                                         │
│         ▼                  ▼                                         │
└─────────┼──────────────────┼─────────────────────────────────────────┘
          │                  │
┌─────────▼──────────────────▼─────────────────────────────────────────┐
│                     Application Layer (应用层)                        │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐        │
│  │ComputeJobUseCase│ │UploadResultUseCase│ │AssignJobUseCase│      │
│  │(计算任务流程)   │  │(上传结果流程)   │  │(分配任务流程) │        │
│  └────────┬───────┘  └────────┬───────┘  └────────┬───────┘        │
│           │                   │                    │                 │
│           └───────────────────┼────────────────────┘                 │
│                               │                                      │
└───────────────────────────────┼──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│                      Domain Layer (领域层)                            │
│  ┌──────────────────────────────────────────────────────┐           │
│  │                  Entities (实体)                      │           │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐             │           │
│  │  │  Job    │  │ Client  │  │ Result  │             │           │
│  │  │(状态机) │  │         │  │         │             │           │
│  │  └─────────┘  └─────────┘  └─────────┘             │           │
│  └──────────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────────┐           │
│  │              Domain Services (领域服务)               │           │
│  │  ┌──────────────┐  ┌──────────────────┐             │           │
│  │  │JobScheduler  │  │ConvergenceDetector│            │           │
│  │  │(任务调度)    │  │(收敛检测)         │            │           │
│  │  └──────────────┘  └──────────────────┘             │           │
│  └──────────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────────┐           │
│  │           Repository Interfaces (仓储接口)            │           │
│  │  ┌──────────────────┐                                │           │
│  │  │JobRepository     │ (抽象接口)                     │           │
│  │  └──────────────────┘                                │           │
│  └──────────────────────────────────────────────────────┘           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 依赖倒置
┌───────────────────────────────▼──────────────────────────────────────┐
│                  Infrastructure Layer (基础设施层)                    │
│  ┌──────────────────────────────────────────────────────┐           │
│  │                Database (数据库)                      │           │
│  │  ┌──────────────────┐  ┌─────────────┐              │           │
│  │  │SQLiteJobRepository│ │Migrations   │              │           │
│  │  │(具体实现)        │  │(版本管理)   │              │           │
│  │  └──────────────────┘  └─────────────┘              │           │
│  └──────────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────────┐           │
│  │                Network (网络)                         │           │
│  │  ┌──────────────┐  ┌──────────────┐                 │           │
│  │  │RPCServer     │  │RPCClient     │                 │           │
│  │  │(服务端)      │  │(客户端)      │                 │           │
│  │  └──────────────┘  └──────────────┘                 │           │
│  │  ┌──────────────┐                                    │           │
│  │  │SFTPClient    │                                    │           │
│  │  │(文件传输)    │                                    │           │
│  │  └──────────────┘                                    │           │
│  └──────────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────────┐           │
│  │                Compute (计算)                         │           │
│  │  ┌──────────────────┐                                │           │
│  │  │FluentExecutor    │                                │           │
│  │  │(Fluent封装)      │                                │           │
│  │  └──────────────────┘                                │           │
│  └──────────────────────────────────────────────────────┘           │
│  ┌──────────────────────────────────────────────────────┐           │
│  │              Config (配置)                            │           │
│  │  ┌──────────────┐  ┌──────────────┐                 │           │
│  │  │Settings      │  │SecretsManager│                 │           │
│  │  │(环境变量)    │  │(密钥管理)    │                 │           │
│  │  └──────────────┘  └──────────────┘                 │           │
│  └──────────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────────┘
```

### 改进效果
✅ **分层清晰**：各层职责明确，依赖方向统一（向下依赖）  
✅ **高内聚低耦合**：模块间通过接口通信  
✅ **易于测试**：每层可独立测试，支持Mock  
✅ **可扩展**：添加新功能只需新增用例和实现  
✅ **可维护**：修改底层实现不影响业务逻辑  
✅ **依赖注入**：通过DI容器管理对象生命周期  

---

## 三、数据流对比

### 现状：请求处理流程（以"计算任务"为例）

```
用户点击按钮
    │
    ▼
client_app.on_compute_next_async()  ◄─ UI逻辑
    │
    ├─ 直接访问 self.listbox         ◄─ 紧耦合
    ├─ 直接调用 client_core.compute_one_local()
    │      │
    │      ├─ 直接调用 fluent_worker.process_case()
    │      ├─ 直接调用 request(SERVER_HOST, SERVER_PORT, {...})  ◄─ 硬编码
    │      └─ 直接访问 SQLite (如果离线模式)
    │
    └─ 手动刷新 self._refresh_listbox()
```

**问题**：
- UI直接操作业务逻辑
- 业务逻辑直接访问数据库和网络
- 配置硬编码在代码里
- 难以单独测试

---

### 重构后：请求处理流程

```
用户点击按钮
    │
    ▼
ClientWindow.on_compute_clicked()     ◄─ 纯UI逻辑
    │
    ▼
ComputeJobUseCase.execute(case_key)   ◄─ 应用层（用例）
    │
    ├─ job = JobRepository.get(case_key)         ◄─ 通过接口访问
    │     │
    │     └─ SQLiteJobRepository.get()  ◄─ 具体实现（基础设施层）
    │
    ├─ job.start_computing()             ◄─ 领域层（实体状态机）
    │
    ├─ duration = FluentExecutor.run()   ◄─ 基础设施层（计算）
    │
    ├─ job.mark_completed(duration)      ◄─ 领域层
    │
    └─ JobRepository.save(job)           ◄─ 通过接口保存
           │
           └─ SQLiteJobRepository.save()
```

**改进**：
- UI只负责展示和交互
- 用例组织业务流程
- 通过接口访问底层服务
- 每层可独立测试
- 易于替换实现（如换成PostgreSQL）

---

## 四、配置管理对比

### 现状配置

```python
# config.py (所有配置混在一起)
SERVER_HOST = "47.94.211.70"           # 硬编码
SERVER_PORT = 8000
POOL_LIMIT = 100
FLUENT_DIMENSION = 2
NAS_SFTP_HOST = "100.98.245.17"
NAS_DELETE_LOCAL_AFTER_UPLOAD = True

# config_pass.py (敏感信息明文)
ADMIN_PASSWORD = "your_password"       # 不安全！
NAS_SSH_PASSWORD = "nas_password"      # 不安全！
```

**问题**：
- 配置硬编码，修改需要改代码
- 敏感信息明文存储
- 无法根据环境切换配置

---

### 重构后配置

```bash
# .env (环境变量，不提交到Git)
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
POOL_LIMIT=100

FLUENT_DIMENSION=2
FLUENT_PROCESSORS=8

NAS_SFTP_HOST=100.98.245.17
NAS_SFTP_KEY_PATH=/path/to/key
NAS_POOL_PATH=/vol1/1007/fluent_pool

# 敏感信息使用密钥管理器
ADMIN_PASSWORD_ENCRYPTED=<encrypted>
```

```python
# src/infrastructure/config/settings.py (类型安全)
from pydantic import BaseSettings

class ServerConfig(BaseSettings):
    host: str = Field(..., env="SERVER_HOST")
    port: int = Field(8000, env="SERVER_PORT")
    pool_limit: int = Field(100, env="POOL_LIMIT")
    
    class Config:
        env_file = ".env"

# 使用时
config = ServerConfig()  # 自动从环境变量读取
print(config.host)       # 类型安全，IDE有提示
```

**改进**：
- 配置与代码分离
- 支持环境变量
- 类型安全（pydantic验证）
- 敏感信息加密存储
- 易于根据环境切换

---

## 五、测试策略对比

### 现状（几乎无测试）

```
tests/
└── (空)
```

**问题**：
- 无单元测试
- 无集成测试
- 依赖手工测试
- 回归风险高

---

### 重构后（完整测试体系）

```
tests/
├── unit/                      # 单元测试（快速，隔离）
│   ├── domain/
│   │   ├── test_job.py       # 测试Job实体状态机
│   │   └── test_scheduler.py # 测试调度逻辑
│   ├── application/
│   │   └── test_compute_job_use_case.py
│   └── infrastructure/
│       └── test_sqlite_repository.py
│
├── integration/               # 集成测试（中速，组件交互）
│   ├── test_compute_workflow.py
│   └── test_upload_workflow.py
│
└── e2e/                       # 端到端测试（慢，完整流程）
    └── test_full_compute_cycle.py
```

```python
# 示例：单元测试
def test_job_state_machine():
    job = Job(case_key="test", status=JobStatus.PENDING)
    
    # 测试正常流程
    job.assign_to("node1")
    assert job.status == JobStatus.ASSIGNED
    
    job.start_computing()
    assert job.status == JobStatus.COMPUTING
    
    job.mark_completed(120.0)
    assert job.status == JobStatus.COMPLETED
    assert job.duration_sec == 120.0

# 示例：集成测试（使用Mock）
def test_compute_use_case(mock_executor, mock_repo):
    use_case = ComputeJobUseCase(mock_repo, mock_executor)
    
    job = use_case.execute("test.msh", Path("/tmp/test.msh"))
    
    assert job.status == JobStatus.COMPLETED
    mock_executor.run.assert_called_once()
    mock_repo.save.assert_called()
```

**改进**：
- 完整的测试金字塔
- 每层独立测试
- 支持Mock和Stub
- CI/CD自动运行
- 覆盖率监控

---

## 六、部署对比

### 现状部署（手动）

```bash
# 手动步骤
1. git clone ...
2. pip install -r requirements.txt
3. 修改 config.py 和 config_pass.py
4. python server_service.py        # 手动启动
5. python launcher.py              # 手动启动
```

**问题**：
- 环境依赖管理困难
- 配置修改繁琐
- 无法一键部署
- 难以扩展（多台服务器）

---

### 重构后部署（Docker + 编排）

```yaml
# docker-compose.yml
version: '3.8'

services:
  server:
    image: runfluent-server:latest
    ports:
      - "8000:8000"
    environment:
      - SERVER_HOST=0.0.0.0
      - DB_PATH=/data/project.db
      - POOL_LIMIT=100
    volumes:
      - ./data:/data
    restart: unless-stopped

  client:
    image: runfluent-client:latest
    environment:
      - SERVER_HOST=server
      - NODE_NAME=client1
    volumes:
      - /path/to/mesh:/mesh
      - /path/to/results:/results
    depends_on:
      - server
```

```bash
# 一键部署
docker-compose up -d

# 扩展（增加计算节点）
docker-compose scale client=5
```

**改进**：
- 环境一致性（Docker）
- 配置灵活（环境变量）
- 一键部署
- 易于扩展
- 支持自动重启

---

## 七、关键指标对比

| 指标 | 现状 | 重构后 | 改进 |
|------|------|--------|------|
| **代码行数** | ~2000行 | ~3500行 | +75% (更详细的抽象) |
| **测试覆盖率** | 0% | >80% | 质量大幅提升 |
| **模块耦合度** | 高（紧耦合） | 低（松耦合） | 易维护 |
| **可扩展性** | 差（修改多处） | 好（仅新增用例） | 灵活 |
| **配置灵活性** | 差（硬编码） | 好（环境变量） | 易部署 |
| **新人上手时间** | 2-3周 | 1周 | 文档+清晰结构 |
| **Bug修复时间** | 2-4小时 | 1小时 | 快速定位 |

---

## 八、总结

### 核心改进
1. **分层架构**：职责清晰，依赖方向统一
2. **领域驱动**：业务逻辑独立于技术实现
3. **依赖注入**：模块解耦，易于测试和替换
4. **配置管理**：环境变量+类型安全
5. **测试体系**：单元+集成+E2E
6. **容器化部署**：一致性+可扩展

### 迁移策略
采用**渐进式重构**，而非推倒重来：
1. 保留现有代码作为Legacy模块
2. 新功能用新架构开发
3. 逐步迁移旧功能到新架构
4. 保持向后兼容（数据库、协议）
5. 全程测试覆盖

---

**这个方案适合你的团队吗？有任何疑问或建议，请告诉我！**
