/** 회의 발언 요약(speech) 깨우기 판정 — 구글 캘린더의 재경위·예결위 일정만 본다 (순수 함수 + 캘린더 fetch).
 *
 * Worker 는 국회 사이트를 부르지 않는다(설계 3절): Cloudflare 엣지에서 webcast 가 열리는지 확인된 바 없고,
 * "이준석 위원이 질의하는 날인지"는 HWP 표를 읽어야 알 수 있어 파이썬(워크플로)이 판정한다.
 * 여기서는 ① 캘린더 일정의 감시 시간대인가 ② 그 채널 실행이 이미 돌고 있나 ③ 오늘 "건너뜀/끝남" 표시가 있나
 * ④ 마지막 깨움 뒤 10분이 지났나 — 네 가지만 본다. 설계: docs/superpowers/specs/2026-11-05-회의-발언-요약-알림-design.md 8절.
 */
import type { FetchLike } from "./gmail.ts";

/** 일정 제목에 든 단어 → 생중계 채널(xcode). 채널을 더하면 그 위원회도 감시한다 */
export const WATCH_CHANNELS: Record<string, string> = { "재경위": "65", "예결위": "21" };
/** 530호 일정 (비공개) — automations/weekend/config.actions.yaml 의 calendar_id 와 같다 */
export const SPEECH_CALENDAR_ID = "1cad154d55cbc50b2d6f7205d0e583e845c725d89a89177461c814662e6815c2@group.calendar.google.com";
export const SPEECH_WORKFLOW = "speech.yml";
/** 같은 채널을 다시 깨우기 전에 쉬는 시간 — 실행이 바로 죽을 때 1분마다 폭주하지 않게 */
export const SPEECH_COOLDOWN_MS = 10 * 60 * 1000;
/** 감시 시간대: 일정 시작 10분 전 ~ 끝 3시간 뒤(회의는 늘 늦게 끝나고 저녁에 속개하기도 한다 — 2026-11-05 실측) */
export const WINDOW_BEFORE_MS = 10 * 60 * 1000;
export const WINDOW_AFTER_MS = 3 * 60 * 60 * 1000;
/** 캘린더는 1시간에 한 번만 읽는다 */
const MEETINGS_CACHE_MS = 60 * 60 * 1000;

export type CalendarItem = {
  summary?: string;
  start?: { dateTime?: string; date?: string };
  end?: { dateTime?: string; date?: string };
};
export type Meeting = { title: string; startMs: number; endMs: number; xcodes: string[] };

const RUNNING = new Set(["in_progress", "queued", "waiting", "requested", "pending"]);
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];

/** 제목에 재경위/예결위가 들어 있고 시각이 있는(종일 아닌) 일정만 */
export function meetingsFrom(items: CalendarItem[]): Meeting[] {
  const out: Meeting[] = [];
  for (const it of items ?? []) {
    const title = (it.summary ?? "").trim();
    const xcodes = Object.entries(WATCH_CHANNELS).filter(([word]) => title.includes(word)).map(([, x]) => x);
    if (xcodes.length === 0) continue;
    const startMs = Date.parse(it.start?.dateTime ?? "");
    const endMs = Date.parse(it.end?.dateTime ?? "");
    if (Number.isNaN(startMs) || Number.isNaN(endMs)) continue;   // 종일 일정(date 만) 은 시간대를 모른다 → 무시
    out.push({ title, startMs, endMs, xcodes });
  }
  return out;
}

export function watchWindow(m: Meeting): { fromMs: number; toMs: number } {
  return { fromMs: m.startMs - WINDOW_BEFORE_MS, toMs: m.endMs + WINDOW_AFTER_MS };
}

/** 지금 감시 시간대인 채널들 — 같은 채널이 여럿이면 가장 늦은 끝 */
export function activeChannels(meetings: Meeting[], nowMs: number): { xcode: string; windowEndMs: number }[] {
  const ends = new Map<string, number>();
  for (const m of meetings) {
    const { fromMs, toMs } = watchWindow(m);
    if (nowMs < fromMs || nowMs > toMs) continue;
    for (const x of m.xcodes) ends.set(x, Math.max(ends.get(x) ?? 0, toMs));
  }
  return [...ends.entries()].map(([xcode, windowEndMs]) => ({ xcode, windowEndMs }));
}

/** 그 채널의 speech 실행이 지금 돌고 있나(queued 포함). run-name 은 "speech · <xcode> · <request_id>" */
export function isRunning(runs: { path: string; status: string; display_title: string }[], xcode: string): boolean {
  return runs.some((r) => r.path.endsWith(`/${SPEECH_WORKFLOW}`) && RUNNING.has(r.status)
    && (r.display_title ?? "").includes(` · ${xcode} · `));
}

export function shouldWakeSpeech(a: { active: boolean; running: boolean; marked: boolean; lastRunMs: number | null; nowMs: number }): boolean {
  if (!a.active || a.running || a.marked) return false;
  return a.lastRunMs === null || a.nowMs - a.lastRunMs >= SPEECH_COOLDOWN_MS;
}

/** 다음 회의 한 줄 — "11/9(월) 10:00 예결위 전체회의" (KST) */
export function nextMeetingLabel(meetings: Meeting[], nowMs: number): string | null {
  const next = meetings.filter((m) => m.startMs > nowMs).sort((a, b) => a.startMs - b.startMs)[0];
  if (!next) return null;
  const k = new Date(next.startMs + 9 * 60 * 60 * 1000);
  const hh = String(k.getUTCHours()).padStart(2, "0");
  const mm = String(k.getUTCMinutes()).padStart(2, "0");
  return `${k.getUTCMonth() + 1}/${k.getUTCDate()}(${WEEKDAY[k.getUTCDay()]}) ${hh}:${mm} ${next.title}`;
}

export function markerKey(kind: "skip" | "done", dateKst: string, xcode: string): string {
  return `speech/${kind}/${dateKst}-${xcode}`;
}

export function stateKey(key: string): string {
  return `speech/state/${key}.json`;
}

let meetingsCache: { at: number; meetings: Meeting[] } | null = null;

export function resetMeetingsCache(): void {
  meetingsCache = null;
}

/** 어제~2주 뒤의 일정을 받아 Meeting 으로. 실패는 예외(부르는 쪽이 calendarError 로 보인다). 1시간 캐시 */
export async function fetchMeetings(token: string, fetchImpl: FetchLike, nowMs: number): Promise<Meeting[]> {
  if (meetingsCache && nowMs - meetingsCache.at < MEETINGS_CACHE_MS) return meetingsCache.meetings;
  const params = new URLSearchParams({
    timeMin: new Date(nowMs - 24 * 60 * 60 * 1000).toISOString(),
    timeMax: new Date(nowMs + 14 * 24 * 60 * 60 * 1000).toISOString(),
    singleEvents: "true",
    orderBy: "startTime",
    maxResults: "50",
  });
  const url = `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(SPEECH_CALENDAR_ID)}/events?${params}`;
  const res = await fetchImpl(url, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`캘린더 읽기 실패 (HTTP ${res.status})`);
  const data = (await res.json()) as { items?: CalendarItem[] };
  const meetings = meetingsFrom(data.items ?? []);
  meetingsCache = { at: nowMs, meetings };
  return meetings;
}
