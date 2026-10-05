"use client";
// 관심 종목 판 — /api/stock?view=board 를 읽어 관심 목록 순서대로 그린다. 담기·빼기는 /api/stock/watch.
import { useMemo, useState } from "react";
import StockHeader, { StockIcon } from "./StockHeader";
import { STATE_META, buildFlags, earnText, money, pctText, polyPoints, tone, watchRows, type BoardRow } from "../stock-rules";
import { useStockBoard } from "./useStockBoard";

const FLAG_ICON = { earnings: "M7 3v4M17 3v4M4 9h16M5 5h14v15H5z", warn: STATE_META.warn.icon, high: "M4 17l5-5 4 4 7-8M15 8h5v5" } as const;
const okNote = (t: string, action: "add" | "remove") => (action === "add" ? `${t} 을(를) 담았어요. 판에 없는 종목은 다음 갱신 때 자료가 들어옵니다.` : `${t} 을(를) 뺐어요.`);
const MARKET = "us";

export default function StockBoard({ ws }: { ws: string }) {
  const { data, error, busy, note, change: apply, mock } = useStockBoard(okNote);
  const [input, setInput] = useState("");
  const change = async (ticker: string, action: "add" | "remove") => {
    if (await apply(ticker, action)) setInput("");
  };

  const rows = useMemo(() => watchRows(data?.board ?? null, data?.watch ?? []), [data]);
  const ready = rows.filter((r): r is BoardRow & { pending: false } => !r.pending);
  const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const flags = buildFlags(ready, today);

  return (
    <main className="page-shell">
      <div className="wrap dash">
        <StockHeader ws={ws} asOf={data?.board?.as_of ?? null} view="board" mock={mock} />
        <section className="dash-title">
          <div>
            <h1>관심 종목</h1>
            <p>내가 담아 둔 종목을 매일 한 번 점검합니다. 종목을 누르면 분석 한 장이 열립니다.</p>
          </div>
        </section>
        {error ? (
          <div className="banners">
            <div className="banner gray">
              <StockIcon d={STATE_META.care.icon} size={16} />
              <span>{error}</span>
            </div>
          </div>
        ) : null}

        {ready.length ? (
          <section aria-label="오늘 먼저 볼 것" className="stk-section">
            <div className="section-head">
              <h2>오늘 먼저 볼 것</h2>
            </div>
            <div className="stk-flags">
              {flags.map((f) => (
                <div key={f.kind} className="stk-flag">
                  <span className="kpi-label">
                    <i className="kpi-ico working">
                      <StockIcon d={FLAG_ICON[f.kind]} />
                    </i>
                    {f.title}
                  </span>
                  <b>{f.body}</b>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section className="panel">
          <div className="section-head">
            <h2>내 목록 {rows.length}개</h2>
            <span>점검표는 가치·매출 성장·이익 방향·수익성·빚·현금흐름·추세 7가지</span>
          </div>
          {!data && !error ? <p className="auto-meta">불러오는 중…</p> : null}
          {data && rows.length === 0 ? <p className="auto-meta">아직 담은 종목이 없어요. 아래에서 종목 기호를 넣어 담아 보세요.</p> : null}
          {rows.length ? (
            <div className="stk-scroll">
              <div className="stk-table" role="table" aria-label="관심 종목">
                <div className="stk-tr head" role="row">
                  <span role="columnheader">종목</span>
                  <span role="columnheader" className="r">현재가</span>
                  <span role="columnheader">1년 흐름</span>
                  <span role="columnheader" className="r">고점 대비</span>
                  <span role="columnheader" className="r">예상 PER</span>
                  <span role="columnheader">점검표</span>
                  <span role="columnheader">점검 요약</span>
                  <span role="columnheader">다음 실적</span>
                  <span role="columnheader" />
                </div>
                {rows.map((r) => {
                  if (r.pending) {
                    return (
                      <div key={r.t} className="stk-tr" role="row">
                        <span role="cell" className="stk-name">
                          <b>{r.t}</b>
                          <small>{r.missing ? "야후에서 찾지 못함" : "자료를 받는 중"}</small>
                        </span>
                        <span role="cell" style={{ gridColumn: "2 / 9" }} className="auto-meta">
                          {r.missing ? "야후에서 찾지 못함 — 종목 기호를 확인하세요" : "다음 갱신(화~토 07:00) 때 들어옵니다."}
                        </span>
                        <span role="cell" className="stk-acts">
                          <button className="btn btn-ghost" disabled={busy} onClick={() => void change(r.t, "remove")}>
                            빼기
                          </button>
                        </span>
                      </div>
                    );
                  }
                  const e = earnText(r.next_earn, today);
                  return (
                    <div key={r.t} className="stk-tr" role="row">
                      <span role="cell" className="stk-name">
                        <b>{r.name}</b>
                        <small>{r.t}</small>
                      </span>
                      <span role="cell" className="r">
                        <span className="stk-num">{money(r.price)}</span>
                        <br />
                        <span className={`stk-sub stk-${tone(r.chg_pct)}`}>{pctText(r.chg_pct)}</span>
                      </span>
                      <span role="cell">
                        <svg width="120" height="32" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
                          <polyline points={polyPoints(r.spark, 100, 30)} fill="none" stroke="currentColor" strokeWidth={1.6} vectorEffect="non-scaling-stroke" className={`stk-${r.spark[r.spark.length - 1] >= r.spark[0] ? "up" : "down"}`} />
                        </svg>
                      </span>
                      <span role="cell" className="r">{pctText(r.ath_pct)}</span>
                      <span role="cell" className="r">{r.fpe != null && r.fpe > 0 ? `${r.fpe.toFixed(1)}배` : "–"}</span>
                      <span role="cell" className="stk-pills">
                        {(["pass", "care", "warn"] as const).map((s) => (
                          <span key={s} className={`status-pill ${STATE_META[s].cls}`}>
                            <StockIcon d={STATE_META[s].icon} size={12} />
                            {STATE_META[s].label} {s === "pass" ? r.n_pass : s === "care" ? r.n_care : r.n_warn}
                          </span>
                        ))}
                      </span>
                      <span role="cell">{r.diag}</span>
                      <span role="cell">
                        <b>{e.date}</b>
                        <br />
                        <span className="stk-sub">{e.days}</span>
                      </span>
                      <span role="cell" className="stk-acts">
                        <a className="btn btn-ghost" href={`/${ws}/stock/${MARKET}/${r.t}${mock ? "?mock=1" : ""}`}>
                          분석 보기
                        </a>
                        <button className="btn btn-ghost" disabled={busy} onClick={() => void change(r.t, "remove")} aria-label={`${r.name} 빼기`}>
                          빼기
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}
          <form
            className="stk-add"
            onSubmit={(ev) => {
              ev.preventDefault();
              void change(input, "add");
            }}
          >
            <label htmlFor="stk-add">종목 추가</label>
            <input id="stk-add" value={input} onChange={(ev) => setInput(ev.target.value)} placeholder="종목 기호 (예: NVDA)" maxLength={10} autoComplete="off" />
            <button className="btn btn-accent" type="submit" disabled={busy || !input.trim()}>
              담기
            </button>
            {note ? <span className="auto-meta" role="status">{note}</span> : null}
          </form>
        </section>

        <footer className="dash-foot">숫자는 프로그램이 계산한 값이고 출처는 야후 파이낸스입니다. 투자 권유가 아니며, 판단은 직접 하셔야 합니다.</footer>
      </div>
    </main>
  );
}
