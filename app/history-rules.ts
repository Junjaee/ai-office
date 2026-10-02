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

// ───────────────────────── 하루 집계 (대시보드 요약 칸·시간대별 막대) ─────────────────────────

export type DayItem = { status: string; conclusion: string | null; startedAt: string | null; durationSec: number | null };

/** 요약 칸 제목: 오늘 실행 / M월 D일 실행 */
export function runsTitle(date: string, today: string): string {
  if (date === today) return "오늘 실행";
  const [, m, d] = date.split("-");
  return `${Number(m)}월 ${Number(d)}일 실행`;
}

/** 그 날 실행 횟수·성공·실패·평균 소요(초). 실패 = 끝났는데 성공·취소·건너뜀이 아닌 것(이력 표의 "오류"와 같은 기준) */
export function dayStats(items: DayItem[]): { runs: number; ok: number; failed: number; avgSec: number | null } {
  let ok = 0, failed = 0, sum = 0, n = 0;
  for (const it of items) {
    if (it.status === "completed") {
      if (it.conclusion === "success") ok += 1;
      else if (it.conclusion !== "cancelled" && it.conclusion !== "skipped") failed += 1;
    }
    if (typeof it.durationSec === "number") { sum += it.durationSec; n += 1; }
  }
  return { runs: items.length, ok, failed, avgSec: n ? sum / n : null };
}

/** KST 0~23시별 실행 횟수(시작 시각 기준). 시작 시각이 없는 줄은 뺀다 */
export function hourBuckets(items: Pick<DayItem, "startedAt">[]): number[] {
  const out = new Array<number>(24).fill(0);
  for (const it of items) {
    const ms = it.startedAt ? Date.parse(it.startedAt) : NaN;
    if (Number.isNaN(ms)) continue;
    out[new Date(ms + KST_OFFSET_MS).getUTCHours()] += 1;
  }
  return out;
}

/** 막대 위 한 줄: "합계 5회 · 가장 많은 시간 09시". 0회면 빈 문자열 */
export function bucketsText(buckets: number[]): string {
  const total = buckets.reduce((a, b) => a + b, 0);
  if (!total) return "";
  const peak = buckets.indexOf(Math.max(...buckets));
  return `합계 ${total.toLocaleString("ko-KR")}회 · 가장 많은 시간 ${String(peak).padStart(2, "0")}시`;
}
