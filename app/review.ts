"use client";
// 주제 검토 칸: /api/review 조회 훅 + 순수 규칙. 파일 모양은 automations/insta/insta_review.py 와 같다.
import { useCallback, useEffect, useState } from "react";

export type ReviewCandidate = {
  id: string;
  key: string;
  title: string;
  /** 편집장(모델)이 붙인 한국어 제목 — 있으면 이걸 크게 보여 준다 */
  title_ko?: string;
  link: string;
  source: string;
  published?: string;
  summary?: string;
  reason?: string;
  angle?: string;
  /** 미국 소식인데 한국 AI 계정이 아직 안 다룬 것(빈자리) */
  gap?: boolean;
  /** 영상이 딸린 소재(공식 유튜브·X) — 릴스로 게시된다 */
  video?: boolean;
};

export type ReviewQueueItem = {
  id: string;
  key: string;
  title: string;
  link: string;
  source: string;
  due: string;
  status: "queued" | "making" | "done" | "failed" | "cancelled";
  added_at?: string;
  finished_at?: string;
  permalink?: string;
  error?: string;
};

export type ReviewFile = {
  date: string;
  generated_at: string;
  count: number;
  interval_hours?: number;
  candidates: ReviewCandidate[];
  queue: ReviewQueueItem[];
};

export type ReviewResponse = { ws: string; automation: string; file: ReviewFile | null; source: "github" | "static"; checkedAt: string };

export type ReviewState = { data: ReviewFile | null; loading: boolean; error: boolean; checkedAt: string | null };

const REFRESH_MS = 60_000;

/** 하루 게시 상한 (automations/insta/config.actions.yaml 의 max_per_day 와 같게) */
export const MAX_PER_DAY = 3;
/** 고정 게시 시간대 (config.actions.yaml 의 slots 와 같게, 사용자 결정 2026-09-12) */
export const SLOTS = ["07:30", "12:30", "18:30"];

/** 고른 개수 N → 24÷N 시간 간격, 단 하루 상한보다 촘촘해지지 않는다 (사용자 결정 2026-09-11 · 상한 2026-09-12). 소수 첫째 자리까지 */
export function intervalHours(n: number, maxPerDay = MAX_PER_DAY): number {
  if (n <= 0) return 0;
  return Math.round(Math.max(24 / n, 24 / maxPerDay) * 10) / 10;
}

/** 간격 설명 문구: 1개면 "바로 게시", 3개면 "바로 1개 + 8시간마다", 상한을 넘으면 "하루 3개씩 · N일"  */
export function intervalText(n: number, maxPerDay = MAX_PER_DAY): string {
  if (n <= 0) return "";
  void maxPerDay;
  const days = Math.ceil(n / SLOTS.length);
  return n === 1 ? "다음 빈 시간대에 게시" : `다음 빈 시간대부터 차례로 (${days}일)`;
}

export const QUEUE_LABEL: Record<ReviewQueueItem["status"], { text: string; cls: string }> = {
  queued: { text: "예약", cls: "idle" },
  making: { text: "만드는 중", cls: "running" },
  done: { text: "게시됨", cls: "done" },
  failed: { text: "실패", cls: "error" },
  cancelled: { text: "취소", cls: "idle" },
};

/** 후보 중 이미 예약·진행·게시된 것의 id */
export function busyIds(file: ReviewFile | null): Set<string> {
  const out = new Set<string>();
  for (const q of file?.queue ?? []) if (q.status === "queued" || q.status === "making" || q.status === "done") out.add(q.id);
  return out;
}

export function dueText(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const d = new Date(t);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const hm = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  return sameDay ? hm : `${d.toLocaleDateString("ko-KR", { month: "numeric", day: "numeric" })} ${hm}`;
}

async function fetchReview(ws: string, automation: string): Promise<ReviewResponse> {
  const r = await fetch(`/api/review?ws=${encodeURIComponent(ws)}&automation=${encodeURIComponent(automation)}&t=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as ReviewResponse;
}

/** 개발용 ?mock=… 가짜 후보 */
function mockReview(): ReviewFile {
  const now = new Date();
  const mk = (i: number): ReviewCandidate => ({
    id: `0000000${i}`.slice(-8),
    key: `https://example.test/${i}`,
    title: `Gemini new feature ${i + 1}`,
    title_ko: `후보 ${i + 1}: 제미나이 새 기능 ${i + 1}가지`,
    link: `https://example.test/${i}`,
    source: i % 2 ? "GeekNews" : "Google AI",
    reason: "직장인이 바로 써먹는 기능이고 공식 화면이 있다",
    angle: "출시 → 장점 → 켜는 법 → 받는 곳",
  });
  return {
    date: now.toISOString().slice(0, 10),
    generated_at: now.toISOString(),
    count: 10,
    interval_hours: 8,
    candidates: Array.from({ length: 10 }, (_, i) => mk(i)),
    queue: [
      { id: "00000000", key: "https://example.test/0", title: "후보 1", link: "#", source: "Google AI", due: now.toISOString(), status: "done", permalink: "https://www.instagram.com/p/x/" },
      { id: "00000001", key: "https://example.test/1", title: "후보 2", link: "#", source: "GeekNews", due: new Date(now.getTime() + 8 * 3_600_000).toISOString(), status: "queued" },
    ],
  };
}

export function useReview(ws: string, automation: string, enabled: boolean): ReviewState & { refresh: () => void } {
  const [state, setState] = useState<ReviewState>({ data: null, loading: enabled, error: false, checkedAt: null });
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const mock = new URLSearchParams(window.location.search).get("mock");
    const load = async () => {
      if (mock) {
        setState({ data: mock === "static" || mock === "no_token" ? null : mockReview(), loading: false, error: false, checkedAt: new Date().toISOString() });
        return;
      }
      try {
        const res = await fetchReview(ws, automation);
        if (alive) setState({ data: res.file, loading: false, error: false, checkedAt: res.checkedAt });
      } catch {
        if (alive) setState((s) => ({ ...s, loading: false, error: true }));
      }
    };
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [ws, automation, enabled, tick]);

  return { ...state, refresh };
}
