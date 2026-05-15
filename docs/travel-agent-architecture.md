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
  ├─ Observability Store：记录 worker 执行摘要、死信通知和基础运行指标
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
- 会话可持久化到 SQLite，后续可替换为生产数据库或工作流引擎。
- 锁库存后、下单前执行价格校验；价格变化时进入二次确认。
- 订单创建后可刷新订单状态，便于后续接入异步轮询。
- `WorkflowWorker` 可扫描持久化会话并自动推进审批状态和订单状态。
- 关键状态可触发通知/待办回调，并通过 `notification_keys` 幂等去重。
- 通知失败不会阻断主流程，会记录失败、重试次数和死信状态。
- worker 每轮执行会落库运行摘要，支持后续排查扫描数、推进数、跳过数和错误会话。
- 达到重试上限的通知可查询并人工重放，重放失败后会重新进入可重试队列。
- 异常恢复会通过 `workflow_generation` 开启新一轮流程，避免重新提交时复用上一轮审批、库存、订单和通知幂等键。

第一阶段历史范围曾暂不包含真实库存、真实 OA、订单创建、补偿和多 Agent。当前实现已推进到真实系统适配、酒店 + 交通组合下单、异常恢复、通知死信和观测能力；剩余未完成的主线是多 Agent 协作雏形、改签/退订、日历同步和生产级指标出口。

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

## 8. 第一阶段开发落地

当前仓库的阶段性实现：

```text
src/travel_agent/
  ├─ agent.py       单 Agent 编排和任务规划
  ├─ config.py      真实系统接入配置
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
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --replay-dead-letter-session "<session-id>" --replay-dead-letter-event "ORDER_COMPLETED"
python -m travel_agent.cli --session-db "D:\tmp\travel-agent.sqlite3" --metrics
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

## 9. 下一阶段推进

下一阶段进入多 Agent 协作雏形，但会保持当前 CLI、状态机、Tool Gateway 和测试入口兼容。

计划拆分：

- `OrchestratorAgent`：负责总流程、状态推进和异常恢复决策。
- `PolicyAgent`：负责酒店政策、交通政策和合规解释。
- `HotelAgent`：负责酒店查询、库存锁定、价格校验和酒店补偿。
- `TransportAgent`：负责机票/火车票查询、交通订单和交通补偿。
- `ApprovalAgent`：负责 OA 审批创建、状态跟踪和撤回。
- `BookingAgent`：负责组合下单顺序、订单状态同步和跨域补偿编排。

落地原则：

- 第一版多 Agent 先做代码模块边界，不引入外部框架。
- 所有子 Agent 仍通过 `ToolGateway` 调用业务工具。
- `TravelContext` 仍作为共享工作流上下文，避免引入不必要的数据迁移。
- 保持现有 `TravelAgent` facade，确保 CLI 和测试不用大规模改造。
