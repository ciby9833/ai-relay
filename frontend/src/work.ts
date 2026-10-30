import { useCallback, useEffect, useState } from "react";
import { notifyNew } from "./notify";
import { api, type Board, type FollowUp, type HomeStatus, type Meeting, type MeetingsData, type ProgressData } from "./api";

/** 待处理、会议、进展的同一份数据：顶部入口、侧栏列表、详情都读它，状态只有一份。 */
export interface Work {
  board: Board | null;
  status: HomeStatus | null;
  meetings: MeetingsData | null;
  progress: ProgressData | null;
  error: boolean;
  loadedAt: Date | null;
  refresh: () => Promise<void>;
}

export function useWork(enabled: boolean): Work {
  const [board, setBoard] = useState<Board | null>(null);
  const [status, setStatus] = useState<HomeStatus | null>(null);
  const [meetings, setMeetings] = useState<MeetingsData | null>(null);
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const [error, setError] = useState(false);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [b, home, m, p] = await Promise.all([api.board(), api.home(), api.meetings(), api.progress()]);
      setBoard({ me: b?.me ?? [], others: b?.others ?? [], relay: b?.relay ?? [] });
      setStatus(home?.status ?? null);
      notifyNew(home?.messages);  // 新的主动提醒：标签页在后台时弹浏览器通知（他打开了开关的话）
      setMeetings({ upcoming: m?.upcoming ?? [], recent: m?.recent ?? [] });
      setProgress({ days: p?.days ?? [], notes: p?.notes ?? [] });
      setError(false);
      setLoadedAt(new Date());
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [enabled, refresh]);

  return { board, status, meetings, progress, error, loadedAt, refresh };
}

/** 现在要处理：紧急、今天到期（或已过期）、他说过要立刻知道的 */
export function isNow(item: FollowUp) {
  if (item.importance === "urgent" || item.attention === "now") return true;
  if (!item.due_at) return false;
  const end = new Date();
  end.setHours(23, 59, 59, 999);
  return new Date(item.due_at).getTime() <= end.getTime();
}

export function sameDay(iso: string | null, day: Date) {
  return !!iso && new Date(iso).toDateString() === day.toDateString();
}

/** 同一天里时间重叠的会（只提示，不替他拒绝） */
export function conflicts(meeting: Meeting, all: Meeting[]): Meeting[] {
  if (!meeting.start || meeting.all_day) return [];
  const start = new Date(meeting.start).getTime();
  const end = meeting.end ? new Date(meeting.end).getTime() : start + 3600_000;
  return all.filter((m) => {
    if (m.id === meeting.id || !m.start || m.all_day || m.rsvp === "decline") return false;
    const s = new Date(m.start).getTime();
    const e = m.end ? new Date(m.end).getTime() : s + 3600_000;
    return s < end && start < e;
  });
}

/** 展示上的分组：同一种审批（例如 4 张新功能申请）放在一起看，每张仍各自确认，互不影响 */
export function approvalGroup(item: FollowUp): string | null {
  if (item.kind !== "approval") return null;
  const name = item.title.split("：").slice(1).join("：").trim();
  return name || null;
}

/** 邮件里的事（要回的、要看的、在等对方回信的）：单独放在“邮件”里，不混在待处理 */
export function isMail(item: FollowUp) {
  return !!item.is_mail;
}
