"use client";
// 관심 종목 판·발굴 판이 같이 쓰는 자료 읽기와 담기/빼기 — /api/stock?view=board, /api/stock/watch. ?mock 이 붙으면 견본 자료(저장 공간 없이 확인용).
import { useCallback, useEffect, useMemo, useState } from "react";
import { normalizeBoard, watchErrorText, type Board } from "../stock-rules";
import { mockBoard } from "../stock-mock";

export type ApiBoard = { market: string; board: Board | null; watch: string[]; checkedAt?: string; lensDays: number };
const MARKET = "us";
const tickers = (v: unknown): string[] => (Array.isArray(v) ? v.filter((t): t is string => typeof t === "string") : []);
const days = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.floor(v) : 0);

/** okNote: 서버에서 담기/빼기가 성공했을 때 보여 줄 문구(화면마다 다르다). 모듈 바깥에 둔 고정 함수를 넘길 것 */
export function useStockBoard(okNote: (t: string, action: "add" | "remove") => string) {
  const [data, setData] = useState<ApiBoard | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const mock = useMemo(() => (typeof window !== "undefined" ? new URLSearchParams(window.location.search).has("mock") : false), []);

  const load = useCallback(async () => {
    if (mock) {
      const m = mockBoard();
      setData({ market: MARKET, board: normalizeBoard(m.board), watch: tickers(m.watch), lensDays: 12 });
      return;
    }
    try {
      const r = await fetch(`/api/stock?market=${MARKET}&view=board&t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status === 503 ? "저장 공간이 아직 연결되지 않았어요" : `자료를 불러오지 못했어요 (HTTP ${r.status})`);
      const j = (await r.json()) as { board?: unknown; watch?: unknown; checkedAt?: string; lensDays?: unknown };
      setData({ market: MARKET, board: normalizeBoard(j.board), watch: tickers(j.watch), checkedAt: j.checkedAt, lensDays: days(j.lensDays) });
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "자료를 불러오지 못했어요");
    }
  }, [mock]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 성공하면 true */
  const change = async (ticker: string, action: "add" | "remove"): Promise<boolean> => {
    const t = ticker.trim().toUpperCase();
    if (!t) return false;
    if (mock) {
      setData((d) => (d ? { ...d, watch: action === "add" ? [...new Set([...d.watch, t])] : d.watch.filter((x) => x !== t) } : d));
      return true;
    }
    setBusy(true);
    setNote("");
    try {
      const r = await fetch("/api/stock/watch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ market: MARKET, ticker: t, action }) });
      const j = (await r.json().catch(() => ({}))) as { watch?: string[]; error?: string };
      if (!r.ok || !j.watch) {
        setNote(watchErrorText(r.status, j.error));
        return false;
      }
      setData((d) => (d ? { ...d, watch: tickers(j.watch) } : d));
      setNote(okNote(t, action));
      return true;
    } catch {
      setNote("잠시 뒤 다시 해 주세요");
      return false;
    } finally {
      setBusy(false);
    }
  };

  return { data, error, busy, note, change, mock };
}
