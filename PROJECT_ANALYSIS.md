# 差旅 Agent (travel-agent-mvp) 项目分析报告

> 分析日期：2026-06-04

---

## 📌 一句话概述

这是一个**企业级差旅 AI Agent 的 MVP（最小可行产品）**，用纯 Python 标准库实现，无需任何外部依赖。它模拟了一个完整的企业差旅申请-审批-下单流程，并且具备生产级运维能力（告警、看板、死信队列、灰度发布、审计等）。

---

## 🎯 核心业务场景

用户在企业内部发起出差申请，Agent 自动完成以下闭环：

```
用户提交出差请求（出发地、目的地、日期、预算…）
  → ① 差旅政策校验（预算是否超标、交通等级是否合规）
  → ② 行程规划（生成日程草案）
  → ③ 酒店/交通查询（搜索可用库存）
  → ④ 用户确认选择
  → ⑤ 创建 OA 审批单
  → ⑥ 审批通过后 → 创建交通订单 → 锁定酒店库存 → 创建酒店订单
  → ⑦ 日历同步 + 通知发送
```

同时覆盖异常路径：**审批驳回、价格变化、库存失效、订单失败、改签退订** 等场景的补偿处理。

---

## 🏗️ 架构分层

项目采用**分层架构**，共 21 个 Python 模块，全部在 `src/travel_agent/` 下：

| 层级 | 模块 | 职责 |
|------|------|------|
| **入口层** | `cli.py` | 命令行界面，150+ 参数，内嵌 HTTP 服务器 |
| **编排层** | `agent.py` | `TravelAgent` 核心编排器，管理整个差旅生命周期 |
| **子 Agent 层** | `domain_agents.py` | 6 个专业子 Agent：Policy、Itinerary、Hotel、Transport、Approval、Booking |
| **工具层** | `tools.py` + `mock_tools.py` + `integrations.py` | Tool Gateway 工具注册/调用/审计 + Mock 实现 + 真实 HTTP 集成 |
| **领域模型** | `models.py` + `state.py` | 30+ 数据类（dataclass）+ 13 状态工作流状态机 |
| **持久化** | `storage.py` | 3 种后端：内存 / SQLite（15 张表）/ HTTP 桥接 |
| **运维层** | `operations.py` + `worker.py` + `observability.py` | 看板、告警、runbook、OnCall、死信、SLA、调度、审计 |
| **治理层** | `permissions.py` + `data_governance.py` + `release_control.py` + `release_gate.py` | 权限、数据脱敏、灰度发布、发布门禁 |
| **质量层** | `evaluation.py` + `acceptance.py` + `smoke.py` + `governance.py` | 评测集、集成验收、探活、发布治理 |

### 模块依赖关系

```
Level 0（无内部依赖）:
  config.py          — 环境变量配置
  models.py          — 领域数据模型

Level 1（依赖 Level 0）:
  state.py           — 工作流状态机
  mock_tools.py      — Mock 工具实现
  tools.py           — Tool Gateway
  data_governance.py — 审计与脱敏

Level 2（依赖 Level 0-1）:
  integrations.py    — HTTP 集成适配器
  permissions.py     — 权限策略
  observability.py   — 可观性
  acceptance.py      — 集成验收
  governance.py      — 发布治理
  release_control.py — 灰度发布
  release_gate.py    — 发布门禁
  smoke.py           — 探活测试
  evaluation.py      — 评测集
  storage.py         — 存储后端

Level 3（依赖 Level 0-2）:
  domain_agents.py   — 6 个子 Agent
  worker.py          — 异步 Worker

Level 4（编排层）:
  agent.py           — 核心编排器
  operations.py      — 运维模块

Level 5（入口）:
  cli.py             — CLI 入口
  __init__.py        — 包外观
```

---

## 🔄 工作流状态机（13 个状态）

在 `src/travel_agent/state.py` 中定义，`TravelState` 枚举 + `ALLOWED_TRANSITIONS` 白名单：

```
DRAFT → POLICY_CHECKED → PLAN_GENERATED → USER_CONFIRMED
  → APPROVAL_CREATED → APPROVAL_APPROVED
  → INVENTORY_LOCKED → ORDER_CREATED → COMPLETED

异常路径：
  APPROVAL_REJECTED  ← 从 APPROVAL_CREATED 进入（审批被驳回）
  PRICE_CHANGED      ← 从 INVENTORY_LOCKED 进入（价格发生变化，需二次确认）
  INVENTORY_EXPIRED  ← 从 APPROVAL_APPROVED 进入（库存过期）
  ORDER_FAILED       ← 从 INVENTORY_LOCKED 进入（订单创建失败）
  USER_CANCELLED     ← 从任意状态进入（用户主动取消）
```

所有状态转换有严格的白名单约束，非法跳转会直接报错。

---

## 🧠 多 Agent 协作模式

`TravelAgent`（`src/travel_agent/agent.py`）作为总编排器，内部协调 6 个专业子 Agent（`src/travel_agent/domain_agents.py`）：

| 子 Agent | 类名 | 职责 |
|----------|------|------|
| 政策 Agent | `PolicyAgent` | 酒店预算政策 + 交通等级政策校验 |
| 行程 Agent | `ItineraryAgent` | 行程规划（日程、会议安排） |
| 酒店 Agent | `HotelAgent` | 酒店查询、库存锁定、价格校验、库存释放 |
| 交通 Agent | `TransportAgent` | 机票/火车票查询、订单创建/取消/改签、退款估算 |
| 审批 Agent | `ApprovalAgent` | OA 审批创建、状态查询、取消、改签审批 |
| 下单 Agent | `BookingAgent` | 酒店订单创建/取消/改签、退款估算 |

所有子 Agent 通过 `AgentTeam` 统一管理，每个 Agent 的执行记录（输入、输出、耗时）都会被写入 `AgentExecutionRecord`。

---

## 🔧 Tool Gateway 设计

所有工具调用都通过 `ToolGateway`（`src/travel_agent/tools.py`）统一管理：

- **工具注册**：每个工具有参数规格（必填/可选/类型）
- **参数校验**：调用前自动校验参数合法性
- **审计日志**：每次调用自动生成脱敏审计事件（`src/travel_agent/data_governance.py`）
- **双通道**：优先调用真实 HTTP 系统（`src/travel_agent/integrations.py`），失败时自动 fallback 到 Mock（`src/travel_agent/mock_tools.py`），可通过环境变量控制
- **数据标记**：所有返回数据带 `source` 字段（`"mock"` / `"real"` / `"mock_fallback"`），区分数据来源

---

## 💾 存储方案

`src/travel_agent/storage.py` 提供 3 种后端，通过 `SessionStore` 协议统一接口：

| 后端 | 类名 | 适用场景 |
|------|------|---------|
| 内存 | `InMemorySessionStore` | 开发/测试 |
| SQLite | `SQLiteSessionStore` | 本地持久化（15 张表，WAL 模式，乐观并发控制） |
| HTTP | `HttpSessionStore` | 桥接外部 PostgreSQL/MySQL/工作流引擎 |

### SQLite 表结构（Schema Version 13）

| 表名 | 用途 |
|------|------|
| `travel_sessions` | 核心工作流会话 |
| `worker_runs` | Worker 执行历史 |
| `operations_dashboard_snapshots` | 看板快照 |
| `operations_closed_loop_snapshots` | 闭环 BI 快照 |
| `oncall_ticket_statuses` | OnCall 工单状态 |
| `oncall_webhook_events` | Webhook 事件（验签、去重） |
| `oncall_webhook_replay_jobs` | Webhook 重放任务 |
| `operations_trend_alerts` | 趋势阈值告警 |
| `operations_action_items` | 行动项跟踪 |
| `operations_knowledge_entries` | 运营知识库 |
| `operations_scheduled_tasks` | 周期调度任务（租约锁） |
| `operations_scheduler_runs` | 调度执行历史 |
| `operations_governance_policy_changes` | 治理策略变更 |
| `operations_console_action_audits` | 控制台操作审计 |
| `operations_audit_sink_deliveries` | 外部审计投递 |
| `operations_compensation_tasks` | 补偿任务版 |

自动选择策略：配置了 `TRAVEL_SESSION_STORE_API_URL` 则用 HTTP，否则用 SQLite（默认路径 `travel_sessions.db`）。

---

## 📊 运维能力

这是项目最"重"的部分，远超普通 MVP，主要在 `src/travel_agent/operations.py` 中实现：

| 功能 | 说明 |
|------|------|
| **运行看板** | 多维度运营视图、趋势分析、环比报告 |
| **告警系统** | 阈值告警、路由规则、升级/静默策略 |
| **OnCall 集成** | 工单创建、状态同步、Webhook 验签/去重/回放 |
| **死信队列** | 通知失败、日历同步失败 → 死信 → 查询/重放 |
| **事故演练** | runbook 输出、演练 gate 退出码 |
| **知识库** | 运营知识沉淀、检索、接入 Agent 规划 |
| **SLA 管理** | 行动项 SLA 评估、自动升级通知 |
| **闭环报表** | BI 报表（summary/JSON/Prometheus）、Schema Registry 发布 |
| **定时调度** | 租约锁调度器，支持周期任务 |
| **治理变更** | 策略变更提案 → 审批 → 回滚，全程审计 |
| **补偿任务** | 统一任务板，跟踪所有补偿/恢复动作 |

### 内嵌 HTTP 服务

`--serve-operations-dashboard` 启动的 HTTP 服务提供以下端点：

| 端点 | 功能 |
|------|------|
| `/health` | 健康检查 |
| `/metrics` | Prometheus 指标 |
| `/operations/closed-loop` | 闭环看板 JSON |
| `/operations/console` | 聚合控制台 |
| `/operations/console/view` | RBAC 视图 |
| `/operations/console/ui` | 只读 HTML 页面 |
| `/operations/console/actions` | 受保护的操作接口 |
| `/operations/console/audit-timeline` | 统一操作审计时间线 |
| `/operations/console/audit-sink-deliveries` | 外部审计投递状态 |
| `/operations/console/compensation-tasks` | 补偿任务板 |

---

## 🌐 外部系统集成

通过 `TRAVEL_*` 环境变量配置 30+ 外部 HTTP 端点（`src/travel_agent/config.py`）：

### 核心差旅系统
- 差旅政策 API（酒店预算 + 交通等级）
- 酒店库存查询 / 价格校验 / 库存锁定 / 库存释放 API
- 交通库存查询 / 订单创建 / 取消 / 改签 API
- OA 审批创建 / 状态查询 / 取消 API
- 酒店订单创建 / 取消 / 状态查询 API
- 退款估算 / 确认 API
- 改签审批 API

### 企业协作系统
- 通知/消息 API
- 企业日历 API

### 运维系统
- 权限/IAM API
- 审计日志 API
- 告警平台 API
- OnCall/工单 API
- OpenTelemetry Collector (OTLP/HTTP)
- 闭环 BI API
- Schema Registry
- 恢复审批 API
- 恢复治理策略 API

---

## 🚀 运行方式

### 基础差旅申请

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --origin 北京 --destination 上海 `
    --start 2026-06-03 --end 2026-06-05 `
    --venue "上海张江人工智能岛" --purpose "客户会议" `
    --budget 650 --auto-confirm
```

不加 `--auto-confirm` 时，CLI 只生成差旅方案和酒店推荐，不会创建审批草稿。

### 自动完成全流程

```powershell
python -m travel_agent.cli --origin 北京 --destination 上海 `
    --start 2026-06-03 --end 2026-06-05 `
    --budget 650 --auto-book
```

### 指定酒店和交通方案

```powershell
python -m travel_agent.cli ... --hotel-id <id> --transport-id <id>
```

### 会话管理与恢复

```powershell
# 持久化会话
python -m travel_agent.cli ... --session-db travel.db

# 取消会话
python -m travel_agent.cli --cancel-session <session_id> --cancel-reason "..."

# 异常恢复重新规划
python -m travel_agent.cli --replan-session <session_id> --replan-reason "..."

# 执行恢复策略
python -m travel_agent.cli --execute-recovery-strategy-session <session_id>
```

### 改签与退订

```powershell
# 改签
python -m travel_agent.cli --change-session <session_id> `
    --new-depart-at "2026-06-04T10:00:00" `
    --new-check-in "2026-06-04" --new-check-out "2026-06-06"

# 退款估算
python -m travel_agent.cli --estimate-refund-session <session_id>
```

### Worker 异步推进

```powershell
# 单次运行
python -m travel_agent.cli --run-worker-once --worker-limit 50

# 自动恢复异常状态
python -m travel_agent.cli --run-worker-once --worker-auto-recover

# 多轮循环
python -m travel_agent.cli --run-worker-once --worker-iterations 5 --worker-interval 10
```

### 运维与监控

```powershell
# 运行看板
python -m travel_agent.cli --operations-dashboard

# 启动运维 HTTP 服务
python -m travel_agent.cli --serve-operations-dashboard --operations-dashboard-port 8080

# 启动 Prometheus 指标服务
python -m travel_agent.cli --serve-metrics --metrics-port 9090

# 告警管理
python -m travel_agent.cli --operations-alerts --operations-alert-format json

# 闭环报表
python -m travel_agent.cli --operations-closed-loop-report --operations-closed-loop-format prometheus

# 运营调度
python -m travel_agent.cli --run-operations-schedule --operations-scheduler-owner "ops-bot"
```

### 质量保障

```powershell
# 运行评测集（8 个场景）
python -m travel_agent.cli --run-evaluation-suite

# 集成验收报告
python -m travel_agent.cli --run-integration-acceptance

# 探活测试
python -m travel_agent.cli --run-smoke-probes

# 发布就绪检查
python -m travel_agent.cli --release-readiness

# CI/CD 门禁
python -m travel_agent.cli --release-gate
```

---

## ✅ 测试覆盖

单个测试文件 `tests/test_agent.py`（约 4600 行），使用 Python 标准库 `unittest` 框架：

| 测试类 | 覆盖内容 |
|--------|---------|
| `TravelAgentFlowTest` | 端到端差旅流程：规划、审批、下单、取消、退款、改签、日历同步 |
| `MultiAgentStructureTest` | 多 Agent 结构验证、执行摘要、补偿任务生命周期 |
| `IntegrationAdapterTest` | HTTP 集成适配器、Mock fallback、异常恢复、治理策略变更 |
| `ToolGatewayTest` | 工具参数校验、脱敏审计、HTTP 审计 Sink |
| `SessionStoreTest` | SQLite/HTTP 存储、乐观并发、死信、Worker 运行记录 |
| `WorkflowWorkerTest` | 异步推进、自动恢复、灰度策略、通知死信重试 |
| `CliRenderTest` | CLI 渲染、Prometheus 指标、OTLP 导出、SLA 告警 |
| `EvaluationSuiteTest` | 8 个评测场景（全部必须 PASS） |
| `IntegrationAcceptanceTest` | 集成验收报告 |
| `SmokeProbeTest` | 探活测试 |
| `ReleaseControlTest` | 灰度发布与回滚 |
| `OperationsReadinessTest` | 运维就绪：看板、告警、OnCall、Webhook、调度、补偿任务 |

运行测试：

```powershell
python -m unittest discover -s tests
```

---

## 🎨 设计亮点

1. **零外部依赖**：纯 Python 标准库，`pyproject.toml` 中 `dependencies = []`
2. **不可变数据模型**：所有领域对象用 `@dataclass(frozen=True)`，仅 `TravelContext` 为可变聚合根
3. **协议导向**：`SessionStore`、`HttpJsonClient`、`AuditSink` 都用 `Protocol` 定义接口，方便替换实现
4. **确定性状态机**：所有状态转换白名单化，杜绝非法状态跳转
5. **Mock Fallback 机制**：每个集成点都可配置"真实失败时自动降级为 Mock"，数据标记 `source` 字段区分来源
6. **幂等设计**：所有外部操作带幂等键，防止重复执行
7. **乐观并发**：SQLite 存储使用版本号实现乐观锁
8. **数据治理**：Tool Gateway 所有调用自动脱敏，敏感字段不进入审计日志
9. **灰度发布**：支持按用户/部门/百分比放量，内置回滚机制
10. **生产就绪**：评测集、集成验收、探活、发布门禁形成完整的 CI/CD 质量防线

---

## 📁 项目文件总览

```
D:\study3\jd\xcw\
├── .gitignore
├── pyproject.toml                    # 项目配置（零依赖）
├── README.md                         # 详细中文文档（650 行）
├── docs/
│   └── travel-agent-architecture.md  # 架构设计文档（696 行）
├── src/
│   └── travel_agent/
│       ├── __init__.py               # 包外观，统一导出
│       ├── agent.py                  # 核心编排器 TravelAgent
│       ├── domain_agents.py          # 6 个子 Agent
│       ├── models.py                 # 30+ 领域数据模型
│       ├── state.py                  # 13 状态状态机
│       ├── tools.py                  # Tool Gateway
│       ├── mock_tools.py             # Mock 工具实现
│       ├── integrations.py           # HTTP 集成适配器
│       ├── config.py                 # 环境变量配置
│       ├── storage.py                # 3 种存储后端
│       ├── worker.py                 # 异步 Worker
│       ├── cli.py                    # CLI 入口（150+ 参数）
│       ├── permissions.py            # 权限策略
│       ├── data_governance.py        # 审计与脱敏
│       ├── observability.py          # OTLP/Prometheus 可观性
│       ├── operations.py             # 运维模块（最大模块）
│       ├── evaluation.py             # 内置评测集
│       ├── acceptance.py             # 集成验收
│       ├── smoke.py                  # 探活测试
│       ├── governance.py             # 发布治理
│       ├── release_gate.py           # 发布门禁
│       └── release_control.py        # 灰度发布
└── tests/
    └── test_agent.py                 # 单元测试（4600 行）
```

---

## 📝 总结

这是一个**架构设计精良、运维能力完备**的企业级 AI Agent 教学/演示项目。尽管标为 "MVP"，实际覆盖了从业务编排到生产运维的完整链路：

- **业务层**：完整的差旅申请-审批-下单闭环 + 异常补偿
- **Agent 层**：多 Agent 协作、Tool Gateway、状态机编排
- **基础设施层**：多存储后端、异步 Worker、死信队列
- **运维层**：看板、告警、OnCall、SLA、知识库、调度
- **治理层**：权限、审计、脱敏、灰度发布、CI/CD 门禁

非常适合作为企业 AI Agent 落地实践的参考架构。