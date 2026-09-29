"use client";
// 실시간 호가·체결 전광판 — /api/live 를 5초마다 읽어 그린다. 자료는 이 PC 의 녹음기(automations/toss_record/live_board.py)가 보낸 집계값 + 종목별 10단계 호가·최근 체결.
import { useEffect, useMemo, useState } from "react";
import { LABELS, LIVE_TTL_MS, relativeTime, type LiveTaskDoc } from "../status-rules";

type Level = [string, string];                       // [가격, 잔량]
type Trade = [string, string, string, string];       // [시각, 체결가, 수량, B|S|M]
export type LiveItem = {
  code: string; name: string; price: number; prev_close?: number | null; chg_pct?: number | null; strength: number | null; buy_amt: number; sell_amt: number;
  amt_ratio?: number | null; pos?: string; mom15?: number | null; high20?: number | null; prev_high?: number | null;
  ratio: number | null; ask_total: number; bid_total: number; amt: number; n_trades: number; score: number;
  wall: { side: "ask" | "bid"; level: number; price: number; amt: number } | null;
  event: string; event_side?: "ask" | "bid" | ""; parts?: { flow: number; wall: number; event: number; depth: number };
  book: { ts: string; asks: Level[]; bids: Level[] } | null; trades: Trade[];
};
export type LiveBoardDoc = LiveTaskDoc & {
  board?: { at: string; codes_n: number; books: number; trades: number; connections: number; subscribed: number; reconnects: number; window_sec: number; items: LiveItem[] };
};
type ApiLive = { ws: string; automation: string; tasks: Record<string, LiveBoardDoc | null>; checkedAt: string };

type SortKey = "amt_ratio" | "score" | "strength" | "wall" | "amt" | "ratio" | "chg" | "mom15";
const SORTS: { id: SortKey; label: string }[] = [
  { id: "amt_ratio", label: "거래대금 배수(평소 대비)" }, { id: "score", label: "호가 점수" }, { id: "chg", label: "등락률" }, { id: "mom15", label: "15분 흐름" },
  { id: "strength", label: "체결강도" }, { id: "wall", label: "큰 벽" }, { id: "amt", label: "5분 거래대금" }, { id: "ratio", label: "매수/매도 잔량비" },
];
const REFRESH_MS = 5000;

const fmt = (n: number | null | undefined, d = 0) => (n == null || Number.isNaN(n) ? "-" : n.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }));
const num = (s: string) => Number(s) || 0;

function strengthClass(s: number | null): string {
  if (s == null) return "";
  if (s >= 200) return "hot";
  if (s >= 120) return "warm";
  if (s < 60) return "cold";
  return "";
}

export default function LiveBoard({ ws, automation, title, back }: { ws: string; automation: string; title: string; back: string }) {
  const [data, setData] = useState<ApiLive | null>(null);
  const [error, setError] = useState<string>("");
  const [now, setNow] = useState(() => new Date());
  const [sort, setSort] = useState<SortKey>("amt_ratio");
  const [q, setQ] = useState("");
  const [onlySignal, setOnlySignal] = useState(false);
  const [sel, setSel] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(`/api/live?ws=${encodeURIComponent(ws)}&automation=${encodeURIComponent(automation)}&t=${Date.now()}`, { cache: "no-store" });
        if (!r.ok) throw new Error(r.status === 503 ? "실시간 저장소가 아직 연결되지 않았어요" : `HTTP ${r.status}`);
        const j = (await r.json()) as ApiLive;
        if (alive) {
          setData(j);
          setError("");
          setNow(new Date());
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "불러오기 실패");
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
  }, [ws, automation]);

  const rec = data?.tasks.record ?? null;
  const board = rec?.board ?? null;
  const ageMs = rec?.at ? now.getTime() - Date.parse(rec.at) : Number.POSITIVE_INFINITY;
  const liveNow = rec?.state === "running" && ageMs < LIVE_TTL_MS;
  const items = useMemo(() => {
    const list = (board?.items ?? []).filter((it) => (!onlySignal || it.event) && (!q || it.name.includes(q) || it.code.includes(q)));
    const key = (it: LiveItem) =>
      sort === "amt_ratio" ? (it.amt_ratio ?? -1) : sort === "score" ? it.score : sort === "chg" ? (it.chg_pct ?? -999) : sort === "mom15" ? (it.mom15 ?? -999)
        : sort === "strength" ? (it.strength ?? -1) : sort === "wall" ? (it.wall?.amt ?? 0) : sort === "amt" ? it.amt : (it.ratio ?? -1);
    return list.slice().sort((a, b) => key(b) - key(a));
  }, [board, sort, q, onlySignal]);
  const selected = items.find((it) => it.code === sel) ?? board?.items.find((it) => it.code === sel) ?? null;
  const signals = board?.items.filter((it) => it.event).length ?? 0;
  const others = ["candles", "flows"].map((id) => [id, data?.tasks[id] ?? null] as const).filter(([, d]) => d);

  return (
    <main className="live-page">
      <header className="live-head">
        <a className="btn btn-ghost" href={back}>← 사무실로</a>
        <h1>
          <span className={`live-dot ${liveNow ? "on" : rec ? "off" : ""}`} />
          {title}
        </h1>
        <span className="live-when">
          {liveNow ? `${LABELS.running} · ${relativeTime(rec?.at, now) || "방금"} 갱신` : rec?.at ? `${rec.state === "done" ? "오늘 녹음 끝" : "신호 끊김"} · 마지막 ${relativeTime(rec.at, now)}` : "아직 신호가 없어요"}
        </span>
      </header>

      {error ? <p className="live-msg">{error}</p> : null}
      {!board && !error ? <p className="live-msg">{rec ? rec.summary ?? "자료가 없어요" : "녹음이 시작되면 여기에 종목이 나타나요"}</p> : null}

      {board ? (
        <>
          <div className="live-stats">
            <div className="live-stat"><b>{board.codes_n}</b><span>녹음 종목</span></div>
            <div className="live-stat"><b>{fmt(board.books)}</b><span>호가 프레임</span></div>
            <div className="live-stat"><b>{fmt(board.trades)}</b><span>체결</span></div>
            <div className="live-stat"><b>{board.connections} / {board.subscribed}</b><span>연결 · 구독</span></div>
            <div className="live-stat"><b>{signals}</b><span>벽 신호({Math.round(board.window_sec / 60)}분)</span></div>
            {others.map(([id, d]) => (
              <div className="live-stat sub" key={id}><b>{id === "candles" ? "1분봉" : "수급"} {d ? LABELS[d.state === "running" ? "running" : d.state === "done" ? "done" : d.state === "error" ? "error" : "idle"] : ""}</b><span>{d?.summary ?? ""}</span></div>
            ))}
          </div>

          <div className="live-tools">
            <label>정렬 <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>{SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>
            <input placeholder="종목명·코드 찾기" value={q} onChange={(e) => setQ(e.target.value)} />
            <label className="live-check"><input type="checkbox" checked={onlySignal} onChange={(e) => setOnlySignal(e.target.checked)} /> 벽 신호만</label>
            <span className="live-count">{items.length}종목</span>
          </div>

          <div className={`live-body ${selected ? "with-detail" : ""}`}>
            <div className="live-table-wrap">
              <table className="live-table">
                <thead>
                  <tr><th className="num">거래대금 배수</th><th>자리</th><th>종목</th><th className="num">현재가</th><th className="num">등락률</th><th className="num">15분 흐름</th><th className="num">호가 점수</th><th className="num">체결강도</th><th className="num">매수/매도(억)</th><th className="num">잔량비</th><th>가장 큰 벽</th><th>신호</th></tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.code} className={`${strengthClass(it.strength)} ${sel === it.code ? "sel" : ""}`} onClick={() => setSel(sel === it.code ? null : it.code)}>
                      <td className={`num ratio ${(it.amt_ratio ?? 0) >= 4 ? "hot" : (it.amt_ratio ?? 0) >= 2 ? "warm" : ""}`}>{it.amt_ratio == null ? "-" : `${fmt(it.amt_ratio, 1)}배`}</td>
                      <td className="pos">{it.pos ? <span className={`live-pos ${it.pos === "20일 신고가" ? "top" : ""}`}>{it.pos}</span> : <span className="live-none">-</span>}</td>
                      <td>{it.name}<small>{it.code}</small></td>
                      <td className="num">{fmt(it.price)}</td>
                      <td className={`num chg ${(it.chg_pct ?? 0) > 0 ? "up" : (it.chg_pct ?? 0) < 0 ? "down" : ""}`}>{it.chg_pct == null ? "-" : `${it.chg_pct > 0 ? "+" : ""}${fmt(it.chg_pct, 2)}%`}</td>
                      <td className={`num chg ${(it.mom15 ?? 0) > 0 ? "up" : (it.mom15 ?? 0) < 0 ? "down" : ""}`}>{it.mom15 == null ? "-" : `${it.mom15 > 0 ? "+" : ""}${fmt(it.mom15, 2)}%`}</td>
                      <td className={`num score ${it.score > 0 ? "up" : it.score < 0 ? "down" : ""}`} title={it.parts ? `체결 ${it.parts.flow} · 벽 ${it.parts.wall} · 신호 ${it.parts.event} · 잔량 ${it.parts.depth}` : ""}>{it.score > 0 ? "+" : ""}{fmt(it.score, 2)}</td>
                      <td className="num strength">{fmt(it.strength)}</td>
                      <td className="num">{fmt(it.buy_amt, 2)} / {fmt(it.sell_amt, 2)}</td>
                      <td className="num">{it.ask_total === 0 ? "상한가" : it.bid_total === 0 ? "하한가" : fmt(it.ratio, 2)}</td>
                      <td className={it.wall ? (it.wall.side === "bid" ? "wall-bid" : "wall-ask") : ""}>{it.wall ? `${it.wall.side === "ask" ? "매도" : "매수"}${it.wall.level} ${fmt(it.wall.price)}원 · ${fmt(it.wall.amt, 1)}억` : "-"}</td>
                      <td>{it.event ? <span className={`live-chip ${it.event_side === "ask" ? "ask" : "bid"}`}>{it.event}</span> : <span className="live-none">-</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {selected ? (
              <aside className="live-detail">
                <div className="live-detail-head">
                  <h2>{selected.name} <small>{selected.code}</small></h2>
                  <button className="btn btn-ghost" onClick={() => setSel(null)}>닫기</button>
                </div>
                <p className="live-detail-sub">
                  현재가 {fmt(selected.price)}원{selected.chg_pct != null ? ` (${selected.chg_pct > 0 ? "+" : ""}${fmt(selected.chg_pct, 2)}%, 전일 ${fmt(selected.prev_close)}원)` : ""} · 5분 체결강도 {fmt(selected.strength)} · 5분 거래대금 {fmt(selected.amt, 1)}억 · 체결 {fmt(selected.n_trades)}건
                </p>
                {selected.book ? <Book book={selected.book} price={selected.price} /> : <p className="live-msg">호가 없음</p>}
                <h3>최근 체결</h3>
                <ul className="live-trades">
                  {selected.trades.slice().reverse().map((t, i) => (
                    <li key={i} className={t[3] === "B" ? "buy" : t[3] === "S" ? "sell" : ""}>
                      <span>{t[0].slice(11, 19)}</span><b>{fmt(num(t[1]))}</b><span>{fmt(num(t[2]))}주</span><em>{t[3] === "B" ? "매수" : t[3] === "S" ? "매도" : "중간"}</em>
                    </li>
                  ))}
                </ul>
              </aside>
            ) : null}
          </div>
          <p className="live-foot">
            체결강도 = 5분간 매수호가에 붙은 체결금액 ÷ 매도호가에 붙은 체결금액 × 100(토스 체결에는 매수·매도 구분이 없어 직전 호가와 대조해 추정). 거래대금 배수 = 최근 5분 거래대금 ÷ 그 종목의 평소 5분 거래대금(20일 평균, 2배 노랑·4배 빨강). 자리 = 20일 신고가 / 전일 고가 돌파 / 당일 고가. 15분 흐름 = 15분 전 대비 등락. 호가 점수 = 체결 방향(±2) + 가장 큰 벽(벽 ÷ 5분 거래대금, 매수 +·매도 −, ±2) + 벽 생김(±2) + 잔량비(±1), 마우스를 올리면 항목별. 벽·신호는 매수 빨강·매도 파랑. 어느 것도 예측값이 아니라 정렬용이며, 어떤 조합이 실제로 오르는지는 매일 채점표로 확인한다(하루치 결과: 평소 8배 넘게 몰린 신고가 종목은 오히려 장 끝까지 −1.4%). 호가는 KRX+NXT 통합.
          </p>
        </>
      ) : null}
    </main>
  );
}

function Book({ book, price }: { book: { ts: string; asks: Level[]; bids: Level[] }; price: number }) {
  const maxV = Math.max(1, ...book.asks.map((l) => num(l[1])), ...book.bids.map((l) => num(l[1])));
  const asks = book.asks.slice().reverse();     // 위가 높은 가격
  return (
    <div className="live-book">
      <div className="live-book-ts">호가 시각 {book.ts.slice(11, 19)}</div>
      {asks.map((l, i) => (
        <div className="live-lv ask" key={`a${i}`}>
          <span className="qty">{fmt(num(l[1]))}</span>
          <span className="bar" style={{ width: `${(num(l[1]) / maxV) * 100}%` }} />
          <span className={`px ${num(l[0]) === price ? "cur" : ""}`}>{fmt(num(l[0]))}</span>
          <span className="qty" />
        </div>
      ))}
      {book.bids.map((l, i) => (
        <div className="live-lv bid" key={`b${i}`}>
          <span className="qty" />
          <span className={`px ${num(l[0]) === price ? "cur" : ""}`}>{fmt(num(l[0]))}</span>
          <span className="bar" style={{ width: `${(num(l[1]) / maxV) * 100}%` }} />
          <span className="qty">{fmt(num(l[1]))}</span>
        </div>
      ))}
    </div>
  );
}
