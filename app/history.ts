"use client";
// 실행 이력(날짜별): /api/history 조회 훅. 오늘을 보고 있으면 30초마다(탭이 보일 때만) 다시 부른다.
import { useEffect, useMemo, useState } from "react";
import { HISTORY_START, kstToday } from "./history-rules";
import type { WorkspaceConfig } from "./workspaces/types";

/** 이력 한 줄 (worker/run-api.ts HistoryItem 과 같은 모양) */
export type HistoryItem = {
  id: string;
  automationId: string;
  status: string;
  conclusion: string | null;
  trigger: "manual" | "schedule" | "local" | "other";
  requestId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  url: string | null;
  summary: string | null;
  /** 실제로 걸린 시간(일지). 실행기 대기 시간은 빠진다 */
  durationSec: number | null;
};

/** Worker `/api/history` 응답 (worker/run-api.ts HistoryBody 와 같은 모양) */
export type HistoryResponse = {
  date: string;
  today: string;
  start: string;
  items: HistoryItem[];
  source: "github" | "archive" | "static";
  partial: boolean;
  checkedAt: string;
};

export type HistoryState = {
  /** 보고 있는 날짜 */
  date: string;
  today: string;
  /** 보고 있는 날짜의 응답만 (날짜를 막 바꾼 뒤에는 null) */
  data: HistoryResponse | null;
  loading: boolean;
  error: boolean;
};

const TODAY_REFRESH_MS = 30_000;

async function fetchHistory(ws: string, date: string): Promise<HistoryResponse> {
  const r = await fetch(`/api/history?ws=${encodeURIComponent(ws)}&date=${date}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as HistoryResponse;
}

/** 개발용: ?mock=… 일 때 날짜별 가짜 이력 (id 는 날짜·자동화마다 겹치지 않게) */
function mockHistory(mode: string, ws: WorkspaceConfig, date: string, today: string): HistoryResponse {
  const base = { date, today, start: HISTORY_START, checkedAt: new Date().toISOString(), partial: false };
  if (mode === "static" || mode === "no_token") return { ...base, items: [], source: "static" };
  if (mode === "empty" || mode === "idle") return { ...base, items: [], source: "github" };
  const day = Date.parse(`${date}T00:00:00+09:00`);
  const at = (h: number, m: number) => new Date(day + (h * 60 + m) * 60_000).toISOString();
  const items: HistoryItem[] = [];
  ws.automations
    .filter((a) => a.workflow)
    .forEach((a, i) => {
      const id = (n: number) => `${date.replace(/-/g, "")}${i}${n}`;
      const url = (n: number) => `https://github.com/Junjaee/ai-office/actions/runs/${id(n)}`;
      items.push({ id: id(1), automationId: a.id, status: "completed", conclusion: "success", trigger: "manual", requestId: "req-mock-1", startedAt: at(16, 4 + i), completedAt: at(16, 5 + i), url: url(1), summary: "신규 12건, 실패 0건, 18초", durationSec: 18 });
      items.push({ id: id(2), automationId: a.id, status: "completed", conclusion: "success", trigger: "schedule", requestId: null, startedAt: at(9, i), completedAt: at(9, 2 + i), url: url(2), summary: "신규 3건, 확정본 교체 1건, 실패 0건, 1.9분 · 결과가 길면 말줄임으로 보입니다", durationSec: 114 });
      items.push({ id: id(3), automationId: a.id, status: "completed", conclusion: "cancelled", trigger: "manual", requestId: "req-mock-2", startedAt: at(8, i), completedAt: at(8, 1 + i), url: url(3), summary: null, durationSec: null });
      if (date !== today) {
        items.push({ id: `local:${a.id}:${at(7, i)}`, automationId: a.id, status: "completed", conclusion: "failure", trigger: "local", requestId: null, startedAt: at(7, i), completedAt: at(7, 3 + i), url: null, summary: "이 PC 에서 직접 실행 · 실패 예시", durationSec: 180 });
      }
    });
  items.sort((x, y) => Date.parse(y.startedAt ?? "") - Date.parse(x.startedAt ?? ""));
  return { ...base, items, source: "github" };
}

/** selected 가 null 이면 오늘 */
export function useHistory(ws: WorkspaceConfig, selected: string | null): HistoryState {
  const today = kstToday(Date.now());
  const date = selected ?? today;
  const mock = useMemo(() => (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("mock") : null), []);
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    const load = async () => {
      setLoading(true);
      try {
        const body = mock ? mockHistory(mock, ws, date, today) : await fetchHistory(ws.id, date);
        if (!alive) return;
        setData(body);
        setError(false);
      } catch {
        if (alive) setError(true);
      } finally {
        if (alive) setLoading(false);
      }
      if (alive && date === today) timer = window.setTimeout(tick, TODAY_REFRESH_MS);
    };
    const tick = () => {
      if (document.visibilityState === "visible") void load();
      else timer = window.setTimeout(tick, TODAY_REFRESH_MS);
    };
    setError(false);
    void load();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [ws, date, today, mock]);

  return { date, today, data: data && data.date === date ? data : null, loading, error };
}
