# runFluent 项目重构架构规划 - 总览

> **状态**: 📝 讨论方案  
> **版本**: v1.0  
> **日期**: 2026-01-19

---

## 🎯 项目概述

**runFluent** 是一个基于 Python 的分布式 ANSYS Fluent CFD 计算系统，用于在多台计算机上管理和执行流体动力学仿真任务。

### 当前架构特点
- ✅ 客户端-服务器架构
- ✅ 自定义 JSON-over-TCP 协议
- ✅ SQLite 任务管理
- ✅ SFTP 文件传输（与NAS集成）
- ✅ 自定义收敛性检测

### 存在的问题
- ❌ 缺乏分层设计，业务逻辑与UI混杂
- ❌ 模块职责不清，单文件承担过多责任
- ❌ 配置管理混乱，硬编码严重
- ❌ 缺乏测试覆盖
- ❌ 难以扩展和维护

---

## 📚 文档导航

本重构方案包含三份核心文档，建议按以下顺序阅读：

### 1. [REFACTORING_PLAN.md](./REFACTORING_PLAN.md) - 主设计文档
**阅读时间**: 45分钟  
**适合人群**: 项目负责人、架构师、技术决策者

**核心内容**:
- 现状分析（优点与问题）
- Clean Architecture 分层设计
- 完整目录结构规划
- 领域层/应用层/基础设施层设计
- 数据库迁移策略
- 测试策略（单元/集成/E2E）
- Docker 部署方案
- 6阶段实施计划（8-12周）
- 风险评估与技术选型

### 2. [docs/architecture_comparison.md](./docs/architecture_comparison.md) - 对比分析
**阅读时间**: 20分钟  
**适合人群**: 开发团队、代码审查者

**核心内容**:
- 现状架构 vs 重构后架构（可视化图表）
- 数据流对比
- 配置管理对比
- 测试策略对比
- 部署方式对比
- 量化改进指标

### 3. [docs/quick_start_guide.md](./docs/quick_start_guide.md) - 实施指南
**阅读时间**: 30分钟  
**适合人群**: 执行重构的开发者

**核心内容**:
- 开发环境设置
- 目录结构搭建
- Job实体完整代码示例
- 单元测试编写
- SQLite仓储实现
- 用例实现（ComputeJobUseCase）
- 集成测试示例
- TDD工作流
- CI/CD配置

---

## 🏗️ 重构架构一览

### 分层设计（Clean Architecture）

```
┌─────────────────────────────────────────┐
│     Presentation Layer (表示层)          │
│  ClientWindow / MonitorWindow / CLI     │
└──────────────┬──────────────────────────┘
               │ 依赖注入
┌──────────────▼──────────────────────────┐
│     Application Layer (应用层)           │
│  ComputeJobUseCase / UploadResultUseCase│
└──────────────┬──────────────────────────┘
               │ 调用
┌──────────────▼──────────────────────────┐
│      Domain Layer (领域层)               │
│  Job实体 / Scheduler / ConvergenceDetector│
└──────────────┬──────────────────────────┘
               │ 依赖倒置
┌──────────────▼──────────────────────────┐
│  Infrastructure Layer (基础设施层)        │
│  SQLiteRepository / RPCClient / SFTPClient│
└─────────────────────────────────────────┘
```

### 推荐目录结构

```
src/
├── domain/                    # 领域层
│   ├── entities/             # 实体（Job、Client、Result）
│   ├── services/             # 领域服务（Scheduler、ConvergenceDetector）
│   └── repositories/         # 仓储接口
│
├── application/               # 应用层
│   ├── use_cases/            # 用例（ComputeJob、UploadResult等）
│   └── dto/                  # 数据传输对象
│
├── infrastructure/            # 基础设施层
│   ├── database/             # SQLite仓储实现
│   ├── network/              # RPC + SFTP
│   ├── compute/              # Fluent执行器
│   └── config/               # 配置管理
│
├── presentation/              # 表示层
│   ├── gui/                  # Tkinter GUI
│   └── cli/                  # 命令行接口
│
└── common/                    # 公共工具
    ├── logging.py
    ├── exceptions.py
    └── utils.py
```

---

## 📊 预期改进效果

| 维度 | 现状 | 重构后 | 提升 |
|------|------|--------|------|
| **代码行数** | ~2000行 | ~3500行 | +75% (更详细的抽象) |
| **测试覆盖率** | 0% | >80% | ∞ |
| **模块耦合度** | 高 | 低 | 易维护 |
| **可扩展性** | 差 | 好 | 灵活 |
| **配置灵活性** | 差 | 好 | 易部署 |
| **新人上手时间** | 2-3周 | 1周 | 50% |
| **Bug修复时间** | 2-4小时 | 1小时 | 50% |

---

## 🚀 实施计划

### 阶段划分（8-12周）

| 阶段 | 时间 | 任务 | 产出 |
|------|------|------|------|
| **阶段1** | 1-2周 | 准备工作 | 目录结构、CI/CD、测试框架 |
| **阶段2** | 2-3周 | 领域层重构 | Job实体、领域服务、单元测试 |
| **阶段3** | 2-3周 | 基础设施层重构 | 仓储、RPC、配置管理、集成测试 |
| **阶段4** | 1-2周 | 应用层重构 | 用例实现、用例测试 |
| **阶段5** | 1-2周 | 表示层重构 | GUI解耦、依赖注入、E2E测试 |
| **阶段6** | 1周 | 迁移上线 | 数据库迁移、部署、培训 |

### 关键里程碑

- **M1 (第2周)**: 完成目录结构和测试框架搭建
- **M2 (第4周)**: 完成领域层实现，单元测试覆盖率>80%
- **M3 (第7周)**: 完成基础设施层和应用层，集成测试通过
- **M4 (第9周)**: 完成表示层解耦，E2E测试通过
- **M5 (第10周)**: 灰度上线，功能完全迁移

---

## 🛠️ 技术栈

### 核心依赖
- **Python**: 3.11+
- **ansys-fluent-core**: Fluent API
- **paramiko**: SFTP/SSH
- **psutil**: 系统资源检测

### 新增依赖
- **pydantic**: 配置管理（类型安全）
- **alembic**: 数据库迁移
- **pytest**: 测试框架
- **pytest-cov**: 覆盖率统计
- **black**: 代码格式化
- **flake8**: 代码检查
- **mypy**: 类型检查

### 可选增强
- **FastAPI**: REST API（如需要）
- **asyncio**: 异步IO优化
- **structlog**: 结构化日志

---

## ⚠️ 风险与缓解

| 风险项 | 可能性 | 影响 | 缓解措施 |
|--------|--------|------|----------|
| 重构期间系统不可用 | 中 | 高 | 渐进式重构，保持向后兼容 |
| 测试覆盖不足导致回归 | 高 | 高 | 先补充测试，再重构 |
| 团队学习成本高 | 中 | 中 | 详细文档 + 定期培训 |
| 依赖库升级冲突 | 低 | 中 | 锁定版本，谨慎升级 |

---

## 🎓 学习资源

### 推荐阅读
1. **Clean Architecture** - Robert C. Martin
2. **Domain-Driven Design** - Eric Evans
3. **Refactoring** - Martin Fowler
4. **Python Testing with pytest** - Brian Okken

### 在线资源
- [Clean Architecture (博客)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [DDD Quickly (电子书)](https://www.infoq.com/minibooks/domain-driven-design-quickly/)
- [pytest 文档](https://docs.pytest.org/)
- [pydantic 文档](https://pydantic-docs.helpmanual.io/)

---

## 🤝 贡献指南

### 代码规范
- 遵循 **PEP 8** 风格指南
- 使用 **black** 格式化代码
- 通过 **flake8** 代码检查
- 通过 **mypy** 类型检查
- 单元测试覆盖率 > 80%

### Git工作流
```bash
# 1. 创建功能分支
git checkout -b feature/job-entity

# 2. 编写代码和测试
# ...

# 3. 运行测试
pytest tests/

# 4. 代码检查
black src/ tests/
flake8 src/ tests/
mypy src/

# 5. 提交
git commit -m "feat: implement Job entity with state machine"

# 6. 推送并创建PR
git push origin feature/job-entity
```

---

## 📞 联系方式

### 项目相关问题
- **GitHub Issues**: [提交Issue](https://github.com/FuShengban/runFluent/issues)
- **Pull Requests**: [提交PR](https://github.com/FuShengban/runFluent/pulls)

### 架构讨论
如有架构相关问题或建议，欢迎：
1. 在GitHub Issues中标记为 `architecture` 标签
2. 发起Discussion讨论
3. 在代码审查时提出

---

## 📝 变更日志

### v1.0 (2026-01-19)
- ✅ 完成现状分析
- ✅ 设计Clean Architecture分层架构
- ✅ 编写三份核心文档（规划、对比、指南）
- ✅ 制定6阶段实施计划
- ✅ 提供完整代码示例

---

## ⚖️ 许可证

本项目遵循原项目的许可证。

---

## 🎉 下一步行动

### 如果您认可这个方案：

1. **审阅文档**
   - [ ] 阅读 REFACTORING_PLAN.md
   - [ ] 阅读 docs/architecture_comparison.md
   - [ ] 阅读 docs/quick_start_guide.md

2. **反馈收集**
   - [ ] 架构设计是否合理？
   - [ ] 实施计划是否可行？
   - [ ] 有哪些需要调整的？

3. **开始实施**（得到您的批准后）
   - [ ] 阶段1：搭建目录结构
   - [ ] 实现第一个领域实体
   - [ ] 编写第一批单元测试
   - [ ] 设置CI/CD流水线

---

**这是讨论方案，期待您的反馈！** 💬

如有任何问题或建议，请：
- 在PR中评论
- 创建GitHub Issue
- 直接与团队沟通

**感谢您的时间和审阅！** 🙏
