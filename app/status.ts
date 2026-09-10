"use client";
// 자동화가 커밋한 /status/*.json 을 읽어 실제 상태로 만든다 (60초마다 재조회)
import { useEffect, useState } from "react";
import { deriveDeptStatus, summarize, type RealDeptStatus, type RealStatus, type Summary } from "./status-rules";
import { currentWorkspaceId } from "./workspaces";

export type RealState = {
  byDept: Record<string, RealStatus>;
  status: Record<string, RealDeptStatus>;
  summary: Summary;
  loadedAt: Date | null;
};

const EMPTY: RealState = { byDept: {}, status: {}, summary: summarize([]), loadedAt: null };
const POLL_MS = 60_000;

export async function fetchRealStatus(): Promise<RealState> {
  const bust = `?t=${Date.now()}`;
  const base = `/status/${currentWorkspaceId()}`;
  const index = (await (await fetch(`${base}/index.json${bust}`)).json()) as { automations: string[] };
  const files = await Promise.all(
    (index.automations ?? []).map(async (id) => {
      try {
        const r = await fetch(`${base}/${id}.json${bust}`);
        if (!r.ok) return null;
        return (await r.json()) as RealStatus;
      } catch {
        return null;
      }
    }),
  );
  const all = files.filter((x): x is RealStatus => Boolean(x && x.id && x.dept));
  const now = new Date();
  const byDept: Record<string, RealStatus> = {};
  const status: Record<string, RealDeptStatus> = {};
  for (const s of all) {
    byDept[s.dept] = s;
    status[s.dept] = deriveDeptStatus(s, now);
  }
  const summary = summarize(all, now);
  status.ops = summary.opsStatus;
  status.secretary = summary.total ? (summary.error ? "오류" : "완료") : "대기";
  return { byDept, status, summary, loadedAt: now };
}

export function useRealStatus(): RealState {
  const [state, setState] = useState<RealState>(EMPTY);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchRealStatus()
        .then((s) => {
          if (alive) setState(s);
        })
        .catch((e) => console.warn("상태 파일 조회 실패", e));
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);
  return state;
}
