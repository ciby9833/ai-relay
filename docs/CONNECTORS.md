# 连接器清单

> 由 `backend/app/connectors/catalog.py` 生成（`python -m app.connectors.catalog`），不要手改。
> 测试保证代码里的每个工具、数据源都在清单里，且本文件与清单一致。

## 连接器

| 连接器 | 说明 |
|---|---|
| `feishu` | 飞书（工作区管理员接入应用；成员登录时授权） |
| `relay` | Relay 自身（不对外的能力：生成文件、待处理事项、记忆、提醒、定时任务、长期任务、协作委托） |
| `mac` | Mac 客户端（成员授权的本机文件夹） |
| `business` | 业务系统（工作区管理员登记，事件推入） |

## 数据源（后台同步，产出 Signal）

| 数据源 | 同步方式 | 产出 | 身份 | 可由谁提供 | 说明 |
|---|---|---|---|---|---|
| `mail` | 轮询 2 分钟：收件箱最近 20 封 + 已发送最近 20 封 | mail, mail_sent | 他本人（用户令牌） | feishu, imap | 接了标准邮箱就用标准邮箱 |
| `calendar` | 轮询 5 分钟：未来 3 天的日程和待回复邀请 | meeting, invitation | 他本人（用户令牌） | feishu, ics | 日历订阅（ICS）只读，不产生待回复邀请 |
| `approval` | 轮询 5 分钟：待我审批、我发起的进展 | approval_pending, approval_update | 他本人（用户令牌） | feishu |  |
| `attendance` | 轮询 5 分钟：今天缺卡 | attendance_missing | 应用（需要员工号） | feishu |  |
| `task` | 轮询 5 分钟：派给他的飞书任务 | task | 他本人（用户令牌，task:task:read） | feishu |  |
| `private_chat` | 轮询 5 分钟：他和常联系同事的私聊（本人开启后） | 私聊消息，只归本人 | 他本人（以用户身份读私聊） | feishu | 默认关闭 |

## 事件（外部推入）

| 事件 | 入口 | 校验 | 去重 | 落到 |
|---|---|---|---|---|
| 群消息 | 长连接（默认工作区）/ /api/feishu/events/{工作区} | verification token + 加密；只认工作区绑定的飞书企业 | event_id | 群消息存档（按工作区）；@他 → mention 信号；@机器人 → 对话 |
| 机器人私聊 | 同上 | 同上 | event_id | 他的首页对话 |
| 卡片按钮 | 同上 | 同上；只在本工作区找点按钮的人 | 按钮所在卡片 + 操作 | 执行对应操作，原地更新卡片 |
| 业务系统事件 | /api/inbound/{key} | HMAC-SHA256 签名（X-Relay-Timestamp + X-Relay-Signature） | integration + event_id | 收件人的待处理（biz_event） |

## 工具

副作用等级：`read` 只读；`prepare` 准备，本人确认后执行；`write` 执行已确认的操作；`create` 新建（不覆盖，回读核对）；`state` 改助理自己的状态。

### feishu

| 工具 | 能力 | 副作用 | 可能的错误 | 说明 |
|---|---|---|---|---|
| `decide_approval` | approval | prepare | not_found, conflict | 准备批准或驳回一张审批（发卡片给用户确认） |
| `get_approval_detail` | approval | read | not_found | 查看一张审批单的完整表单内容和审批意见（实时从飞书读取） |
| `list_pending_approvals` | approval | read | needs_reauth | 列出等用户审批的单子，每张附一句话说明要批什么 |
| `query_my_approvals` | approval | read | needs_reauth | 查本人的审批历史，用于回答“我发起的那个审批到哪了”“上周批过什么”之类的问题：done 我已审批、initiated 我发起的（含结果）、cc 抄送我的 |
| `read_my_approval` | approval | read | not_found | 读取本人发起、已办或抄送的审批详情（表单、流程进度、意见） |
| `attendance_today` | attendance | read | app_scope | 查用户今天的考勤打卡情况 |
| `list_base_fields` | base | read | app_scope, no_access, not_found | 看多维表格一张数据表有哪些字段、什么类型、单选/多选有哪些选项 |
| `list_base_records` | base | read | app_scope, no_access, not_found | 以本人权限读取：读取多维表格记录，可指定 view_id；page_token 继续 |
| `list_base_tables` | base | read | app_scope, no_access, not_found | 以本人权限读取：列出多维表格的数据表 |
| `prepare_add_base_record` | base | prepare | app_scope, no_access | 准备往多维表格新增一条记录（例如提交每天的工作餐、登记一条需求），以用户本人身份提交 |
| `find_meeting_times` | calendar | read | needs_reauth | 查用户和参会人的忙闲，找出接下来几天工作时间里大家都有空的时间段 |
| `get_meeting_responses` | calendar | read | not_found, unsupported | 查一个会议每位参会人的回复情况（接受/拒绝/待定/还没回复） |
| `list_calendar_events` | calendar | read | not_connected, needs_reauth | 查用户飞书日历里的日程（实时） |
| `prepare_add_attendees` | calendar | prepare | not_found, unsupported | 准备给一个已有会议加参会人 |
| `prepare_cancel_meeting` | calendar | prepare | not_found, unsupported | 准备取消一个会议（会通知参会人） |
| `prepare_meeting` | calendar | prepare | — | 准备一个会议邀请（用户为组织者，带视频会议） |
| `prepare_reschedule` | calendar | prepare | not_found, unsupported | 准备把一个会议改到新的时间（会通知参会人） |
| `respond_to_invitation` | calendar | prepare | not_found, unsupported | 准备回复一个会议邀请（接受/待定/拒绝），发确认卡片给用户，用户确认后才真正回复 |
| `find_person` | contact | read | — | 按名字（或企业邮箱）找同事，得到能用来发消息、建任务、约会的身份 |
| `list_department_members` | contact | read | app_scope | 列出一个部门的直属成员和职位 |
| `person_profile` | contact | read | not_found | 查一位同事的资料：职位、所在部门、直属上级、企业邮箱。约定：实时查通讯录，不要从邮件里推测职位和上级。 |
| `search_departments` | contact | read | app_scope | 按名称搜部门，返回部门负责人、人数和所属上级部门。约定：实时查通讯录，不要从邮件里推测。 |
| `prepare_append_doc_text` | docs | prepare | app_scope, no_access, not_found | 准备操作，展示内容并等待用户确认：在指定文档内容块末尾追加纯文本段落（不解析 Markdown），block_id 通常等于 document_id。约定：先读原文确认目标位置。 |
| `prepare_create_doc` | docs | prepare | app_scope, no_access | 准备操作，展示内容并等待用户确认：创建空白新版文档；创建成功后可另行确认追加正文 |
| `read_feishu_doc` | docs | read | no_access, not_found, unsupported | 读取飞书链接的内容：新版文档正文、知识库节点、云空间上传的原始文件（/file/ 链接，Excel、Word、PDF）、妙记（/minutes/ 链接，会议录制的文字记录，带说话人），以及电子表格、多维表格的结构（表格再用 read_sheet_range 读数据） |
| `search_docs` | docs | read | needs_reauth, limit | 用用户本人的权限分页搜索飞书云文档和知识库。约定：返回的只是片段，不能拼起来当原文；有链接时直接用 read_feishu_doc。 |
| `list_drive_files` | drive | read | app_scope, no_access, not_found | 以本人权限读取：浏览云空间文件夹；返回 files 和下一页 next_page_token |
| `save_file_to_drive` | drive | create | not_found, app_scope, no_access | 把 Relay 已经生成的文件存进他的飞书云空间（默认“我的空间”，或 folder_url 指定的文件夹） |
| `find_chats` | im | read | limit | 按名称找用户所在的飞书群（以用户身份，机器人不在的群也能找到） |
| `prepare_chat_message` | im | prepare | — | 准备一条飞书消息，发给某位同事（to）或某个群（chat_id，用 find_chats 找）。约定：用你们往来时用的语言写；看不出来时用英文或问他。 |
| `read_chat_messages` | im | read | no_access, not_found | 以用户身份读一个群最近的消息（他在群里能看到的），用来了解大家在讨论什么、有没有人找他、某件事进展如何 |
| `draft_mail_forward` | mail | prepare | not_found | 准备把一封邮件转发给别人（默认带上原附件），以卡片展示给用户确认后才发送。约定：附言用收件人的语言写。 |
| `draft_mail_reply` | mail | prepare | not_found | 为一封邮件起草回复，草稿以卡片形式展示给用户，用户可以直接修改。约定：用原邮件的语言写。 |
| `list_mail_folder` | mail | read | not_connected, needs_reauth | 看某个邮箱文件夹里最近的邮件（例如已发送、草稿、垃圾邮件），只列主题、收发件人和时间 |
| `read_mail` | mail | read | not_found, needs_reauth | 读取一封邮件的全文（任何文件夹都可以） |
| `read_mail_attachment` | mail | read | not_found, unsupported | 读取邮件附件的内容（Excel、Word、PDF、CSV、TXT） |
| `search_mail` | mail | read | not_connected, needs_reauth, limit | 实时搜索用户的飞书邮箱（主题、发件人、正文关键词），覆盖收件箱、已发送、草稿、已删除、垃圾邮件、已归档和自建文件夹 |
| `list_sheet_tabs` | sheets | read | app_scope, no_access, not_found | 列出电子表格的工作表（名称、sheet_id、行列数），再用 read_sheet_range 读数据 |
| `prepare_fill_sheet_cells` | sheets | prepare | app_scope, no_access, not_found | 准备按单元格填写电子表格（例如别人发来让你填的反馈表），展示每格的原值和新值，用户确认后才写入。约定：先用 read_sheet_range 读表头和相关行。 |
| `read_sheet_range` | sheets | read | app_scope, no_access, not_found | 读取电子表格一个范围的值（纯文本），按 `R行号 / 列字母: 值` 返回，空格子省略，可以直接定位单元格（如 S49） |
| `prepare_task` | task | prepare | — | 准备一个飞书任务并指派给同事（或用户自己） |
| `list_wiki_nodes` | wiki | read | app_scope, no_access, not_found | 以本人权限读取：列出知识库子节点；不传 parent_node_token 时列出根节点 |
| `list_wiki_spaces` | wiki | read | app_scope | 以本人权限读取：列出本人可访问的知识空间 |

### relay

| 工具 | 能力 | 副作用 | 可能的错误 | 说明 |
|---|---|---|---|---|
| `confirm_action` | actions | write | not_found, conflict, needs_reauth, app_scope, no_access | 执行一个待确认操作（发送邮件草稿、回复会议邀请） |
| `revise_draft` | actions | prepare | not_found, conflict | 按用户的意见重写一份待发送的邮件草稿；也可以改成回复全部或只回复发件人 |
| `delete_notify_rule` | attention | state | not_found | 删除一条提醒规则（用户说那类事又要正常提醒了） |
| `list_notify_rules` | attention | read | — | 列出用户设过的提醒规则（每条命中过多少件事），以及从他以前的话里整理出、还在等他确认的候选规则。约定：他问“为什么这件事没马上告诉我”时看这里和事项上的提醒档位。 |
| `set_notify_rule` | attention | state | — | 按用户的明确要求设置一类事的提醒方式 |
| `get_collaboration` | collab | read | not_found | 看一份协作的完整内容：要求、交付、验收、共享材料、对方提的修改、提交的结果、变更记录 |
| `list_collaborations` | collab | read | — | 列出用户和同事之间还没结束的协作（他请别人的、别人请他的），以及每份现在轮到谁、能做什么 |
| `request_colleague` | collab | prepare | not_found | 请同一个工作区的同事做一件事（发出协作请求） |
| `respond_collaboration` | collab | prepare | conflict, not_found | 回应或推进一份协作 |
| `create_excel_file` | files | create | — | 生成一个 Excel 文件（.xlsx）给用户：一个或多个工作表，每个有表头和数据行。约定：先把真实数据查到再生成，sources 写清来源；核对只证明文件写对了，不证明数据对，回复里分开说。 |
| `create_ppt_file` | files | create | — | 生成一个 PPT 文件（.pptx，16:9）给用户：可选封面标题，每页一个标题加要点，或一张表格。约定：先把真实数据查到再生成，sources 写清来源；核对只证明文件写对了，不证明数据对，回复里分开说。 |
| `create_word_file` | files | create | — | 生成一个 Word 文件（.docx）给用户：可选总标题，每节一个小标题，下面是段落、要点或一张表格（纪要、报告、说明、通知……）。约定：先把真实数据查到再生成，sources 写清来源；核对只证明文件写对了，不证明数据对，回复里分开说。 |
| `close_followup` | followups | state | not_found | 结束跟进一件事：用户说已经处理了，或者不用再跟了。约定：对方要的东西还没交付（例如要他填表、交材料），只是发了消息说明情况时不要关闭。 |
| `list_followups` | followups | read | — | 列出 Relay 正在替用户跟进的事：等他处理的、他在等别人的 |
| `open_case` | followups | read | not_found | 打开一件事的档案：同一邮件线程里双方的往来和附件、审批单、相关的私聊/群聊、文档链接、相关的会、之前和同一个人的事 |
| `forget` | memory | state | not_found | 删除一条长期记忆 |
| `remember` | memory | state | invalid_input | 把一条信息存入用户的长期记忆，之后的对话都能用上。约定：只记以后还用得上的（岗位、负责的项目和客户、偏好、重要决定）；提醒偏好用 set_notify_rule；密码、密钥、证件号码不记（会被拒绝）。 |
| `search_memory` | memory | read | — | 按语义搜索用户的长期记忆 |
| `answer_mission` | missions | state | not_found | 把用户对某个长期任务提问的回答转给它，任务会马上继续 |
| `ask_user` | missions | state | — | 遇到只有用户能决定的事（缺信息、要他拿主意）时提问 |
| `cancel_mission` | missions | state | not_found | 停止一个长期任务（用户说不用办了） |
| `check_criterion` | missions | state | conflict | 对照验收清单标记一条：做到了（met=true）必须给出证据编号 ref——action:编号（本任务里执行成功的操作）、signal:编号（邮件/消息）或 log:编号（时间线里记下的对方回复）；确定做不到时 met=false 并说明原因 |
| `complete_mission` | missions | state | conflict | 任务完成（或确定办不成）时结束它，并给用户一个结论 |
| `edit_mission_criteria` | missions | state | not_found | 用户要改某个长期任务的验收清单（做到什么才算办成）时使用：传入改好后的完整清单 |
| `list_missions` | missions | read | — | 列出 Relay 正在办的长期任务和它们的进展 |
| `report_progress` | missions | state | — | 在主线里向用户汇报进展 |
| `save_notes` | missions | state | — | 保存这个任务的工作笔记（会覆盖旧的）：关键事实、已经联系过谁、对方怎么说、还差什么 |
| `start_mission` | missions | state | — | 把一件需要持续推进、跨越几小时到几周的事交给 Relay 在后台办，例如“盯着客户A的报价直到他确认”“约张三李四下周开会并跟到都接受”“每天下班前看看这几个需求有没有进展” |
| `update_plan` | missions | state | — | 写下或更新这个任务的计划（完整列表，会覆盖旧的） |
| `wait_for_reply` | missions | state | — | 等对方回复再继续：mail 等某封邮件线程有新回信；chat 等某个会话（群聊或私聊）里对方发言，不传 chat_id 时默认等本任务最近一条发出的消息所在的会话 |
| `wait_until` | missions | state | — | 这一轮先到这里，过一段时间再醒来看看（例如明早再查一次） |
| `create_scheduled_task` | tasks | state | — | 创建定时任务。约定：创建后告诉他下一次执行的时间。 |
| `delete_scheduled_task` | tasks | state | not_found | 删除一个定时任务 |
| `list_scheduled_tasks` | tasks | read | — | 列出用户的定时任务 |

### mac

| 工具 | 能力 | 副作用 | 可能的错误 | 说明 |
|---|---|---|---|---|
| `list_local_files` | local_files | read | offline, not_connected, no_access | 列出用户 Mac 上某个授权文件夹里的文件（可以进子文件夹，可以按文件名关键字找） |
| `local_folders` | local_files | read | — | 看用户在 Mac 客户端里授权了哪些文件夹（读 / 写），以及 Mac 现在在不在线 |
| `read_local_file` | local_files | read | offline, not_connected, no_access, not_found, unsupported | 读取用户 Mac 上授权文件夹里的一个文件（xlsx、docx、pdf、csv、txt 等），返回文字内容和文件版本 |
| `save_file_to_mac` | local_files | create | offline, not_connected, no_access, not_found | 把 Relay 生成的文件（Excel、Word、PPT）存进用户 Mac 上授权写入的文件夹 |

## 错误码

| 错误码 | 原因 | 怎么处理 |
|---|---|---|
| `not_connected` | 这个数据源还没有接入 | 请管理员在“工作区设置”里接入，或在设置里连接自己的账号 |
| `needs_reauth` | 他的授权过期了，或者授权里缺这一项 | 请重新登录一次（授权页里同意即可） |
| `app_scope` | 应用还没有开通这项权限 | 需要管理员在飞书后台为 Relay 应用开通对应权限并发布，然后他重新登录一次 |
| `no_access` | 他本人对这份资源没有权限（文件、表格、审批……） | 需要找资源的所有者给他开通 |
| `not_found` | 找不到这份资源 | 请核对链接或编号 |
| `invalid_input` | 参数不对 | 按工具的要求重新提供 |
| `unsupported` | Relay 还没有这个功能 | 如实告诉他还不支持，不要说成没有权限 |
| `conflict` | 状态已经变了（别人刚处理过、文件被改过、版本对不上） | 刷新后再看是否还需要做 |
| `offline` | 他的设备（Mac 客户端）现在不在线 | 打开 Relay 客户端后再试 |
| `limit` | 这一轮同一类查找已经查了好几次 | 停下来，告诉他查过哪些地方，问他资料在哪 |
| `precondition` | 前置条件不满足 | 按说明补齐条件后再试 |
| `upstream` | 外部服务暂时出错 | 稍后再试 |
| `internal` | Relay 内部错误 | 稍后再试；一直出错请联系管理员 |

查找类工具（search_mail、search_docs、find_chats）每轮对话最多调用 3 次，之后返回 `limit`。
