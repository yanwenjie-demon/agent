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
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --operations-closed-loop-report
```

`TRAVEL_TREND_ALERT_RULES_JSON` 可覆盖默认趋势阈值规则，格式为 `{"rules":[{"metric":"critical_alerts","severity":"critical","route":"ops","owner":"ops","delta_threshold":1}]}`。
`TRAVEL_ACTION_SLA_POLICY_JSON` 可覆盖行动项 SLA 阈值和 owner 路由，格式为 `{"warning_after_hours":12,"critical_after_hours":24,"owner_routes":{"platform-oncall":"incident-oncall"}}`。

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
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-oncall-ticket-statuses
```

## 存储健康检查

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --storage-health
```

健康检查会输出当前持久化后端、schema 版本、会话数、worker run 数和后端详情。SQLite 会包含 `PRAGMA integrity_check` 和 journal mode；HTTP 后端会调用 `/health`。

## 下一阶段建议

- 知识检索接入 Agent 规划：让历史复盘和处置知识参与行程规划、异常恢复和告警解释。
- SLA 自动通知联动：将行动项超时升级推送到通知、OnCall 或企业工单系统。
- 闭环指标外部导出：将闭环报表输出为 Prometheus/JSON/HTTP sink，接入 BI 或运营大盘。
