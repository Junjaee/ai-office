// 실행 이력(날짜별) 규칙 — 순수. node --test 가 직접 실행하므로 값 import 금지(import type 만).

/** 일지·실행 기록이 시작된 날(KST). 화면 달력의 최소값, Worker 도 같은 값을 쓴다 */
export const HISTORY_START = "2026-09-10";

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** KST 오늘 "YYYY-MM-DD" */
export function kstToday(nowMs: number): string {
  return new Date(nowMs + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/** 날짜를 days 만큼 옮긴다 (달·해 넘김 포함) */
export function shiftDate(date: string, days: number): string {
  return new Date(Date.parse(`${date}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/** start~today 밖이면 가까운 끝으로 */
export function clampDate(date: string, start: string, today: string): string {
  if (date < start) return start;
  if (date > today) return today;
  return date;
}

export function historyTitle(date: string, today: string): string {
  if (date === today) return "오늘 실행 이력";
  const [, m, d] = date.split("-");
  return `${Number(m)}월 ${Number(d)}일 실행 이력`;
}

export type HistoryView = {
  loading: boolean;
  error: boolean;
  source: "github" | "archive" | "static" | null;
  partial: boolean;
  count: number;
  isToday: boolean;
};

/** 표 대신(replacesTable) 또는 표 위에 보일 한 줄. 표만 보이면 null */
export function historyMessage(v: HistoryView): { text: string; replacesTable: boolean } | null {
  if (v.error && v.count === 0) return { text: "이력을 불러오지 못했어요 · 잠시 뒤 다시 시도해 주세요", replacesTable: true };
  if (v.loading && v.source === null) return { text: "불러오는 중…", replacesTable: true };
  if (v.source === "static") return { text: "실행 이력은 GitHub 연결이 있을 때만 보여요.", replacesTable: true };
  if (v.count === 0) {
    const text = v.partial ? "GitHub 응답이 없어 이 날 기록을 다 불러오지 못했어요." : v.isToday ? "오늘은 아직 실행한 게 없어요." : "이 날은 실행한 게 없어요.";
    return { text, replacesTable: true };
  }
  if (v.partial) return { text: "GitHub 응답이 없어 일부만 보여요.", replacesTable: false };
  return null;
}
