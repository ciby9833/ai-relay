# 飞书接入说明

Relay 用到的飞书能力、用在什么场景、什么时候会提醒用户。验收时点的实测数字记在 [FEISHU_ACCEPTANCE_LOG.md](FEISHU_ACCEPTANCE_LOG.md)，这里不放。

路径均在 `https://open.feishu.cn/open-apis` 下。

## 原则

**飞书数据有两种用途，别混在一起：**

| 用途 | 例子 | 会不会提醒用户 |
|---|---|---|
| **要处理的事**：需要用户本人回复、决定或出席 | 外部邮件、会议邀请、待我审批、@我的消息、业务系统告警、自己发起被驳回的审批 | 会，变成跟进事项（等你 / 等别人），实时告诉他 |
| **理解用的背景**：帮 Relay 弄懂上下文、回答问题、写得更准 | 知识库、文档、电子表格、多维表格、群聊记录、通讯录、抄送审批 | 不会；按需读取，最多进每日简报 |

**写操作一律先确认。** 写类工具名以 `prepare_` 开头，只在本地生成待确认操作（PendingAction）。用户通过网页按钮、飞书卡片按钮或对话中的 `confirm_action` 确认后才执行。长期任务可以按任务给出授权（例如“这个任务里的群消息可以直接发”），授权范围见 `proactive/actions.py` 的 `GRANTABLE`。

**身份。** 能用用户身份（`user_access_token`）就用，失败后不会改用应用身份扩大读取范围。只有飞书要求应用身份的接口才用 `tenant_access_token`（审批、考勤、机器人发消息），这时 `user_id` 固定为当前用户本人，模型不能传入别人的 ID。

## 按场景

### 邮件

| 能力 | 接口 | 工具 / 模块 |
|---|---|---|
| 搜索、按文件夹看 | `POST /mail/v1/user_mailboxes/me/search`、`GET .../messages?folder_id=` | `search_mail`、`list_mail_folder` |
| 读正文 | `GET .../messages/{id}?format=plain_text_full` | `read_mail` |
| 本人地址 | `GET .../profile` | 回复全部时排除自己 |
| 起草、发送 | `POST .../drafts`、`POST .../drafts/{id}/send` | `draft_mail_reply`、`revise_draft`（都支持 `reply_all`） |
| 读附件 | `GET .../messages/{id}/attachments/download_url` → 下载原件解析 | `read_mail_attachment`：xlsx / docx / pdf / csv / txt；Excel 带行号列字母，Word 保留修订和批注；≤60MB，长内容分段 |
| 已发送同步 | `GET .../messages?folder_id=SENT` | 判断“他已经在别处回复了”，自动关闭等你回复的事项 |

**回复全部**：抄送 = 原邮件的收件人 + 抄送人，去掉本人地址和原发件人，去重。网页草稿编辑器和对话里都可以切换。

**提醒**：外部、需要他回复的邮件 → 等你回复；他回复后对方 3 天没回 → 提醒并起草跟进邮件（最多 2 次）。通知类、群发类邮件只进简报。

### 日历与会议

| 能力 | 接口 | 工具 |
|---|---|---|
| 查日程 | `GET /calendar/v4/calendars/{id}/events/instance_view`（含重复日程实例） | `list_calendar_events` |
| 找空档 | `POST /calendar/v4/freebusy/batch` | `find_meeting_times` |
| 约会 | `POST .../events`、`POST .../events/{id}/attendees` | `prepare_meeting` |
| 改期、取消、加人 | `PATCH` / `DELETE .../events/{id}`、`POST .../attendees` | `prepare_reschedule`、`prepare_cancel_meeting`、`prepare_add_attendees` |
| 看回复情况 | `GET .../events/{id}/attendees`（查不到时用 base_event_id + 组织者日历兜底） | `get_meeting_responses` |
| 回复邀请 | `POST .../events/{id}/reply` | `respond_to_invitation` |

**提醒**：新的会议邀请 → 等你回复（带冲突检查）；会前给出会议准备（参会人和相关背景）。

### 审批

| 能力 | 接口 | 工具 |
|---|---|---|
| 待我审批 | `GET /approval/v4/tasks/query?topic=1` | `list_pending_approvals`、`get_approval_detail` |
| 批准 / 驳回 | `POST /approval/v4/tasks/approve`、`/reject` | `decide_approval`（需确认） |
| 我已审批、我发起的、抄送我的 | 同一接口，`topic=2` / `3` / `17`+`18`（抄送未读+已读，合并去重，不改已读状态） | `query_my_approvals`、`read_my_approval` |
| 详情 | `GET /approval/v4/instances/{code}` | |

任务列表的 `process_status`：0 无状态、1 审批中、2 通过、3 驳回、4 撤回（实测有字符串也有数字，统一转成字符串）。不要和实例详情里的 `PENDING/APPROVED/...` 混用。

**需要补填内容的节点**（例如要选 IT 处理人）不能在 Relay 里直接批，卡片只给“去飞书处理”的入口，避免绕过必填项直接通过。

**提醒规则：**

| 情况 | Relay 怎么做 |
|---|---|
| 待我审批 | 等你处理，实时提醒；可以直接批的带批准/驳回按钮 |
| 我发起、审批中 | 静默放进“等别人”；3 天没结果提醒他催一下 |
| 我发起、通过 | 告诉他一声，关闭“等别人”，不留待办 |
| 我发起、驳回或撤回 | 等你处理：看原因，修改后重新提交 |
| 抄送我的 | 只知会：不建事项、不推送，进每日简报的团队动态；随时可查 |

首次同步只建档（历史结果不提醒），之后每 5 分钟随审批来源同步一次。

### 消息与群聊

| 能力 | 接口 | 身份 | 工具 |
|---|---|---|---|
| 找群 | `GET /im/v1/chats/search`（没有用户身份群权限时退回到机器人所在的群） | 用户 / 应用 | `find_chats` |
| 读群消息 | `GET /im/v1/messages?container_id_type=chat` | 用户 | `read_chat_messages` |
| 以本人身份发 | `POST /im/v1/messages` | 用户 | `prepare_chat_message`（需确认） |
| 以 Relay 机器人代发 | `POST /im/v1/messages`，正文前注明“某某的助理 Relay 代发” | 应用 | `prepare_chat_message` + `as_relay` |
| 推送卡片、私聊回复 | `POST /im/v1/messages`、`PATCH /im/v1/messages/{id}` | 应用 | `feishu/client.py`、`proactive/push.py` |

群消息主要用来**理解**：机器人所在的群里，Relay 从对话中找出明确交给他的事（“@他 帮忙看下…”）变成事项，其余只作为回答问题、写回复时的背景。**@他的消息**实时提醒。

### 通讯录与组织架构

| 能力 | 接口 | 身份 |
|---|---|---|
| 搜人 | `GET /search/v1/user` | 用户 |
| 按邮箱/手机号查 | `POST /contact/v3/users/batch_get_id` | 应用 |
| 个人资料、上级、部门 | `GET /contact/v3/users/{open_id}`、`GET /contact/v3/departments/{id}` | 用户 |
| 搜部门、部门成员 | `POST /contact/v3/departments/search`、`GET /contact/v3/users/find_by_department` | 用户 |

工具：`find_person`、`person_profile`、`search_departments`、`list_department_members`。组织架构必须用用户身份（应用身份会报 no dept authority）。查到的人记进本地名册 `people`，支持中文名、英文名、括号内名字；**同名多人时让用户选**，不猜。

### 考勤

`POST /attendance/v1/user_tasks/query`（应用身份，只查本人）。工具 `attendance_today`。工作日到点没打卡提醒一次；其他考勤数据只在用户问到时查。

### 飞书任务

`POST /task/v2/tasks`（用户身份）。工具 `prepare_task`：把对话或事项里的事交给某人，需确认，可设截止时间。需要开通 `task:task:write`。

### 云文档

**理解类读取**（不需要确认，以本人权限读取，不提醒）：

| 工具 | 接口 | 用途 |
|---|---|---|
| `search_docs` | `POST /search/v2/doc_wiki/search` | 按关键词找文档和知识库；保留分页，不把摘要当全文 |
| `read_feishu_doc` | `GET /wiki/v2/spaces/get_node` → 按类型分发；docx 用 `GET /docx/v1/documents/{id}/raw_content`；`/file/` 用 `GET /drive/v1/files/{token}/download` 下载后解析 | 给链接就读：文档正文、知识库节点、云空间上传的原件（Excel、Word、PDF）、表格和多维表格结构。长内容分段，传 offset 继续 |
| `list_wiki_spaces`、`list_wiki_nodes` | `GET /wiki/v2/spaces`、`.../{space_id}/nodes` | 浏览知识库目录 |
| `list_drive_files` | `GET /drive/v1/files` | 浏览云空间文件夹 |
| `list_sheet_tabs`、`read_sheet_range` | `GET /sheets/v3/.../sheets/query`、`GET /sheets/v2/.../values/{range}?valueRenderOption=ToString` | 接受链接或 token；值按纯文本返回为 `R行号 \| 列字母: 值`，标出合并单元格；单次 ≤5000 格 |
| `list_base_tables`、`list_base_fields`、`list_base_records` | `GET /bitable/v1/apps/{app}/tables...` | 读多维表格的表、字段、记录 |

起草邮件回复时，Relay 也会顺带搜一下知识库和相关群聊，让回复有依据。

**产出**（需确认）：

| 工具 | 接口 | 说明 |
|---|---|---|
| `prepare_create_doc` | `POST /docx/v1/documents` | 新建空白文档（例如会议纪要、周报） |
| `prepare_append_doc_text` | `POST /docx/v1/documents/{id}/blocks/{block_id}/children` | 在文档末尾追加纯文本段落（不解析 Markdown） |
| `prepare_fill_sheet_cells` | `GET /drive/v1/permissions/{token}/members/auth?action=edit` 预检 → `POST /sheets/v2/.../values_batch_update` | 按单元格填别人发来的表格。准备时检查本人编辑权限、合并单元格改写到左上角、读出原值；确认卡片显示“原值 → 新值”；确认时原值变了就拒绝写入 |

确认卡片展示要写到哪、写什么，执行后返回一句话结果，飞书的原始返回保存在操作记录里。

**读不到原件的情况**：存放在其他数据区（例如 `xxx.sg.feishu.cn`）的云空间文件，开放接口跨区域下载会返回 404，Relay 会说明原因，并建议改读邮件里的同名附件或在飞书里另存为在线表格。

**填表写不进去时**，按原因分别告诉用户：应用没开表格写权限（找管理员开通 `sheets:spreadsheet` 后重新登录）、本人对文件只有查看权限（找所有者开编辑权限）、确认前单元格被别人改过（重新读取后再准备）。

**已实现、暂不开放给模型**：`sources/cloud.py` 里还有整块覆盖表格范围、增改多维表格记录、建知识库节点、改标题、建表格、复制文件、画板节点、文档评论订阅、日历列表等操作。它们有完整的参数校验和“修改前快照、确认时复查”，场景明确后在 `agent/tools/cloud.py` 的 `EXPOSED` 里加上即可。

## 语言

同事里有中国人也有印尼人，Relay 不默认中文：

| 内容 | 用什么语言 |
|---|---|
| 和用户对话 | 用户这句话用的语言 |
| 主动提醒、简报、审批摘要、飞书卡片按钮和标题 | 用户的常用语言：设置里可指定（简体中文 / English / Bahasa Indonesia），默认按他发给 Relay 的消息自动识别 |
| 替用户写给别人（邮件回复、飞书消息） | 对方的语言：回邮件用原邮件语言，发消息用双方往来时的语言，看不出来用英文 |
| 机器人代发的署名 | 英文（Sent by Relay on behalf of …） |

看板分组名、网页界面等固定文字暂时还是中文。

## 事件接入

### 飞书长连接

`feishu` 服务（`python -m app.feishu.longconn`，lark-oapi）订阅：

| 事件 | 处理 |
|---|---|
| `im.message.receive_v1` | 私聊 → 进入主线对话，Relay 回复；群聊 → 记入群消息、更新人员名册，@他或交给他的事变成事项。引用回复会带上被引用的原文 |
| `card.action.trigger` | 卡片按钮（确认、取消、批准、回复邀请等）。2.2 秒内在回调响应里直接返回新卡片；超时则先回 toast，处理完再更新卡片 |

同一个应用只能有一个长连接在消费，本地和生产不要同时连同一个应用。

### 业务系统接入

公司内部系统（TMS、财务等）把需要某人处理的事推给 Relay。管理员在网页“业务系统接入”里登记，拿到推送地址和密钥。

```
POST /api/inbound/{key}
X-Relay-Timestamp: <Unix 秒>
X-Relay-Signature: hex(HMAC-SHA256(密钥, "{timestamp}.{请求体原文}"))
```

| 字段 | 说明 |
|---|---|
| `event_id` | 必填，重复推送只处理一次 |
| `title` / `content` | 必填 / 可选 |
| `recipients` | 必填，`[{"email"} \| {"open_id"} \| {"name"}]`；没用过 Relay 的同事也能收到 |
| `priority` | `urgent` / `normal`（默认）/ `low`（只进简报） |
| `group_key` | 归并键（如订单号），同一个键的后续事件更新同一件事 |
| `status` | `open`（默认）/ `resolved`（关闭对应事项） |
| `action_hint`、`due_at`、`url`、`data` | 告诉用户要做什么、截止时间、详情页、结构化字段 |

时间戳与服务器相差超过 5 分钟拒绝；请求体上限 256KB。

## 权限与授权

登录时 Relay 从 `/application/v6/scopes` 读取应用已生效的用户权限并全部申请，**不需要在环境变量里配置 scope**。后台新开了权限后：创建版本并发布 → 用户在 Relay 退出并重新登录（旧 token 不会自动获得新权限）。同步时发现缺权限会提醒用户重新授权，缺权限的错误原样展示，不当成“没有数据”。

常见的缺口（任选其一即可）：

| 能力 | 用户身份权限 |
|---|---|
| 云空间文件列表 | `drive:drive:readonly` / `space:document:retrieve` |
| 电子表格 | `sheets:spreadsheet:readonly` |
| 多维表格 | `bitable:app:readonly` / `base:table:read` |
| 新建、追加文档 | 文档创建/编辑接口页列出的写权限 |
| 用户身份搜群 | `im:chat:readonly` |
| 长期任务查对方在私聊里的回复 | `im:message.p2p_msg:get_as_user`（没开时只能到点再看） |
| 飞书任务 | `task:task:write` |

所有接口还受用户本人对目标资源的访问级别限制。官方说明：[配置权限](https://open.feishu.cn/document/uAjLw4CM/ugTN1YjL4UTN24CO1UjN/trouble-shooting/how-to-add-permissions-to-app)、[错误 99991679](https://open.feishu.cn/document/uAjLw4CM/ugTN1YjL4UTN24CO1UjN/trouble-shooting/how-to-resolve-error-99991679)。

## 写入机制

- 云文档操作用封闭的 JSON Schema 校验参数，模型不能提交任意 API 路径（`sources/cloud.py`）。
- 覆盖类操作在准备时读取原值，确认时复查；已被他人修改则拒绝执行，要求重新准备。
- 确认时校验操作归属，用数据库行锁防止重复点击；支持 `client_token` 的接口用操作 ID 生成稳定的幂等键。
- 网络超时记为“结果未知”，不自动重试。

## 验证

```bash
# 单元测试 + 真实数据库集成测试（假飞书，不写真实飞书）
docker compose -f compose.test.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yml down
```

```bash
# 只读核验真实账号：不打印正文和凭证，不推送，不写入
docker compose run --rm --no-deps -v "$PWD/backend:/srv:ro" api python -m scripts.audit_feishu
```

测试数据只用虚构姓名，不在真实飞书资源上做写入测试。真实写入要由用户针对明确的目标确认执行后，才算验收通过。
