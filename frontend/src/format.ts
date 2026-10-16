const WEEKDAYS = "日一二三四五六";

export function timeOf(value: string | null | undefined) {
  if (!value) return "";
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function dayLabel(value: string) {
  const date = new Date(value);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  if (date.toDateString() === today.toDateString()) return "今天";
  if (date.toDateString() === tomorrow.toDateString()) return "明天";
  return `${date.getMonth() + 1}月${date.getDate()}日 周${WEEKDAYS[date.getDay()]}`;
}

export function relative(value: string | null | undefined) {
  if (!value) return "";
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return dayLabel(value);
}

export function greeting() {
  const hour = new Date().getHours();
  if (hour < 5) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 13) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

// 工具名 → 完成时 / 进行时的说法
const STEPS: Record<string, [string, string]> = {
  list_calendar_events: ["查看了日历", "正在查看日历"],
  search_mail: ["搜了邮箱", "正在搜邮箱"],
  list_mail_folder: ["看了邮件文件夹", "正在看邮件文件夹"],
  read_mail: ["读了邮件", "正在读邮件"],
  draft_mail_reply: ["起草了回复", "正在起草回复"],
  revise_draft: ["修改了草稿", "正在修改草稿"],
  confirm_action: ["执行了操作", "正在执行"],
  respond_to_invitation: ["准备了会议回复", "正在准备会议回复"],
  list_pending_approvals: ["查看了审批", "正在查看审批"],
  attendance_today: ["查看了考勤", "正在查看考勤"],
  search_docs: ["搜索了文档", "正在搜索文档"],
  read_feishu_doc: ["读了文档", "正在读文档"],
  remember: ["记住了一件事", "正在记下来"],
  forget: ["删除了一条记忆", "正在删除记忆"],
  search_memory: ["回想了一下", "正在回想"],
  create_scheduled_task: ["创建了定时任务", "正在创建定时任务"],
  list_scheduled_tasks: ["查看了定时任务", "正在查看定时任务"],
  delete_scheduled_task: ["删除了定时任务", "正在删除定时任务"],
  start_mission: ["接下了长期任务", "正在接下长期任务"],
  list_missions: ["查看了长期任务", "正在查看长期任务"],
  answer_mission: ["转告了长期任务", "正在转告长期任务"],
  cancel_mission: ["停止了长期任务", "正在停止长期任务"],
  find_person: ["找了同事", "正在找同事"],
  find_meeting_times: ["查了大家的空闲时间", "正在查大家的空闲时间"],
  prepare_chat_message: ["准备了一条消息", "正在准备消息"],
  prepare_task: ["准备了飞书任务", "正在准备飞书任务"],
  prepare_meeting: ["准备了会议邀请", "正在准备会议邀请"],
  list_followups: ["查看了跟进事项", "正在查看跟进事项"],
  close_followup: ["结束了一件跟进", "正在结束跟进"],
  get_approval_detail: ["读了审批单", "正在读审批单"],
  decide_approval: ["准备了审批决定", "正在准备审批决定"],
  get_meeting_responses: ["查了参会人的回复", "正在查参会人的回复"],
  search_departments: ["查了组织架构", "正在查组织架构"],
  find_chats: ["找了群", "正在找群"],
  read_chat_messages: ["读了群消息", "正在读群消息"],
  list_department_members: ["查了部门成员", "正在查部门成员"],
  person_profile: ["查了同事资料", "正在查同事资料"],
  prepare_reschedule: ["准备了改期", "正在准备改期"],
  prepare_cancel_meeting: ["准备了取消会议", "正在准备取消会议"],
  prepare_add_attendees: ["准备了加参会人", "正在准备加参会人"],
};

export function stepDone(name: string) {
  return STEPS[name]?.[0] ?? name;
}

export function stepActive(name: string) {
  return STEPS[name]?.[1] ?? name;
}
