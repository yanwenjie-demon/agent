# 差旅 Agent

本仓库包含差旅 AI Agent 的架构设计文档，以及单 Agent 到真实系统接入的阶段性实现。

## 当前能力

- 单 Agent 任务规划
- Tool Gateway 工具注册、参数校验、调用审计
- 差旅政策校验，支持真实 HTTP 系统和 Mock fallback
- 行程规划 Mock 工具
- 酒店库存查询与推荐，支持真实 HTTP 系统和 Mock fallback
- 用户确认后创建 OA 审批记录，支持真实 HTTP 系统和 Mock fallback
- 审批状态跟踪，审批通过后锁定酒店库存并创建订单
- 取消补偿：取消订单、释放酒店库存
- 价格变化二次确认：锁库存后、下单前校验当前价
- 订单状态刷新：订单创建后可同步最新订单状态
- 异步 worker：扫描持久化会话，自动推进审批和订单状态
- 通知/待办回调：关键成功、失败、待确认状态自动发送通知，支持真实 HTTP 系统和 Mock fallback
- 通知重试/死信：通知失败不会阻断主流程，超过重试上限后进入 `DEAD_LETTER`
- 生产化观测：worker 运行摘要落库、死信查询/重放、基础指标输出
- SQLite 会话持久化，可从 session 恢复流程
- 内存会话状态和确定性工作流状态机

架构说明见 [docs/travel-agent-architecture.md](docs/travel-agent-architecture.md)。

## 运行演示

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-confirm
```

不加 `--auto-confirm` 时，CLI 只生成差旅方案和酒店推荐，不会创建审批草稿。

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

重放指定通知死信：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-dead-letter-session "<session-id>" --replay-dead-letter-event "ORDER_COMPLETED"
```

输出基础运行指标：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --metrics
```

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
$env:TRAVEL_HOTEL_INVENTORY_API_URL = "https://hotel.example.com/api/search"
$env:TRAVEL_HOTEL_PRICE_CHECK_API_URL = "https://hotel.example.com/api/price-check"
$env:TRAVEL_HOTEL_INVENTORY_LOCK_API_URL = "https://hotel.example.com/api/lock"
$env:TRAVEL_HOTEL_INVENTORY_RELEASE_API_URL = "https://hotel.example.com/api/release"
$env:TRAVEL_OA_APPROVAL_API_URL = "https://oa.example.com/api/approvals"
$env:TRAVEL_OA_APPROVAL_STATUS_API_URL = "https://oa.example.com/api/approvals/status"
$env:TRAVEL_ORDER_API_URL = "https://order.example.com/api/orders"
$env:TRAVEL_ORDER_STATUS_API_URL = "https://order.example.com/api/orders/status"
$env:TRAVEL_ORDER_CANCEL_API_URL = "https://order.example.com/api/orders/cancel"
$env:TRAVEL_NOTIFICATION_API_URL = "https://notify.example.com/api/messages"
$env:TRAVEL_POLICY_API_TOKEN = "policy-token"
$env:TRAVEL_HOTEL_INVENTORY_API_TOKEN = "hotel-token"
$env:TRAVEL_OA_APPROVAL_API_TOKEN = "oa-token"
$env:TRAVEL_ORDER_API_TOKEN = "order-token"
$env:TRAVEL_NOTIFICATION_API_TOKEN = "notification-token"
$env:TRAVEL_NOTIFICATION_USE_MOCK_FALLBACK = "true"
$env:TRAVEL_SESSION_DB_PATH = "D:\tmp\travel-agent.sqlite3"
```

默认 `TRAVEL_USE_MOCK_FALLBACK=true`。真实接口未配置或调用失败时，会降级到 mock 数据，并在返回结果里标记 `source=mock_fallback`。如果希望真实系统异常时直接失败：

```powershell
$env:TRAVEL_USE_MOCK_FALLBACK = "false"
```

通知可单独关闭 mock fallback，用于验证重试/死信路径：

```powershell
$env:TRAVEL_NOTIFICATION_USE_MOCK_FALLBACK = "false"
```

接口期望：

- 政策接口：POST JSON，返回 `policy` 或 `data`，字段支持 `policy_id`、`max_hotel_price`、`approved_budget`、`compliant`、`reasons`。
- 酒店接口：POST JSON，返回 `hotels`、`data.hotels`、`data.items` 或 `data.records` 列表，字段支持 `hotel_id`、`name`、`city`、`address`、`nightly_price`、`distance_km`、`rating`、`refundable`。
- OA 接口：POST JSON，返回 `approval` 或 `data`，字段支持 `approval_id`、`status`。
- OA 状态接口：POST JSON，返回 `approval` 或 `data`，字段支持 `approval_id`、`status`。`APPROVED` 会进入下单，`REJECTED` 会停止流程。
- 酒店库存锁定接口：POST JSON，返回 `inventory_lock` 或 `data`，字段支持 `lock_id`、`status`、`hotel_id`、`expires_at`。
- 酒店价格校验接口：POST JSON，返回 `price_check` 或 `data`，字段支持 `hotel_id`、`status`、`original_price`、`current_price`、`policy_compliant`、`requires_confirmation`。
- 订单接口：POST JSON，返回 `order` 或 `data`，字段支持 `order_id`、`status`、`total_amount`、`currency`。
- 订单状态接口：POST JSON，返回 `order` 或 `data`，字段支持 `order_id`、`status`、`total_amount`、`currency`。
- 订单取消接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 库存释放接口：POST JSON，返回 `compensation` 或 `data`，字段支持 `action`、`target_id`、`status`。
- 通知接口：POST JSON，返回 `notification` 或 `data`，字段支持 `notification_id`、`event_type`、`channel`、`recipient_id`、`title`、`message`、`status`。

## 运行测试

```powershell
python -m unittest discover -s tests
```

## 下一阶段建议

- 将 SQLite 会话存储替换为生产数据库或工作流引擎
- 增加审批撤回、改签/退订、重新选酒店等异常恢复工作流
- 将 CLI 指标升级为 Prometheus/OpenTelemetry 指标出口
- 增加评测集，覆盖工具调用准确率、政策合规率、流程成功率
