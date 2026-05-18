# 差旅 AI Agent 架构设计

## 1. 目标

面向企业差旅场景，Agent 需要从自然语言请求出发，完成需求理解、任务拆解、工具调用、流程编排和关键节点确认。

核心目标：

- 理解差旅意图：出发地、目的地、时间、预算、会场、同行人、偏好。
- 自动规划任务：查政策、查酒店、规划行程、创建审批单、创建订单。
- 调用业务工具：酒店、机票/火车票、差旅政策、OA 审批、订单、支付、日历、消息通知。
- 编排复杂流程：审批前置、预算校验、库存锁定、订单确认、异常补偿。
- 支持人机协同：价格变化、库存变化、审批提交、订单支付等关键节点需要用户确认或策略授权。

## 2. 总体架构

```text
用户入口
  ├─ 企业 IM
  ├─ App / Web
  └─ 语音入口
      ↓
Agent Runtime
  ├─ Intent Parser：意图识别与参数抽取
  ├─ Planner：任务规划与依赖拆解
  ├─ Executor：任务执行
  ├─ Tool Gateway：工具路由、鉴权、审计、幂等
  ├─ Workflow Engine：状态机与复杂流程编排
  ├─ Workflow Worker：扫描持久化会话并推进可自动执行的状态
  ├─ Observability Store：记录 worker 执行摘要、子 Agent 执行摘要、死信通知、日历同步和基础运行指标
  ├─ Memory：会话、用户偏好、任务状态
  └─ Guardrails：权限、风控、合规、敏感信息保护
      ↓
业务工具层
  ├─ 差旅政策工具
  ├─ 酒店查询工具
  ├─ 交通查询工具
  ├─ 审批单工具
  ├─ 订单工具
  ├─ 支付/结算工具
  ├─ 日历工具
  └─ 通知/待办工具
      ↓
业务系统
  ├─ 差旅平台
  ├─ OA 审批
  ├─ 财务系统
  ├─ 用户中心
  ├─ 企业政策库
  └─ 订单中心
```

设计边界：

- LLM 负责理解、规划、解释和异常协商。
- 业务系统负责确定性执行，例如库存锁定、审批提交、支付、订单创建。
- Agent 不直接访问核心系统，所有业务调用必须经过 Tool Gateway。
- 工作流状态必须持久化，不能只保存在 LLM 上下文中。

## 3. 第一阶段范围

第一阶段采用单 Agent MVP，目标是跑通酒店差旅申请的最小闭环：

```text
用户请求
  ↓
TravelAgent 生成任务计划
  ↓
Policy Tool 校验差旅政策
  ↓
Itinerary Tool 生成行程草案
  ↓
Hotel Tool 查询酒店候选
  ↓
Transport Tool 查询机票/火车票候选
  ↓
用户确认酒店和交通
  ↓
Approval Tool 创建审批记录
  ↓
Approval Status Tool 查询审批状态
  ↓
Transport Order Tool 创建交通订单
  ↓
Hotel Lock Tool 锁定库存
  ↓
Order Tool 创建订单
```

第一阶段包含：

- 单 Agent 编排。
- Tool Gateway 工具注册、参数校验、调用审计。
- 工作流状态机。
- Mock 差旅政策、Mock 酒店库存、Mock 审批草稿。
- CLI 演示入口。
- 基础单元测试。

第二阶段在第一阶段基础上补充真实系统接入层：

- 差旅政策、酒店库存、OA 审批均通过 `TravelSystemIntegrations` 适配。
- 交通政策、交通库存和交通订单通过同一接入层适配，可使用真实 HTTP JSON 或 mock fallback。
- 默认使用 mock 数据，支持真实 HTTP JSON 接口。
- 真实接口未配置或调用失败时，可按配置降级到 mock 数据。
- 返回对象带 `source` 字段，便于审计真实来源和 fallback 来源。
- 审批通过后进入交通订单创建、酒店库存锁定和酒店订单创建，审批驳回则停止下单。
- 下单后支持取消补偿：先取消交通订单和酒店订单，再释放酒店库存。
- 改签/退订深化支持退款预估、改签审批、退款确认、交通改签、酒店改期、供应商失败补偿和改签后日历同步；真实系统未配置时使用 mock fallback。
- 日历同步支持订单完成、改签和取消后的企业日历更新；真实系统未配置时使用 mock fallback，失败后可由 worker 重试并进入独立死信。
- 会话可持久化到 SQLite，后续可替换为生产数据库或工作流引擎。
- 锁库存后、下单前执行价格校验；价格变化时进入二次确认。
- 订单创建后可刷新订单状态，便于后续接入异步轮询。
- `WorkflowWorker` 可扫描持久化会话并自动推进审批状态和订单状态。
- 关键状态可触发通知/待办回调，并通过 `notification_keys` 幂等去重。
- 通知失败不会阻断主流程，会记录失败、重试次数和死信状态。
- worker 每轮执行会落库运行摘要，支持后续排查扫描数、推进数、跳过数和错误会话。
- 子 Agent 每次执行会写入 `AgentExecutionRecord`，记录 Agent 名称、动作、状态、输入/输出引用、说明和时间，形成跨 Agent 审计视图。
- 达到重试上限的通知可查询并人工重放，重放失败后会重新进入可重试队列。
- 异常恢复会通过 `workflow_generation` 开启新一轮流程，避免重新提交时复用上一轮审批、库存、订单和通知幂等键。

第一阶段历史范围曾暂不包含真实库存、真实 OA、订单创建、补偿和多 Agent。当前实现已推进到真实系统适配、酒店 + 交通组合下单、异常恢复、通知死信、多 Agent 协作深化、改签/退订深化、日历同步重试/死信、Prometheus 文本指标出口、HTTP `/metrics` 服务和 OTLP/HTTP 导出；剩余未完成的主线是评测集和生产化存储。

## 4. 单 Agent 架构

```text
TravelAgent
  ├─ SimpleTaskPlanner
  │   └─ 将用户请求拆成 check_policy / check_transport_policy / plan_itinerary / search_hotels / search_transport / create_approval
  ├─ WorkflowStateMachine
  │   └─ 管理 DRAFT → POLICY_CHECKED → PLAN_GENERATED → USER_CONFIRMED → APPROVAL_CREATED
  ├─ ToolGateway
  │   └─ 统一调用业务工具，负责参数校验和审计
  └─ SessionStore
      └─ 保存会话上下文、方案、酒店候选、审批草稿
```

典型状态流：

```text
DRAFT
  ↓
POLICY_CHECKED
  ↓
PLAN_GENERATED
  ↓
USER_CONFIRMED
  ↓
APPROVAL_CREATED
```

异常状态预留：

```text
APPROVAL_REJECTED
PRICE_CHANGED
INVENTORY_EXPIRED
ORDER_FAILED
USER_CANCELLED
```

## 5. 多 Agent 演进架构

当场景扩展到交通、酒店、审批、订单、改签、退订等完整链路后，建议演进为中心编排式多 Agent。

```text
Orchestrator Agent
  ├─ Intent Agent：理解用户需求和缺失参数
  ├─ Policy Agent：差旅政策、预算、权限校验
  ├─ Trip Planning Agent：行程规划
  ├─ Hotel Agent：酒店查询与推荐
  ├─ Transport Agent：机票/火车票查询与推荐
  ├─ Approval Agent：审批单创建与状态跟踪
  ├─ Booking Agent：库存锁定、订单创建、支付触发
  ├─ Notification Agent：消息、日历、提醒
  └─ Exception Agent：异常处理、重试、补偿
```

协作原则：

- Orchestrator 负责总规划和最终决策。
- 子 Agent 只处理自己领域内的有限任务。
- 子 Agent 不直接互相抢控制权。
- 所有工具调用仍然通过 Tool Gateway。
- 长事务和补偿逻辑交给 Workflow Engine。

## 6. Tool Gateway 设计

Tool Gateway 是 Agent 和业务系统之间的稳定边界。

职责：

- 工具注册：统一暴露工具名称、描述、必填参数。
- 参数校验：阻止缺参、空参进入业务系统。
- 权限鉴权：校验用户、企业、角色、数据范围。
- 调用审计：记录工具名称、输入字段、成功失败、错误原因。
- 幂等控制：审批、订单、支付等动作必须具备幂等键。
- 错误标准化：把业务错误转换成 Agent 可处理的结构化错误。
- 敏感信息保护：脱敏证件号、手机号、支付信息。

工具定义示例：

```json
{
  "name": "search_hotels",
  "description": "根据城市、入住日期、会场位置和价格上限查询酒店",
  "required": ["city", "check_in", "check_out", "venue", "max_price"]
}
```

## 7. 工作流设计

复杂差旅流程不应完全交给 LLM 自由执行。推荐使用确定性状态机或工作流引擎。

基础状态：

```text
DRAFT：会话已创建，尚未完成政策校验
POLICY_CHECKED：已获取差旅政策和预算上限
PLAN_GENERATED：已生成行程草案和酒店候选
USER_CONFIRMED：用户已确认关键方案
APPROVAL_CREATED：审批记录已创建
APPROVAL_APPROVED：审批已通过
INVENTORY_LOCKED：酒店库存已锁定
PRICE_CHANGED：价格变化，需要用户二次确认
ORDER_CREATED：订单已创建
COMPLETED：流程完成
USER_CANCELLED：用户取消，补偿动作已尽量执行
```

关键补偿：

- 审批驳回：重新生成低价或更合规方案，进入新一轮审批。
- 价格变化：通知用户并二次确认。
- 库存过期：重新查询并保留原筛选条件。
- 下单失败：取消失败订单、释放库存、撤回审批关联，再重新规划。
- 用户取消：终止流程并记录取消原因。
- 完成后取消：取消订单，释放库存，并保留补偿结果用于审计。
- 取消前退款预估：按酒店和交通订单分别调用退款预估工具，记录可退金额、手续费和规则说明。
- 改签/改期：先做退款预估和改签审批，审批通过后确认退款金额，再调用交通改签和酒店改期工具，记录 `RefundEstimate`、`RefundConfirmationRecord`、`ChangeRecord`；供应商失败时记录 `CompensationResult` 并进入人工可追踪补偿。
- 订单状态变化：刷新订单状态并保存到会话，后续可由调度器定时执行。

恢复流程：

```text
APPROVAL_REJECTED / PRICE_CHANGED / INVENTORY_EXPIRED / ORDER_FAILED
  ↓
replan_after_exception
  ├─ cancel_order（如已有订单）
  ├─ release_hotel_inventory（如已有库存锁）
  ├─ cancel_approval（如审批仍可撤回）
  ├─ workflow_generation + 1
  ├─ 重新查询酒店库存
  └─ PLAN_GENERATED
      ↓
reselect_hotel_and_create_approval
      ↓
APPROVAL_CREATED
```

恢复记录：

- `RecoveryRecord` 记录恢复动作、原因、原状态、新状态、补偿结果、酒店候选数和创建时间。
- 新一轮审批、库存锁、订单和通知的 idempotency key 均包含 `workflow_generation`。
- 旧轮次的通知记录会保留，通知去重按 `session_id + workflow_generation + event_type` 生效。

自动推进边界：

- `APPROVAL_CREATED`：可自动查询审批状态。
- `APPROVAL_APPROVED`：可自动创建交通订单、锁酒店库存、校验价格、创建酒店订单。
- `ORDER_CREATED` / `COMPLETED`：可自动刷新订单状态。
- `PRICE_CHANGED`：必须等待用户或企业策略显式确认，worker 不自动接受。

通知触发：

- `COMPLETED`：通知用户订单已创建。
- `PRICE_CHANGED`：通知用户确认价格变化。
- `APPROVAL_REJECTED`：通知用户审批被驳回。
- `INVENTORY_EXPIRED`：通知用户重新查询酒店。
- `ORDER_FAILED`：通知运营或用户介入处理。
- `USER_CANCELLED`：通知用户流程已取消并记录补偿结果。

通知重试：

- `FAILED`：通知发送失败，可由 worker 后续扫描并重试。
- `DEAD_LETTER`：达到最大重试次数后停止自动重试，等待人工或运维重放。
- 通知失败不会回滚审批、库存、订单等主流程状态。

观测与运维：

- 每次 worker `run_once` 生成 `WorkerRunRecord`，记录 `run_id`、起止时间、扫描数、推进数、跳过数、错误和涉及会话。
- SQLite 存储会创建 `worker_runs` 表；生产环境可替换为数据库表、日志平台或工作流引擎历史表。
- `list_dead_letter_notifications` 从持久化会话里查询 `DEAD_LETTER` 通知，保留会话状态和原通知内容。
- `replay_dead_letter_notification` 使用原事件类型、标题、消息和通知渠道重新调用通知工具；成功后写入去重键，失败后回到 `FAILED` 状态继续由 worker 重试。
- CLI 暴露 worker 历史、死信列表、死信重放和基础指标摘要，便于在真实监控系统接入前做运维验证。
- CLI 支持 `--metrics --metrics-format prometheus` 输出 Prometheus text exposition，覆盖 worker 扫描/推进/错误、通知死信、会话状态、Agent 执行摘要和日历同步状态。
- CLI 支持 `--serve-metrics` 启动标准库 HTTP 指标服务，暴露 `/metrics` 和 `/health`，方便 Prometheus 或边车采集器直接拉取。
- CLI 支持 `--export-otlp` 生成 OTLP/HTTP traces 与 metrics 并导出到 OpenTelemetry Collector，trace 覆盖 worker run 和子 Agent 执行摘要，metrics 覆盖 worker、会话状态、死信、日历同步和 SLA alert 点。

## 8. 第一阶段开发落地

当前仓库的阶段性实现：

```text
src/travel_agent/
  ├─ agent.py       单 Agent 编排和任务规划
  ├─ config.py      真实系统接入配置
  ├─ domain_agents.py 多 Agent 协作雏形，封装策略、酒店、交通、审批、预订等领域 Agent
  ├─ integrations.py 真实系统 HTTP 适配与 mock fallback
  ├─ models.py      请求、政策、酒店、审批、上下文数据模型
  ├─ state.py       工作流状态机
  ├─ storage.py     内存/SQLite 会话存储
  ├─ tools.py       Tool Gateway
  ├─ worker.py      异步工作流推进器
  ├─ mock_tools.py  Mock 业务工具
  └─ cli.py         CLI 演示入口
```

当前组合下单顺序：

```text
APPROVAL_APPROVED
  ↓
create_transport_order
  ↓
lock_hotel_inventory
  ↓
verify_hotel_price
  ↓
create_order
  ↓
COMPLETED
```

交通订单先于酒店订单创建，因此价格变化、库存失效、用户取消或订单失败时，补偿逻辑会优先取消交通订单，再处理酒店订单和库存释放。

改签/退订深化链路：

```text
COMPLETED / ORDER_CREATED
  ├─ estimate_refund(transport)
  ├─ estimate_refund(hotel)
  ├─ create_change_approval
  ├─ confirm_refund(transport)
  ├─ confirm_refund(hotel)
  ├─ change_transport_order
  ├─ change_hotel_order
  ├─ compensate_change_failure（按需）
  └─ sync_calendar(TRIP_CHANGED)
```

退款预估会生成 `RefundEstimate`，改签审批会写入 `change_approvals`，退款确认会生成 `RefundConfirmationRecord`，改签/改期会生成 `ChangeRecord`，供应商失败补偿会生成 `CompensationResult`；这些记录均写入 `TravelContext` 并可持久化到 SQLite。

日历同步链路：

```text
COMPLETED / ORDER_CREATED / USER_CANCELLED
  ↓
sync_calendar
  ├─ TRIP_BOOKED
  ├─ TRIP_CHANGED
  └─ TRIP_CANCELLED
```

日历同步会生成 `CalendarSyncRecord`，记录事件类型、同步状态、日历事件 ID、时间范围、参会人、重试次数、错误原因和来源；改签后的日历时间优先使用最近一次酒店改期结果。

日历重试/死信：

- `FAILED`：日历同步失败，可由 worker 后续扫描并重试。
- `DEAD_LETTER`：达到最大重试次数后停止自动重试，等待人工或运维重放。
- `list_dead_letter_calendar_syncs` 可查询日历死信，`replay_dead_letter_calendar_sync` 可按事件类型重放。
- 日历同步支持传入 `attendees`，用于更新参会人或同步给管理者。

运行方式：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-confirm
```

完整下单并执行取消补偿：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --origin 北京 --destination 上海 --start 2026-06-03 --end 2026-06-05 --venue "上海张江人工智能岛" --purpose "客户会议" --budget 650 --auto-book --cancel-after-book
```

运行一次 worker：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-worker-once
```

运行多轮 worker loop：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --run-worker-once --worker-iterations 10 --worker-interval 5
```

查看运行历史、通知死信并重放：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-worker-runs
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-dead-letters
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --list-calendar-dead-letters
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-dead-letter-session "<session-id>" --replay-dead-letter-event "ORDER_COMPLETED"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-calendar-dead-letter-session "<session-id>" --replay-calendar-dead-letter-event "TRIP_BOOKED"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --metrics
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --serve-metrics --metrics-port 9108
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --export-otlp --otlp-endpoint "http://localhost:4318"
```

异常恢复并重新提交审批：

```powershell
$env:PYTHONPATH = "src"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replan-session "<session-id>" --replan-reason "operator_replan"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --reselect-hotel-session "<session-id>" --hotel-id "SHA-002"
```

测试方式：

```powershell
python -m unittest discover -s tests
```

## 9. 多 Agent 协作深化

当前已完成多 Agent 协作深化，并保持 CLI、状态机、Tool Gateway 和测试入口兼容。`TravelAgent` 仍是对外 facade，同时承担第一版 Orchestrator 职责；内部通过 `AgentTeam` 持有各领域子 Agent。

已拆分：

- `TravelAgent`：对外 facade 和当前 Orchestrator，负责状态机、会话持久化、通知、恢复流程入口。
- `PolicyAgent`：负责酒店政策和交通政策检查。
- `ItineraryAgent`：负责行程草案生成。
- `HotelAgent`：负责酒店查询、库存锁定、价格校验和库存补偿工具调用。
- `TransportAgent`：负责机票/火车票查询、交通订单、状态刷新和交通补偿工具调用。
- `ApprovalAgent`：负责 OA 审批创建、状态跟踪和撤回工具调用。
- `BookingAgent`：负责酒店订单创建、订单状态同步和酒店订单补偿工具调用。

已落地的深化点：

- `TravelContext.agent_executions` 持久化子 Agent 执行摘要，SQLite round-trip 后仍可追踪。
- CLI 输出 `Agent 执行摘要`，便于排查一次流程中各领域 Agent 的执行顺序和结果。
- 价格变化拒绝、用户取消、异常恢复中的交通订单取消、酒店订单取消、库存释放和审批撤回，均由对应子 Agent 执行。
- 订单状态刷新通过 `TransportAgent.refresh_order` 和 `BookingAgent.refresh_hotel_order` 完成，并保留旧订单金额，兼容只返回状态的真实系统。
- 异常恢复重规划阶段通过 `PolicyAgent`、`ItineraryAgent`、`HotelAgent`、`TransportAgent` 重新补齐政策、行程和库存候选。
- 改签和退订深化通过 `TransportAgent`、`BookingAgent`、`ApprovalAgent` 协作生成退款预估、改签审批、退款确认、改签记录和失败补偿，保持与现有 Orchestrator/facade 兼容。
- 日历同步通过 `TravelAgent.sync_calendar` 暴露，支持完成、改签和取消三类事件，保留 mock/真实系统来源，并支持失败重试、死信和参会人更新。

落地原则：

- 第一版多 Agent 先做代码模块边界，不引入外部框架。
- 所有子 Agent 仍通过 `ToolGateway` 调用业务工具。
- `TravelContext` 仍作为共享工作流上下文，避免引入不必要的数据迁移。
- 保持现有 `TravelAgent` facade，确保 CLI 和测试不用大规模改造。

下一阶段主线：

- 评测集：沉淀政策超标、审批驳回、价格变化、库存失效、订单失败、改签失败、日历死信等多场景回归用例。
- 生产化存储：评估将 SQLite 会话存储替换为生产数据库或工作流引擎。
