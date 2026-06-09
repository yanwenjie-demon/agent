# 差旅 Agent

本仓库包含差旅 AI Agent 的架构设计文档，以及单 Agent 到真实系统接入的阶段性实现。

## 当前能力

- 单 Agent 任务规划
- 多 Agent 协作雏形：`TravelAgent` 作为 Orchestrator/facade，内部拆出 Policy、Itinerary、Hotel、Transport、Approval、Booking 子 Agent
- 领域级 Agent 执行摘要：子 Agent 的动作、输入/输出引用、状态和时间会写入 `AgentExecutionRecord`，支持 SQLite 持久化和 CLI 展示
- Tool Gateway 工具注册、参数校验、调用审计
- 差旅政策校验，支持真实 HTTP 系统和 Mock fallback
- 行程规划 Mock 工具
- 酒店库存查询与推荐，支持真实 HTTP 系统和 Mock fallback
- 交通政策、机票/火车票查询与交通订单，支持真实 HTTP 系统和 Mock fallback
- 用户确认后创建 OA 审批记录，支持真实 HTTP 系统和 Mock fallback
- 审批状态跟踪，审批通过后创建交通订单、锁定酒店库存并创建酒店订单
- 取消补偿：通过 Transport、Booking、Hotel 子 Agent 取消交通订单、取消酒店订单、释放酒店库存
- 异常恢复：审批驳回、价格变化、库存失效、订单失败后可由 Orchestrator 协调子 Agent 补偿并重新规划
- 价格变化二次确认：锁库存后、下单前校验当前价
- 订单状态刷新：订单创建后可同步最新订单状态
- 改签/退订深化：支持改签审批联动、退款确认、交通订单改签、酒店订单改期、供应商失败补偿和改签后日历同步，真实系统未就绪时使用 mock fallback
- 日历同步：订单完成、改签、取消后可同步企业日历，支持真实 HTTP 系统和 mock fallback，失败后可重试、死信查询和重放
- 异步 worker：扫描持久化会话，自动推进审批和订单状态
- 通知/待办回调：关键成功、失败、待确认状态自动发送通知，支持真实 HTTP 系统和 Mock fallback
- 通知重试/死信：通知失败不会阻断主流程，超过重试上限后进入 `DEAD_LETTER`
- 生产化观测：worker 运行摘要落库、死信查询/重放、基础指标输出、Prometheus 文本指标出口、HTTP `/metrics` 服务和 OTLP/HTTP 导出
- 内置评测集：覆盖完整下单、政策超标、审批驳回、价格变化、库存失效、订单失败恢复、改签失败补偿和日历死信
- 生产化存储准备：SQLite 会话持久化支持 schema 版本、会话版本号、乐观并发保存、索引和健康检查，可从 session 恢复流程
- 外部生产存储适配：支持 HTTP JSON `SessionStore` 后端，可桥接 PostgreSQL/MySQL、工作流引擎或内部存储服务，并保留版本控制、健康检查和回放能力
- 真实系统联调验收报告：汇总真实端点配置、mock fallback 风险、存储健康和评测集结果，形成上线前准入检查
- 真实端到端探活：可向已配置真实端点发送 `dry_run` smoke payload，校验响应契约并避免产生真实订单、审批或通知副作用
- 生产发布治理门禁：检查 mock fallback、持久化存储、接口 token、审计留痕、数据最小化、验收和 smoke 结果
- 灰度发布决策：支持按用户、部门和百分比进行放量，并内置回滚阻断
- 权限策略检查：支持按用户、部门、角色和动作做本地权限决策，并提供 CLI 门禁检查
- 数据治理脱敏：Tool Gateway 调用审计会自动生成脱敏事件，避免敏感字段直接进入审计日志
- 外部权限中心和审计落库：支持 HTTP 权限决策和外部审计日志 sink，便于接入 IAM 和合规平台
- 生产运行手册、SLO 告警聚合和事故演练：支持输出上线/灰度/回滚 runbook，并用 mock 信号演练权限中心不可用、审计落库失败、供应商订单失败和回滚开关触发
- 告警平台接入与演练流水线化：operations 告警支持 summary/JSON/Prometheus 输出、HTTP 告警 sink 推送和事故演练 gate 退出码
- 生产运行看板和真实值班闭环：支持运行看板摘要、告警路由/升级/静默规则模板，以及 OnCall/工单 HTTP ticket 创建
- 看板数据落库、工单状态回写和告警规则配置化：支持持久化 dashboard 快照、同步 OnCall 状态，并通过环境变量加载告警规则 JSON
- 运营洞察分析：支持基于 dashboard 快照的趋势/环比分析、多维运行视图，以及自动事故复盘报告
- 运营闭环沉淀：支持趋势阈值告警、复盘/趋势行动项持久化、行动项关闭和运营知识库条目沉淀
- 运营闭环增强：支持运营知识检索、行动项 SLA/升级评估和运营闭环报表
- 运营闭环外联：支持将运营知识检索接入 Agent 规划、行动项 SLA 自动通知，以及闭环报表 summary/JSON/Prometheus/HTTP sink 导出
- 运营闭环深化：支持异常恢复时自动引用运营知识、按 OnCall/工单状态关闭行动项，并持久化闭环报表 snapshot 供定时导出和看板消费
- 运营闭环服务化：异常恢复会记录 `RecoveryStrategyAgent` 自动策略决策和策略 gate，OnCall webhook 支持事件验签、幂等、回放窗口和死信记录，闭环 snapshot 可通过带 token 的 HTTP `/operations/closed-loop` 按 owner 查询
- 运营闭环自动恢复：`execute_recovery_strategy()` 可执行 gate 通过的恢复策略，支持状态刷新、知识重规划、补偿后重规划和审批 override，worker 可通过 `--worker-auto-recover` 显式开启异常状态自动恢复
- Webhook 死信重放与闭环看板增量视图：支持查询/重放 OnCall webhook dead-letter、重放后同步工单状态和行动项关闭，并支持闭环看板 cursor、limit、since、owner 过滤和 `next_cursor`
- 自动恢复治理、Webhook 批处理与 BI 契约深化：恢复执行支持 idempotency key、审批回执、worker 灰度和恢复指标；Webhook dead-letter 支持 payload patch、批量重放和审计 JSON；闭环看板支持部门/租户 metadata 过滤和 checkpoint
- 恢复治理外部化、Webhook 运营控制台与 BI 契约发布：支持恢复策略白名单/黑名单/限流、审批回执外发和恢复失败开 OnCall 工单，Webhook ops console 可汇总死信原因和 patch 模板，闭环看板可输出 JSON Schema、OpenAPI、兼容矩阵和契约校验
- 治理策略中心化、Webhook 控制台服务化与 BI 发布自动化：支持从远端配置中心拉取恢复治理策略、审批回执 SLA/审批人校验和策略变更审计；`--serve-operations-dashboard` 暴露 OnCall webhook ops/replay job 只读接口并复用 token 鉴权；闭环 BI 支持 schema registry 发布、数据质量校验、checkpoint 计划和消费验收报告
- 运维调度、权限审计与控制台聚合：支持默认 operations schedule plan、周期执行闭环 snapshot/checkpoint/质量/SLA/replay job 任务、pending replay job 执行器、运维动作权限 + 脱敏审计，以及 `/operations/console` 聚合 API
- 持久化运维调度与租约锁：支持 `--init-operations-schedule`、`--list-operations-schedule`、`--run-persisted-operations-schedule`，可将 schedule plan 落库到内存、SQLite 或 HTTP store，通过 `lease_owner`/`lease_expires_at` claim due task，并在执行后推进 `next_run_at`、`run_count`、`failure_count` 和失败重试时间
- 调度运行历史与健康告警：scheduler run report 会落库到内存、SQLite 或 HTTP store，`--operations-scheduler-health` 可聚合 run history 和 scheduled task，识别失败 run、过期租约、长期未运行任务和连续失败任务
- Web 控制台与 RBAC 视图：`--serve-operations-dashboard` 新增 `/operations/console/view` 和 `/operations/console/ui`，可按 `X-Operations-Actor`、`X-Operations-Roles`、`X-Operations-Department` 构建 RBAC-aware 控制台视图，展示可见 sections、可执行 actions、权限状态和只读 HTML 页面
- 控制台交互动作、治理变更审批与操作审计：`--serve-operations-dashboard` 新增 `/operations/console/actions`，支持 token + RBAC 保护的 `create_replay_job`、`execute_replay_jobs`、`run_operations_schedule`、`publish_closed_loop_schema`、`propose_governance_policy_change`、`approve_governance_policy_change`、`rollback_governance_policy_change`、`retry_audit_sink_deliveries`、`close_compensation_task`、`execute_compensation_tasks` 和 `remediate_compensation_slo` POST action，可写回 replay job、webhook event、OnCall ticket status、scheduler run history、治理策略变更 diff/审批/回滚记录、补偿任务状态、补偿 SLO 处置记录和控制台 action audit，并向 schema registry 发布 BI contract
- 审计回放查询视图：`--serve-operations-dashboard` 新增 `/operations/console/audit-timeline`，可将控制台 action audit、治理策略变更、replay job 和 scheduler run 聚合成统一操作时间线，并按 `event_type`、`actor`、`action`、`status`、`limit` 过滤查询
- 审计 sink 回放联动：控制台 action audit 可投递到外部审计 sink，并将投递状态落库到内存、SQLite 或 HTTP store；`/operations/console/audit-sink-deliveries` 可查询投递记录，`retry_audit_sink_deliveries` action 可重试失败投递
- 补偿任务生命周期与外部工单联动：`/operations/console/compensation-tasks` 可聚合恢复补偿、replay job、行动项 SLA 和 OnCall 状态为统一任务板，`close_compensation_task` action 可完成人工验收关闭并落库覆盖状态，`execute_compensation_tasks` action 可批量选择 `OPEN` / `ESCALATED` 任务，已有工单进入 `WAITING_ONCALL`，未绑定工单时按 OnCall endpoint 创建外部工单并落库 ticket 状态，未配置 endpoint 时标记 `PENDING_MANUAL`
- 补偿执行策略治理与批量重试：`execute_compensation_tasks` 接入 `OperationsCompensationExecutionPolicy`，支持 `enabled`、`dry_run`、`max_batch_size`、`retry_window_seconds`、`max_failures_per_task`、`allowed_severities` 和 endpoint 强制策略；CLI 支持 `--execute-operations-compensation-tasks`，默认 scheduler 新增 `compensation_task_execution` 批处理任务，执行报告会输出 policy、gate、attempted/succeeded/failed/skipped 并复用控制台 action audit
- 补偿执行可观测闭环与运营报表：`--operations-compensation-observability` 和 `/operations/console/compensation-observability` 会聚合补偿任务 lifecycle、scheduler run history 与控制台 action audit，输出成功率、失败原因、gate 分布、重试等待、人工介入、调度执行量和控制台触发次数
- 补偿执行告警与 SLO 联动：`--operations-compensation-slo`、`--export-operations-compensation-slo-alerts`、`--open-operations-compensation-slo-ticket` 和 `/operations/console/compensation-slo` 会基于补偿执行可观测报表评估 SLO burn rate、失败/重试/人工介入/调度失败告警，并复用告警平台与 OnCall 升级
- 补偿执行自动处置与 Runbook 联动：`--operations-compensation-remediation`、`remediate_compensation_slo`、默认 `compensation_remediation` 调度任务和 `/operations/console/compensation-remediation` 会基于补偿 SLO 告警生成行动项、筛选受控重试候选、执行补偿策略 gate，并输出 runbook 执行记录；`TRAVEL_COMPENSATION_REMEDIATION_POLICY_JSON` 可控制 dry-run、最大重试任务数、行动项 owner/ETA 和允许重试状态/严重级别
- 内存会话状态和确定性工作流状态机

架构说明见 [docs/travel-agent-architecture.md](docs/travel-agent-architecture.md)。

## 运行演示

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-confirm
```

不加 `--auto-confirm` 时，CLI 只生成差旅方案和酒店推荐，不会创建审批草稿。

可用 `--hotel-id` 和 `--transport-id` 指定确认的酒店和交通方案；未指定时默认选择排序第一的推荐。

创建审批后继续自动查审批、锁库存、创建订单：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-book
```

下单后立即执行取消补偿：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-book --cancel-after-book
```

启用 SQLite 会话持久化：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-book
```

之后可用输出中的会话 ID 恢复并取消：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --cancel-session "<session-id>" --cancel-reason "meeting_cancelled"
```

如果流程停在 `PRICE_CHANGED`，可以恢复 session 后接受或拒绝价格变化：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --cancel-session "<session-id>" --accept-price-change
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --cancel-session "<session-id>" --reject-price-change
```

刷新订单状态：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --refresh-order-session "<session-id>"
```

取消前预估酒店和交通退款：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --estimate-refund-session "<session-id>" --cancel-reason "meeting_cancelled"
```

对已完成会话提交交通和酒店改签：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --change-session "<session-id>" --new-depart-at "2026-06-03T13:00:00+08:00" --new-check-in 2026-06-04 --new-check-out 2026-06-06 --change-reason "meeting_rescheduled"
```

同步企业日历：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --sync-calendar-session "<session-id>"
```

同步企业日历并指定参会人：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --sync-calendar-session "<session-id>" --calendar-attendee "u-demo" --calendar-attendee "manager@example.com"
```

运行一次异步 worker：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-worker-once --worker-limit 50
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-worker-once --worker-auto-recover --worker-recovery-approval-override --worker-limit 50
```

运行多轮 worker loop：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-worker-once --worker-iterations 10 --worker-interval 5
```

worker 会自动处理：

- `APPROVAL_CREATED`：查询审批状态，审批通过后继续锁库存、校验价格、创建订单。
- `APPROVAL_APPROVED`：继续锁库存、校验价格、创建订单。
- `ORDER_CREATED` / `COMPLETED`：刷新订单状态。

worker 不会自动接受价格变化；`PRICE_CHANGED` 必须由用户或策略显式确认。
`--worker-auto-recover` 默认关闭；开启后会扫描 `APPROVAL_REJECTED`、`PRICE_CHANGED`、`INVENTORY_EXPIRED`、`ORDER_FAILED` 等异常状态，并通过恢复策略 gate 执行状态刷新、重规划或补偿后重规划。涉及 critical/补偿路径时仍会被 gate 阻断，除非显式传入 `--worker-recovery-approval-override`。

查看最近 worker 运行历史：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-worker-runs
```

查看通知死信：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-dead-letters
```

查看日历同步死信：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-calendar-dead-letters
```

重放指定通知死信：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-dead-letter-session "<session-id>" --replay-dead-letter-event "ORDER_COMPLETED"
```

重放指定日历同步死信：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-calendar-dead-letter-session "<session-id>" --replay-calendar-dead-letter-event "TRIP_BOOKED"
```

输出基础运行指标：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --metrics
```

输出 Prometheus 文本指标：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --metrics --metrics-format prometheus
```

启动 Prometheus 拉取端点：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --serve-metrics --metrics-host 127.0.0.1 --metrics-port 9108
```

启动后可访问 `http://127.0.0.1:9108/metrics` 和 `http://127.0.0.1:9108/health`。

导出 OpenTelemetry Collector OTLP/HTTP traces 和 metrics：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --export-otlp --otlp-endpoint "http://localhost:4318"
```

也可以只打印生成的 OTLP payload 便于调试：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --export-otlp --print-otlp-payload
```

异常恢复：对停在 `APPROVAL_REJECTED`、`PRICE_CHANGED`、`INVENTORY_EXPIRED`、`ORDER_FAILED` 等状态的会话执行补偿并重新查询酒店。

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replan-session "<session-id>" --replan-reason "operator_replan"
```

恢复后重新选择酒店并创建新一轮审批：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --reselect-hotel-session "<session-id>" --hotel-id "SHA-002"
```

每次重规划都会递增 `workflow_generation`。审批、库存、订单和通知的幂等键都会带上轮次，避免新一轮流程命中上一轮审批单或通知去重记录。

通知会在以下状态触发，并通过 `notification_keys` 去重：

- `COMPLETED`：订单已创建
- `PRICE_CHANGED`：价格变化待确认
- `APPROVAL_REJECTED`：审批驳回
- `INVENTORY_EXPIRED`：库存失效
- `ORDER_FAILED`：订单失败
- `USER_CANCELLED`：流程取消

## 接入真实系统

默认不需要外部系统，Agent 会使用 mock 数据。真实差旅政策、酒店库存、OA 审批系统就绪后，可以用环境变量接入 HTTP JSON 接口：

```powershell
$env:TRAVEL_POLICY_API_URL = "https://policy.example.com/api/check"
$env:TRAVEL_TRANSPORT_POLICY_API_URL = "https://policy.example.com/api/transport-check"
$env:TRAVEL_HOTEL_INVENTORY_API_URL = "https://hotel.example.com/api/search"
$env:TRAVEL_TRANSPORT_INVENTORY_API_URL = "https://transport.example.com/api/search"
$env:TRAVEL_HOTEL_PRICE_CHECK_API_URL = "https://hotel.example.com/api/price-check"
$env:TRAVEL_HOTEL_INVENTORY_LOCK_API_URL = "https://hotel.example.com/api/lock"
$env:TRAVEL_HOTEL_INVENTORY_RELEASE_API_URL = "https://hotel.example.com/api/release"
$env:TRAVEL_OA_APPROVAL_API_URL = "https://oa.example.com/api/approvals"
$env:TRAVEL_OA_APPROVAL_STATUS_API_URL = "https://oa.example.com/api/approvals/status"
$env:TRAVEL_OA_APPROVAL_CANCEL_API_URL = "https://oa.example.com/api/approvals/cancel"
$env:TRAVEL_ORDER_API_URL = "https://order.example.com/api/orders"
$env:TRAVEL_ORDER_STATUS_API_URL = "https://order.example.com/api/orders/status"
$env:TRAVEL_ORDER_CANCEL_API_URL = "https://order.example.com/api/orders/cancel"
$env:TRAVEL_REFUND_ESTIMATE_API_URL = "https://order.example.com/api/refund-estimate"
$env:TRAVEL_REFUND_CONFIRM_API_URL = "https://order.example.com/api/refund-confirm"
$env:TRAVEL_CHANGE_APPROVAL_API_URL = "https://oa.example.com/api/change-approvals"
$env:TRAVEL_CHANGE_FAILURE_COMPENSATION_API_URL = "https://order.example.com/api/change-failure-compensation"
$env:TRAVEL_HOTEL_CHANGE_API_URL = "https://order.example.com/api/hotel-change"
$env:TRAVEL_TRANSPORT_ORDER_API_URL = "https://transport.example.com/api/orders"
$env:TRAVEL_TRANSPORT_ORDER_STATUS_API_URL = "https://transport.example.com/api/orders/status"
$env:TRAVEL_TRANSPORT_ORDER_CANCEL_API_URL = "https://transport.example.com/api/orders/cancel"
$env:TRAVEL_TRANSPORT_CHANGE_API_URL = "https://transport.example.com/api/change"
$env:TRAVEL_NOTIFICATION_API_URL = "https://notify.example.com/api/messages"
$env:TRAVEL_CALENDAR_API_URL = "https://calendar.example.com/api/sync"
$env:TRAVEL_OTLP_HTTP_ENDPOINT = "http://localhost:4318"
$env:TRAVEL_POLICY_API_TOKEN = "policy-token"
$env:TRAVEL_TRANSPORT_API_TOKEN = "transport-token"
$env:TRAVEL_HOTEL_INVENTORY_API_TOKEN = "hotel-token"
$env:TRAVEL_OA_APPROVAL_API_TOKEN = "oa-token"
$env:TRAVEL_ORDER_API_TOKEN = "order-token"
$env:TRAVEL_NOTIFICATION_API_TOKEN = "notification-token"
$env:TRAVEL_CALENDAR_API_TOKEN = "calendar-token"
$env:TRAVEL_OTLP_API_TOKEN = "otel-token"
$env:TRAVEL_NOTIFICATION_USE_MOCK_FALLBACK = "true"
$env:TRAVEL_CALENDAR_USE_MOCK_FALLBACK = "true"
$env:TRAVEL_SESSION_STORE_BACKEND = "auto"
$env:TRAVEL_SESSION_DB_PATH = "D:\tmp\travel-agent.sqlite3"
$env:TRAVEL_SESSION_STORE_API_URL = "https://store.example.com/api/travel-agent"
$env:TRAVEL_SESSION_STORE_API_TOKEN = "store-token"
```

默认 `TRAVEL_USE_MOCK_FALLBACK=true`。真实接口未配置或调用失败时，会降级到 mock 数据，并在返回结果里标记 `source=mock_fallback`。如果希望真实系统异常时直接失败：

```powershell
$env:TRAVEL_USE_MOCK_FALLBACK = "false"
```

通知可单独关闭 mock fallback，用于验证重试/死信路径：

```powershell
$env:TRAVEL_NOTIFICATION_USE_MOCK_FALLBACK = "false"
```

会话存储支持三种后端：

- `auto`：优先使用 `TRAVEL_SESSION_STORE_API_URL`，其次使用 `TRAVEL_SESSION_DB_PATH`，都未配置时使用内存。
- `sqlite`：使用 `TRAVEL_SESSION_DB_PATH` 或 CLI `--session-db`。
- `http`：使用 `TRAVEL_SESSION_STORE_API_URL` 和可选 `TRAVEL_SESSION_STORE_API_TOKEN`，用于对接外部数据库服务或工作流引擎。

接口期望：

- 政策接口：POST JSON，返回 `policy` 或 `data`，字段支持 `policy_id`、`max_hotel_price`、`approved_budget`、`compliant`、`reasons`。
- 交通政策接口：POST JSON，返回 `transport_policy` 或 `data`，字段支持 `policy_id`、`allowed_seat_classes`、`max_transport_price`、`compliant`、`reasons`。
- 酒店接口：POST JSON，返回 `hotels`、`data.hotels`、`data.items` 或 `data.records` 列表，字段支持 `hotel_id`、`name`、`city`、`address`、`nightly_price`、`distance_km`、`rating`、`refundable`。
- 交通查询接口：POST JSON，返回 `transports`、`data.transports`、`data.items` 或 `data.records` 列表，字段支持 `transport_id`、`mode`、`provider`、`origin_city`、`destination_city`、`depart_at`、`arrive_at`、`seat_class`、`price`、`refundable`。
- OA 接口：POST JSON，返回 `approval` 或 `data`，字段支持 `approval_id`、`status`。
- OA 状态接口：POST JSON，返回 `approval` 或 `data`，字段支持 `approval_id`、`status`。`APPROVED` 会进入下单，`REJECTED` 会停止流程。
- OA 撤回接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 酒店库存锁定接口：POST JSON，返回 `inventory_lock` 或 `data`，字段支持 `lock_id`、`status`、`hotel_id`、`expires_at`。
- 酒店价格校验接口：POST JSON，返回 `price_check` 或 `data`，字段支持 `hotel_id`、`status`、`original_price`、`current_price`、`policy_compliant`、`requires_confirmation`。
- 订单接口：POST JSON，返回 `order` 或 `data`，字段支持 `order_id`、`status`、`total_amount`、`currency`。
- 订单状态接口：POST JSON，返回 `order` 或 `data`，字段支持 `order_id`、`status`、`total_amount`、`currency`。
- 订单取消接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 交通订单接口：POST JSON，返回 `transport_order` 或 `data`，字段支持 `order_id`、`status`、`total_amount`、`currency`。
- 交通订单状态接口：POST JSON，返回 `transport_order` 或 `data`，字段支持 `order_id`、`status`、`total_amount`、`currency`。
- 交通订单取消接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 退款预估接口：POST JSON，返回 `refund_estimate` 或 `data`，字段支持 `estimate_id`、`target_type`、`target_id`、`refundable_amount`、`penalty_amount`、`currency`、`rules`。
- 退款确认接口：POST JSON，返回 `refund_confirmation` 或 `data`，字段支持 `confirmation_id`、`estimate_id`、`target_type`、`target_id`、`status`、`confirmed_amount`、`currency`。
- 改签审批接口：POST JSON，返回 `approval` 或 `data`，字段支持 `approval_id`、`status`。
- 酒店改期接口：POST JSON，返回 `change` 或 `data`，字段支持 `change_id`、`target_type`、`target_id`、`status`、`penalty_amount`、`currency`。
- 交通改签接口：POST JSON，返回 `change` 或 `data`，字段支持 `change_id`、`target_type`、`target_id`、`status`、`penalty_amount`、`currency`。
- 改签失败补偿接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 库存释放接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 通知接口：POST JSON，返回 `notification` 或 `data`，字段支持 `notification_id`、`event_type`、`channel`、`recipient_id`、`title`、`message`、`status`。
- 日历同步接口：POST JSON，返回 `calendar` 或 `data`，字段支持 `calendar_event_id`、`event_type`、`status`、`user_id`、`title`、`start_at`、`end_at`、`attendees`、`retry_count`、`max_retries`、`last_error`。
- HTTP 会话存储接口：POST JSON，路径包括 `/sessions/save`、`/sessions/save-if-version`、`/sessions/get`、`/sessions/list-by-states`、`/sessions/list-recent`、`/worker-runs/record`、`/worker-runs/list`、`/health`。会话保存请求包含 `session_id`、`state`、`payload`，乐观并发保存额外包含 `expected_version`，健康检查返回 `backend`、`ok`、`schema_version`、`session_count`、`worker_run_count` 和 `details`。

## 运行测试

```powershell
python -m unittest discover -s tests
```

## 运行评测集

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --run-evaluation-suite
```

评测集会输出每个场景的状态、断言和失败原因，可作为接入真实政策、库存、审批、订单、日历系统前的回归基线。

## 运行联调验收报告

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --run-integration-acceptance
```

如只需要快速检查配置，不运行内置评测集：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --run-integration-acceptance --skip-acceptance-evaluation
```

验收报告会输出 `PASS`、`ACTION_REQUIRED` 或 `FAIL`。`ACTION_REQUIRED` 表示仍有真实端点缺失、mock fallback 未关闭或持久化存储未配置；`FAIL` 表示评测集失败或存储健康检查失败。

## 运行 Smoke 探活

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --run-smoke-probes
```

如不探测可选端点，例如外部 HTTP 会话存储 `/health`：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --run-smoke-probes --skip-optional-smoke-probes
```

Smoke 探活只会调用已配置的真实端点；未配置的端点会显示 `SKIP`。每个请求都会携带 `smoke_test=true`、`dry_run=true` 和稳定的 `idempotency_key`，真实系统需保证该类请求不创建真实审批、订单、通知或日历事件。

## 运行发布准入检查

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --release-readiness
```

发布准入也可以纳入联调验收和 smoke 探活结果：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --release-readiness --include-acceptance --include-smoke-probes
```

发布准入会检查 mock fallback 是否关闭、是否配置持久化存储、已配置真实端点是否有对应 token、审计与观测能力是否存在，以及可选的验收/smoke 结果。

CI/CD 阶段可以使用发布 gate，状态不是 `PASS` 时返回非零退出码：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --release-gate --include-acceptance --include-smoke-probes
```

`--allow-action-required` 可用于预发环境，让 `ACTION_REQUIRED` 状态临时通过；生产流水线不建议开启。

## 运行灰度决策

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --rollout-decision --rollout-user u-demo
```

可以通过环境变量控制放量和回滚：

```powershell
$env:TRAVEL_ROLLOUT_ENABLED = "true"
$env:TRAVEL_ROLLOUT_PERCENTAGE = "10"
$env:TRAVEL_ROLLOUT_ALLOWED_USERS = "u-demo"
$env:TRAVEL_ROLLBACK_ENABLED = "false"
```

灰度决策会输出用户是否命中当前放量、所在 bucket，以及命中原因。回滚开启时会直接阻断发布。

## 运行权限检查

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --permission-check --permission-user u-demo --permission-action plan_trip --permission-role traveler
```

可以通过环境变量启用本地权限门禁：

```powershell
$env:TRAVEL_PERMISSION_ENABLED = "true"
$env:TRAVEL_PERMISSION_REQUIRED_ROLES = "traveler"
$env:TRAVEL_PERMISSION_ALLOWED_DEPARTMENTS = "sales,consulting"
$env:TRAVEL_PERMISSION_BLOCKED_ACTIONS = ""
```

权限检查会输出是否放行、是否启用强制校验、动作、用户、部门、角色和命中原因。启用后，Agent 在规划、审批、下单、改签、取消、日历同步和死信重放等关键动作前都会执行同一套策略。

如果企业用户中心或 IAM 已就绪，也可以接入外部权限服务：

```powershell
$env:TRAVEL_PERMISSION_API_URL = "https://iam.example.com/api/check"
$env:TRAVEL_PERMISSION_API_TOKEN = "iam-token"
```

审计日志外部落库支持 HTTP sink：

```powershell
$env:TRAVEL_AUDIT_LOG_API_URL = "https://audit.example.com/api/events"
$env:TRAVEL_AUDIT_LOG_API_TOKEN = "audit-token"
```

## 生产运行与事故演练

输出生产运行手册：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --operations-runbook
```

运行事故演练：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --operations-drill
```

演练会汇总 release readiness、SLO 告警和四类场景结果：权限中心不可用、审计 sink 不可用、供应商订单失败和回滚开关触发。没有真实系统或持久化存储时，会使用 mock 信号完成演练；配置 SQLite/HTTP session store 后，会额外读取 worker run、通知死信、日历死信和最近会话。

输出 operations 告警：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --operations-alerts
python -m travel_agent.cli --operations-alerts --operations-alert-format prometheus
python -m travel_agent.cli --operations-alerts --operations-alert-format json
```

推送到企业告警平台或值班系统：

```powershell
$env:TRAVEL_ALERT_API_URL = "https://alerts.example.com/api/events"
$env:TRAVEL_ALERT_API_TOKEN = "alert-token"
$env:PYTHONPATH = "src"
python -m travel_agent.cli --export-operations-alerts
```

演练可作为 CI/CD gate 使用，出现 `FAIL` 或未允许的 `WARN` 时返回非零退出码：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --operations-drill-gate
```

输出生产运行看板：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --operations-dashboard
```

持久化并查询看板快照：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --save-operations-dashboard
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-operations-dashboard-snapshots
```

基于持久化运营数据生成趋势、多维视图和事故复盘：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-dashboard-trend --dashboard-trend-window 7
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-trend-alerts --persist-trend-alerts --create-trend-action-items
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-multidim-view --multidim-limit 5
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-postmortem --create-postmortem-action-items --save-operations-knowledge
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-operations-action-items
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-operations-knowledge
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --search-operations-knowledge "critical alerts"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-action-sla
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-action-sla --notify-action-sla --action-sla-channel im
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-report
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-report --operations-closed-loop-format json
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-report --operations-closed-loop-format prometheus
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-recovery-metrics --operations-recovery-metrics-format prometheus
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --export-recovery-approval-receipts --recovery-approval-endpoint "https://audit.example.com/recovery-approvals"
python -m travel_agent.cli --fetch-recovery-governance-policy --recovery-governance-policy-endpoint "https://config.example.com/recovery-governance"
python -m travel_agent.cli --fetch-recovery-governance-policy --audit-recovery-governance-policy --recovery-governance-policy-endpoint "https://config.example.com/recovery-governance"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --recovery-approval-sla --recovery-approval-sla-policy-json '{"max_pending_hours":12,"allowed_approvers":["ops-lead"]}'
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-report --save-operations-closed-loop --closed-loop-snapshot-department finance --closed-loop-snapshot-tenant corp-a
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-operations-closed-loop-snapshots
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-dashboard --closed-loop-dashboard-limit 10 --closed-loop-dashboard-owner ops
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-dashboard --closed-loop-dashboard-cursor "2026-05-20T03:10:00+00:00" --closed-loop-dashboard-department finance --closed-loop-dashboard-tenant corp-a
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-dashboard --closed-loop-dashboard-checkpoint "2026-05-20T03:10:00+00:00"
python -m travel_agent.cli --operations-closed-loop-contract schema
python -m travel_agent.cli --operations-closed-loop-contract openapi --closed-loop-contract-server-url "https://ops.example.com"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-contract validate --closed-loop-dashboard-department finance --closed-loop-dashboard-tenant corp-a
python -m travel_agent.cli --publish-operations-closed-loop-contract --closed-loop-schema-registry-endpoint "https://schema.example.com/registry"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-quality
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-checkpoint-plan
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-acceptance
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-report --export-operations-closed-loop --closed-loop-endpoint "https://bi.example.com/travel/closed-loop"
python -m travel_agent.cli --operations-authorize-action view_operations_console --operations-actor ops --operations-actor-role ops
python -m travel_agent.cli --operations-schedule-plan
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --init-operations-schedule
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-operations-schedule
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-operations-schedule --operations-actor ops --operations-actor-role ops
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-persisted-operations-schedule --operations-scheduler-owner worker-a --operations-scheduler-lease-seconds 300
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-scheduler-health
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --execute-oncall-webhook-replay-jobs --operations-actor ops --operations-actor-role ops
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-console-overview
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-compensation-observability
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-compensation-slo
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-compensation-slo --export-operations-compensation-slo-alerts --operations-alert-endpoint "https://alerts.example.com/api/events"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-compensation-slo --open-operations-compensation-slo-ticket --oncall-endpoint "https://oncall.example.com/api/tickets"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-compensation-remediation --operations-actor ops --operations-actor-role ops
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --serve-operations-dashboard --operations-dashboard-host 127.0.0.1 --operations-dashboard-port 9110 --operations-dashboard-token "read-token"
```

`TRAVEL_TREND_ALERT_RULES_JSON` 可覆盖默认趋势阈值规则，格式为 `{"rules":[{"metric":"critical_alerts","severity":"critical","route":"ops","owner":"ops","delta_threshold":1}]}`。
`TRAVEL_ACTION_SLA_POLICY_JSON` 可覆盖行动项 SLA 阈值和 owner 路由，格式为 `{"warning_after_hours":12,"critical_after_hours":24,"owner_routes":{"platform-oncall":"incident-oncall"}}`。
`TRAVEL_CLOSED_LOOP_API_URL` / `TRAVEL_CLOSED_LOOP_API_TOKEN` 可配置闭环报表 HTTP sink。持久化知识库存在命中时，`TravelAgent.plan()` 会自动将知识条目和推荐动作写入任务计划，CLI 输出中会展示“规划知识”；`replan_after_exception()` 会将恢复策略决策和策略 gate 写入 `RecoveryRecord.payload`，`execute_recovery_strategy()` 会额外写入 `strategy_execution` 执行结果，包含 `idempotency_key` 和可选 `approval_receipt`。
`TRAVEL_RECOVERY_APPROVAL_API_URL` / `TRAVEL_RECOVERY_APPROVAL_API_TOKEN` 可配置恢复审批回执外发端点；`TRAVEL_RECOVERY_GOVERNANCE_POLICY_JSON` 可配置本地恢复策略治理规则，`TRAVEL_RECOVERY_GOVERNANCE_POLICY_API_URL` / `TRAVEL_RECOVERY_GOVERNANCE_POLICY_API_TOKEN` 可配置远端配置中心，例如 `{"allowed_actions":["retry_status_refresh","replan"],"max_executions_per_session":2}`。`--recovery-approval-sla` 可评估审批回执超时和审批人 allowlist/prefix，`--audit-recovery-governance-policy` 可输出策略变更审计。`--open-recovery-failure-ticket-session` 会把最近一次失败/阻断的恢复执行作为 OnCall payload 推送。
`TRAVEL_CLOSED_LOOP_SCHEMA_REGISTRY_URL` / `TRAVEL_CLOSED_LOOP_SCHEMA_REGISTRY_API_TOKEN` 可配置闭环 schema registry。`--publish-operations-closed-loop-contract` 会发布 JSON Schema、OpenAPI 和兼容矩阵，`--operations-closed-loop-quality`、`--operations-closed-loop-checkpoint-plan` 和 `--operations-closed-loop-acceptance` 可用于 BI 契约 CI 或外部消费验收。
`TRAVEL_COMPENSATION_SLO_POLICY_JSON` 可覆盖补偿执行 SLO 阈值、burn rate、失败/重试/人工介入/调度失败阈值和 route/escalation；`--operations-compensation-slo-policy-json` 或控制台调度 payload 的 `compensation_slo_policy` / `compensation_slo_policy_json` 可临时覆盖。`TRAVEL_COMPENSATION_REMEDIATION_POLICY_JSON` 可覆盖补偿自动处置策略，支持 `enabled`、`create_action_items`、`controlled_retry_enabled`、`max_retry_tasks`、`retry_statuses`、`retry_severities`、`action_owner`、`action_eta`、`runbook_owner` 和 `dry_run`；`--operations-compensation-remediation-policy-json` 或控制台 payload 的 `compensation_remediation_policy` / `compensation_remediation_policy_json` 可临时覆盖。
`--operations-authorize-action` 会按 `--operations-actor`、`--operations-actor-role` 和 `--operations-actor-department` 执行运维动作权限决策，并在配置 `TRAVEL_AUDIT_LOG_API_URL` 后写入脱敏审计。`--operations-schedule-plan` 输出默认周期任务，`--run-operations-schedule` 执行一次内存态 due tasks；`--init-operations-schedule` 会将默认 schedule plan 落库，`--run-persisted-operations-schedule` 会按 `--operations-scheduler-owner` claim due tasks，执行成功或失败后释放租约并推进下次运行/重试时间，同时记录 scheduler run history；`--operations-scheduler-health` 会输出失败 run、过期租约、长期未运行任务和连续失败任务告警。`--execute-oncall-webhook-replay-jobs` 可单独执行 pending replay job 并写回事件、工单状态和 job 结果。
`--serve-operations-dashboard` 会暴露 `/health`、`/metrics`、`/operations/closed-loop`、`/operations/closed-loop/snapshots`、`/operations/oncall-webhook-ops`、`/operations/oncall-webhook-replay-jobs`、`/operations/console`、`/operations/console/view`、`/operations/console/ui`、`/operations/console/actions`、`/operations/console/audit-timeline`、`/operations/console/audit-sink-deliveries`、`/operations/console/compensation-tasks`、`/operations/console/compensation-observability`、`/operations/console/compensation-slo` 和 `/operations/console/compensation-remediation`，闭环看板 JSON 中包含 `travel.operations.closed_loop.v1` schema 版本、最新 snapshot、趋势指标、过滤条件、摘要、`limit`、`cursor`、`next_cursor`、`checkpoint` 和 `has_more`；`/operations/console` 聚合 closed-loop dashboard、webhook ops、replay job、质量门禁和验收摘要；`/operations/console/view` 和 `/operations/console/ui` 会读取 `X-Operations-Actor`、`X-Operations-Roles`、`X-Operations-Department` 生成 RBAC-aware JSON/HTML 控制台；`/operations/console/actions` 支持 `create_replay_job`、`execute_replay_jobs`、`run_operations_schedule`、`publish_closed_loop_schema`、`propose_governance_policy_change`、`approve_governance_policy_change`、`rollback_governance_policy_change`、`retry_audit_sink_deliveries`、`close_compensation_task`、`execute_compensation_tasks` 和 `remediate_compensation_slo`，可用 JSON payload 传入 `limit`、`requested_by`、`patch_template_id`、`patches`、`persisted`、`owner`、`endpoint`、`oncall_endpoint`、`token`、`server_url`、`before`、`after`、`change_id`、`approved_by`、`task_id`、`closure_note`、`compensation_execution_policy`、`compensation_execution_policy_json`、`compensation_slo_policy` 或 `compensation_slo_policy_json` 等参数，并为每次 action 持久化 actor、roles、RBAC authorization、请求摘要、结果摘要和可选 audit sink 投递状态；`execute_compensation_tasks` 会返回 `compensation_task_execution` 报告并写回补偿任务状态和可选 OnCall ticket status，策略也可通过 `TRAVEL_COMPENSATION_EXECUTION_POLICY_JSON` 配置；`/operations/console/audit-timeline` 会聚合 action audit、治理策略变更、replay job 和 scheduler run，支持 `?event_type=<type>&actor=<actor>&action=<action>&status=<status>&limit=20` 查询；`/operations/console/audit-sink-deliveries` 会查询外部审计 sink 投递记录；`/operations/console/compensation-tasks` 会聚合补偿任务生命周期，支持 `?owner=<owner>&status=<status>&source_type=<source_type>&limit=20` 查询；`/operations/console/compensation-observability` 会基于补偿任务 lifecycle、scheduler run 和 console action audit 输出补偿执行成功率、失败原因、gate 分布、重试等待和人工介入指标；`/operations/console/compensation-slo` 会基于补偿观测报表输出 SLO burn rate、error budget、告警列表和 route/escalation；`/operations/console/compensation-remediation` 会以 dry-run 方式预览行动项、受控重试候选和 runbook 执行记录，`remediate_compensation_slo` action 会按策略落库行动项并触发受控重试。可通过 `--operations-dashboard-token` 或 `TRAVEL_OPERATIONS_DASHBOARD_TOKEN` 开启 token，并用 `?owner=<owner>&since=<iso>&cursor=<iso>&department=<department>&tenant=<tenant>&checkpoint=<iso>&limit=10` 进行增量分页查询。

输出告警路由、升级和静默规则模板：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --alert-rules
python -m travel_agent.cli --alert-rules --alert-rules-format json
```

也可以通过 `TRAVEL_ALERT_RULES_JSON` 覆盖默认规则：

```powershell
$env:TRAVEL_ALERT_RULES_JSON = '{"rules":[{"alert_type":"order_failed","severity":"critical","route":"booking-oncall","escalation":"page","silence_hint":"incident owner approval"}]}'
```

创建 OnCall/工单事件：

```powershell
$env:TRAVEL_ONCALL_API_URL = "https://oncall.example.com/api/tickets"
$env:TRAVEL_ONCALL_API_TOKEN = "oncall-token"
$env:PYTHONPATH = "src"
python -m travel_agent.cli --open-oncall-ticket
```

同步并查询工单状态：

```powershell
$env:TRAVEL_ONCALL_STATUS_API_URL = "https://oncall.example.com/api/ticket-status"
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --sync-oncall-ticket "INC-1"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --sync-action-items-from-oncall
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-oncall-ticket-statuses
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --record-oncall-webhook-json '{"data":{"ticket_id":"INC-1","status":"CLOSED","assignee":"ops","updated_at":"2026-05-21T10:00:00+08:00","detail":"resolved by webhook"}}' --sync-action-items-from-webhook
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --record-oncall-webhook-file ".\webhook-payload.json" --oncall-webhook-signature "sha256=<digest>" --oncall-webhook-secret "secret" --sync-action-items-from-webhook
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-oncall-webhook-events
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-oncall-webhook-dead-letters
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --oncall-webhook-ops-console --oncall-webhook-ops-format json
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --create-oncall-webhook-replay-job --oncall-webhook-replay-requested-by ops
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-oncall-webhook-event "WHK-1" --sync-action-items-from-webhook
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-oncall-webhook-dead-letters --oncall-webhook-replay-limit 20 --oncall-webhook-patch-file ".\webhook-patch.json" --sync-action-items-from-webhook --oncall-webhook-replay-audit-json --persist-oncall-webhook-replay-job
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-oncall-webhook-replay-jobs --oncall-webhook-replay-jobs-format json
```

## 存储健康检查

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --storage-health
```

健康检查会输出当前持久化后端、schema 版本、会话数、worker run 数和后端详情。SQLite 会包含 `PRAGMA integrity_check` 和 journal mode；HTTP 后端会调用 `/health`。

## 下一阶段建议

- 补偿处置效果评估与知识反馈：评估自动处置命中率、受控重试成功率和行动项闭环效果，并将高价值处置经验沉淀到运营知识库。
