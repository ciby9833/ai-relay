# Relay

公司内部的个人助手：记得每位同事是谁、在忙什么，能读飞书文档，能定时主动找你。
入口有两个：网页端和飞书机器人，背后是同一个 Agent、同一份记忆。

后续按“以助理为核心、本地工作空间与云端持续协作”的方向演进。待实施的 [架构改造方案](docs/ASSISTANT_ARCHITECTURE.md) 与 [阶段 0／1 任务清单](docs/ASSISTANT_PHASE_0_1.md) 已记录；独立身份、客户端和助理间协作尚不属于当前已交付能力。

飞书各模块的能力范围、官方 API 对照、权限开通步骤见 [飞书接入与验收文档](docs/FEISHU_API.md)。常用云文档读写已接入确认机制；是否实际可用还取决于应用权限、用户授权和目标资源权限。

## 启动

```bash
cp .env.example .env      # 填写 SECRET_KEY、POSTGRES_PASSWORD、飞书和模型的 key
docker compose up -d --build
```

- 网页端：http://localhost:5173
- API：http://localhost:8098 （飞书登录回调走这个端口）
- 数据库迁移在 `api` 容器启动时自动执行

开发时用热重载：

```bash
docker compose -f compose.yml -f compose.dev.yml up
```

跑测试：

```bash
docker compose -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yml down
```

Web 界面语言支持、Figma 组件参考和交互检查记录见 [Web UI 与国际化](docs/WEB_UI.md)。

Blog 位于 `/blog/`，文章原始 HTML、图片和视频存储在 PostgreSQL，API 启动时自动导入随版本附带的文章。新增文章、草稿和生产部署步骤见 [Blog 发布与维护](docs/BLOG.md)。

## 组成

| 服务 | 作用 |
|---|---|
| `db` | Postgres 17 + pgvector，业务数据和记忆向量都在这里 |
| `api` | FastAPI：登录、对话（SSE 流式）、飞书事件回调 |
| `worker` | 定时任务执行进程，每 30 秒检查一次到点的任务 |
| `feishu` | 飞书长连接，接收机器人消息（不需要公网地址） |
| `web` | Nginx 托管前端，并把 `/api` 反代到 `api` |

```
backend/app/
  agent/        Agent 主循环、系统提示词、工具（agent/tools/）
  llm/          Claude / OpenAI / Gemini 适配器，统一成一种消息格式
  memory/       长期记忆的存取与语义检索
  feishu/       飞书客户端（登录、发消息、读文档）和事件解密
  scheduler/    定时任务的时间计算与执行进程
  api/          HTTP 接口
frontend/src/   React 网页端
```

## Relay 在做什么

Relay 以「事」为单位替用户跟进，而不是把消息一条条转给他。`worker` 每 30 秒为每位用户跑一遍：

1. **采集**：同步邮件、日历、审批、考勤，以及群里@他的消息（邮件和日历用本人授权，其余用应用身份）。
2. **判断**：新邮件交给模型，结合个人记忆分级，并判断需要他回复、需要他看，还是只是知会。
3. **归并成跟进事项**（`follow_ups` 表）：
   - 同一邮件线程是一件事。
   - 同一个人同一天发来的一批邮件是一件事，例如 11 封需求归成「Hendri 发来 11 封邮件需要你看」。
   - 一个会议邀请、一张审批也各是一件事。
   每件事记录球在谁那（等你 / 等别人）、下一步、Relay 的建议和截止时间。
4. **先做事**：要他回复的邮件先起草好；会议邀请先查时间冲突，再给出建议（接受或待定）。
5. **推进与闭环**：
   - 回复发出后，转为「等对方回复」，3 天没回就提醒，并起草一封跟进邮件。
   - 对方回了，又变成「等你回复」。
   - 邀请回复后、审批处理后、群里回了@，对应的事自动关闭。
6. **实时告诉用户**：新出现的事在「主线」里用一两句话说明，附可操作的卡片，同时推一张飞书卡片。
   飞书卡片上每件事的按钮紧跟在它下面。免打扰时段先记下，结束后再说，紧急的事不受限制。

网页首页上方是跟进看板，分三栏：等你、等别人、Relay 在办（会前准备、盯回复）。下方是和 Relay 的主线对话，
网页和飞书私聊是同一条。用户可以点卡片，也可以直接说「发吧」「这个不用跟了」。
早间简报默认关闭，需要时点「简报」，或者在设置里打开。

**对外的操作一律等用户确认**：发邮件、回复会议邀请都只准备好，用户点确认才执行，按钮只认点击者本人。
邮件、文档内容在提示词里都标为外部数据，不能驱动助手执行操作。
用户正在对话时，主动发言会等这一轮结束再发（跨进程的 Postgres advisory lock）。

## 长期任务

需要持续推进、要等别人回应的事（「盯着客户 A 的报价直到确认」「约齐 Andrew、Nikki 下周开评审会并跟到都接受」
「催 Andrew 本周交运单明细」），在主线里说一句，Relay 用 `start_mission` 接下，在后台分多次推进：

- 每个任务有自己的对话和计划、工作笔记、时间线（`missions`、`mission_logs` 表），每次醒来都接着之前的进度干。
- 每次醒来先推进一步：查资料、找人、查忙闲、准备消息/任务/会议，最后决定接下来做什么：
  - 过一段时间再看（`wait_until`）
  - 等对方回信或群里回复（`wait_for_reply`）
  - 问用户（`ask_user`，任务暂停到他回答）
  - 结束（`complete_mission`）
- 它准备的操作被用户确认或取消后，任务会被自动叫醒，知道结果后继续。
- 有实质进展才在主线汇报，并推到飞书；待确认的操作附在汇报里，带确认按钮。
- **权限**：对外操作（发飞书消息、建飞书任务、发会议邀请、发邮件、回复邀请）默认都要用户确认。
  用户可以在任务页为单个任务勾选「允许自动做」的类型，只能在界面上由用户设置，模型不能给自己授权。
  审批始终逐张处理，不能授权自动执行。
- **上限**：单个任务最多醒来 60 次，单轮最多 16 步，防止失控。

网页左侧「长期任务」里可以看每个任务的计划、时间线、等你确认的操作，设置授权、立即推进或停止。

## 业务系统接入

业务系统（TMS、WMS、CRM……）有需要人处理的事时推给 Relay，Relay 通知到具体的人、放进他的跟进看板、实时告诉他。
管理员在网页「业务系统接入」里登记系统，拿到推送地址和签名密钥（第一位用飞书登录的用户自动成为管理员）。

`POST /api/inbound/{key}`，请求头 `X-Relay-Timestamp`（Unix 秒）和
`X-Relay-Signature = hex(HMAC-SHA256(密钥, "{timestamp}.{请求体原文}"))`，时间戳与服务器相差超过 5 分钟会被拒绝。

```json
{
  "event_id": "order-JT123-exception-1",
  "title": "订单 JT123 清关异常，需要确认是否改派",
  "content": "海关要求补充发票，预计延误 2 天",
  "recipients": [{"email": "someone@company.com"}, {"name": "Andrew（陈春华）"}],
  "priority": "urgent",
  "url": "https://tms.example.com/orders/JT123",
  "group_key": "JT123",
  "action_hint": "确认是否改派",
  "due_at": "2026-10-16T18:00:00+07:00",
  "data": {"order_no": "JT123"}
}
```

- `event_id` 用于去重，重复推送只处理一次。
- `group_key` 相同的事件归到同一件事。
- `priority`：
  - `urgent`：免打扰时段也会通知；
  - `normal`；
  - `low`：只归纳进简报。
- `status: "resolved"` 时关闭对应的事。
- 收件人支持 `email`、`open_id`、名字；没用过 Relay 的同事也能通过机器人收到。

生产环境要让业务系统访问到这个地址，需要通过公网域名，例如 `https://<域名>/api/inbound/{key}`。

## 飞书后台需要的配置

1. **重定向 URL**（安全设置）：与 `.env` 的 `FEISHU_REDIRECT_URI` 完全一致。
2. **事件与回调**，订阅方式都选“长连接”：
   - 事件：`im.message.receive_v1`
   - 回调：`card.action.trigger`（卡片按钮）
   由 `feishu` 服务建立连接，不需要公网地址。同一应用有多个长连接时每条事件只推给其中一个，本地和线上不要同时连。
3. **飞书权限**（权限管理，开通后需发布版本并经管理员审核）：

   用户身份（后台开通只是允许应用申请；登录时 Relay 会查询应用已开通的全部用户身份权限（`/application/v6/scopes`）
   逐项向用户申请，用户同意后才生效。后台新开通权限后，Relay 会发现用户的授权里缺了哪些，主动提醒他重新授权一次）：
   - `offline_access`：后台持续同步必须，否则 token 两小时后过期
   - 日历：`calendar:calendar:readonly`、`calendar:calendar.event:reply`（接受/拒绝邀请）
   - 邮件：`mail:user_mailbox.message:readonly`、`mail:user_mailbox.message.subject:read`、
     `mail:user_mailbox.message.address:read`、`mail:user_mailbox.message.body:read`；
     起草和发送：`mail:user_mailbox.message:modify`、`mail:user_mailbox.message:send`
   - 文档：`docx:document:readonly`、`wiki:wiki:readonly`，以及文档搜索权限
   - 长期任务里建飞书任务、发会议邀请：飞书任务的写权限、日历的写权限

   应用身份：
   - 消息：`im:message`、`im:message:send_as_bot`、`im:message.group_msg`（读机器人所在群的全部消息，用于提取待办；没有它只能看到@机器人的消息）、`im:chat:readonly`
   - 通讯录：读取用户姓名（群消息里识别发言人）；按邮箱查用户 ID（找群里没出现过的同事）
   - 日历：查询忙闲（约会时找共同空闲时间）
   - 审批：任务查询权限
   - 考勤：`attendance:task:readonly`
   - 通讯录：`contact:user.employee_id:readonly`（考勤要用 user_id）

   权限名以飞书后台为准。缺哪个权限时，接口报错会写明，并显示在「提醒设置」的数据源下面。

## 模型

Gemini 支持两种接入：把 Google Cloud 服务账号文件放在本目录，`.env` 里写
`GOOGLE_CREDENTIALS_FILE=./xxx.json`（走 Vertex AI，优先），或者填 `GEMINI_API_KEY`。
服务账号文件已被 `.gitignore` 忽略，不要提交。

其余在 `.env` 里填了哪家的 key 就启用哪家，网页端可以按对话切换。模型名都是配置项
（`ANTHROPIC_MODELS` / `OPENAI_MODELS` / `GEMINI_MODELS`），默认模型由 `DEFAULT_MODEL` 指定。

记忆的语义检索需要 embedding，Claude 不提供，所以至少要配 OpenAI 或 Gemini 其中一个的 key；
都没有时记忆仍然可用，只是按时间而不是按相关性召回。

## 加一个工具

在 `backend/app/agent/tools/` 里写一个带 `@tool` 的异步函数，并在该目录的 `__init__.py` 里导入：

```python
@tool("tool_name", "给模型看的说明", {"arg": {"type": "string"}}, ["arg"])
async def tool_name(ctx: ToolContext, args: dict) -> str:
    ...
```

`ctx` 里有当前用户、数据库会话和飞书客户端。需要以用户身份调飞书接口时用
`ctx.feishu.user_token(ctx.user)`，不要用应用身份代替，否则会绕过用户自己的权限。

## 改数据库结构

改 `backend/app/models.py` 后生成迁移：

```bash
docker compose run --rm api alembic revision --autogenerate -m "说明"
```

## 发布到 GitHub

发布范围仅限 `/Users/ellis/Documents/CargoPPT/relay`，目标固定为
[`ciby9833/ai-relay`](https://github.com/ciby9833/ai-relay)。发布步骤与生产部署配置见
[部署与发布说明](docs/DEPLOYMENT.md)。`.env`、云服务凭证、数据库备份和内部验收记录只保留在本机或服务器。

## 部署

同一份 `compose.yml`。生产环境的 `.env` 里改：

```
ENV=production
FRONTEND_URL=https://<域名>
FEISHU_REDIRECT_URI=https://<域名>/api/auth/feishu/callback
```

容器默认只监听 `127.0.0.1`，由宿主机的 Nginx 做 HTTPS 并反代到 `WEB_PORT`（默认 5173）。
反代时对 `/api/` 关闭缓冲（`proxy_buffering off`），否则流式回答会卡住。

数据都在 `pgdata` 卷里，迁移机器时备份数据库，并另外安全保存 `.env` 和凭证；`SECRET_KEY` 用于解密已保存的 token，必须保留：

```bash
docker compose exec db pg_dump -U relay relay > relay.sql
```
