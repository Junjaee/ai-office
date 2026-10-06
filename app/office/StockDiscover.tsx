"use client";
// 발굴 판 — 봇이 네 관점으로 걸러 온 종목 카드. 자료·담기/빼기는 관심 종목 판과 같은 훅(useStockBoard)을 쓴다.
import { useMemo, useState } from "react";
import StockHeader, { StockIcon } from "./StockHeader";
import { LENS_LABEL, LENS_ORDER, STATE_META, discoverView, displayName, lensDaysText, money, nextRunText, pctText, scoreText, tone, type BoardRow, type LensId, type Market } from "../stock-rules";
import { useStockBoard } from "./useStockBoard";

const PAGE = 60;
const okNote = (t: string, action: "add" | "remove") => (action === "add" ? `${t} 을(를) 담았어요.` : `${t} 을(를) 뺐어요.`);
const SYMBOL: Record<Market, RegExp> = { us: /^[A-Z][A-Z0-9.\-]{0,9}$/, kr: /^[0-9][0-9A-Z]{5}$/ }; // Worker 와 같은 종목 모양 — 맞지 않으면 분석 링크를 만들지 않는다
const FOOT: Record<Market, string> = {
  us: "발굴 결과는 조건에 맞는 종목을 걸러 보여 주는 것이며 매수 추천이 아닙니다. 출처는 야후 파이낸스와 미국 증권거래위원회(EDGAR) 공시 목록입니다.",
  kr: "발굴 결과는 조건에 맞는 종목을 걸러 보여 주는 것이며 매수 추천이 아닙니다. 출처는 야후 파이낸스입니다. 국내 공시는 아직 받지 않습니다.",
};

const fpeText = (v: number | null) => (v != null && v > 0 ? `${v.toFixed(1)}배` : "–");
const debtText = (v: number | null) => (v == null ? "–" : v <= 0 ? "현금이 더 많음" : `영업이익의 ${v.toFixed(1)}배`);
const ratioText = (v: number | null) => (v == null ? "–" : `평소의 ${v.toFixed(1)}배`);

export default function StockDiscover({ ws }: { ws: string }) {
  const { data, error, busy, note, change, mock, market } = useStockBoard(okNote);
  const [lens, setLens] = useState<LensId | "all">("all");
  const [shown, setShown] = useState(PAGE);

  const board = data?.board ?? null;
  const view = useMemo(() => discoverView(board, lens), [board, lens]);
  const watch = useMemo(() => new Set(data?.watch ?? []), [data]);
  const label = (id: LensId) => board?.lens_info[id].label ?? LENS_LABEL[id];
  const cards = view.cards.slice(0, shown);
  const rest = view.cards.length - cards.length;
  const noData = !board || board.rows.length === 0 || LENS_ORDER.every((id) => !board.lens_info[id].rule); // 1단계 판(관점 자료 없음)도 "아직 없음"

  const pick = (id: LensId | "all") => {
    setLens(id);
    setShown(PAGE);
  };

  return (
    <main className="page-shell">
      <div className="wrap dash">
        <StockHeader ws={ws} asOf={board?.as_of ?? null} view="discover" mock={mock} market={market} />
        <section className="dash-title">
          <div>
            <h1>발굴</h1>
            <p>봇이 네 관점으로 찾아온 종목입니다. 마음에 들면 관심 종목에 담아 매일 점검하세요.</p>
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

        <section className="stk-section">
          <div className="stk-tabs" role="group" aria-label="관점">
            {view.tabs.map((t) => (
              <button key={t.id} type="button" className="stk-tab" aria-pressed={lens === t.id} onClick={() => pick(t.id)}>
                <span>{t.label}</span>
                <span className="stk-count">{t.count}</span>
              </button>
            ))}
          </div>
          {board && !noData ? (
            <p className="stk-rule">
              기준: {view.rule}
              {lens === "all" ? ` 대상 ${view.universe}종목 중 ${view.total}종목이 하나 이상에 걸렸습니다.` : ""}
            </p>
          ) : null}
          <p className="auto-meta" role="status">{note}</p>
        </section>

        {!data && !error ? <p className="auto-meta">불러오는 중…</p> : null}
        {data && cards.length === 0 ? (
          <div className="empty-state">{noData ? `아직 발굴 자료가 없어요. 다음 갱신(${nextRunText(market)}) 뒤에 채워집니다.` : "오늘은 이 관점에 걸린 종목이 없어요."}</div>
        ) : null}

        {cards.length ? (
          <section className="stk-cards" aria-label="발굴 종목">
            {cards.map((r) => (
              <Card key={r.t} r={r} ws={ws} market={market} mock={mock} saved={watch.has(r.t)} busy={busy} label={label} change={change} />
            ))}
          </section>
        ) : null}
        {cards.length && note ? <p className="auto-meta">{note}</p> : null}   {/* 위쪽 안내와 같은 글(안내 읽기는 위쪽 한 곳만) */}
        {rest > 0 ? (
          <div className="stk-more">
            <button type="button" className="btn" onClick={() => setShown((n) => n + PAGE)}>
              더 보기 ({rest}장 남음)
            </button>
          </div>
        ) : null}

        {data ? <p className="auto-meta">{lensDaysText(data.lensDays)}</p> : null}
        {board?.lens_score ? (
          <section className="stk-section">
            <h3 className="stk-subhead">관점별 성적 (최근 1년 · 지수 대비 · 배당 제외)</h3>
            <div className="stk-scroll" tabIndex={0} role="region" aria-label="관점별 성적 표">
              <table className="stk-ops stk-lens-score">
                <thead>
                  <tr>
                    <th scope="col">관점</th>
                    <th scope="col">1주</th>
                    <th scope="col">1개월</th>
                    <th scope="col">3개월</th>
                  </tr>
                </thead>
                <tbody>
                  {LENS_ORDER.map((id) => (
                    <tr key={id}>
                      <th scope="row">{label(id)}</th>
                      {(["1w", "1m", "3m"] as const).map((h) => (
                        <td key={h}>{scoreText(board.lens_score?.[id]?.[h], board.score_gate)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="auto-meta">1주 = 5거래일 · 1개월 = 21거래일 · 3개월 = 63거래일, 최근 1년 종가, 배당 제외</p>
          </section>
        ) : board && data && data.lensDays > 0 ? (
          <p className="auto-meta">오늘은 채점을 건너뛰었어요 — 다음 갱신 때 다시 계산합니다</p>
        ) : null}

        <footer className="dash-foot">{FOOT[market]}</footer>
      </div>
    </main>
  );
}

function Card({ r, ws, market, mock, saved, busy, label, change }: { r: BoardRow; ws: string; market: Market; mock: boolean; saved: boolean; busy: boolean; label: (id: LensId) => string; change: (t: string, a: "add" | "remove") => Promise<boolean> }) {
  const hits = LENS_ORDER.flatMap((id) => r.lenses.filter((h) => h.id === id));
  return (
    <article className="stk-card" aria-label={displayName(r)}>
      <div className="stk-card-top">
        <div className="stk-card-name">
          <h2>{displayName(r)}</h2>
          <small>{r.t}</small>
        </div>
        <div className="stk-card-price">
          <span className="stk-num">{money(r.price, r.currency)}</span>
          <span className={`stk-sub stk-${tone(r.chg_pct)}`}>{pctText(r.chg_pct)}</span>
        </div>
      </div>
      <div className="stk-chips">
        <span className="stk-chip dark">관점 {hits.length}개</span>
        {hits.map((h) => (
          <span key={h.id} className="stk-chip">{label(h.id)}</span>
        ))}
      </div>
      <ul className="stk-why">
        {hits.map((h) => (
          <li key={h.id}>
            <span>{label(h.id)}</span>
            <span>{h.why}</span>
          </li>
        ))}
      </ul>
      <dl className="stk-kv">
        <div><dt>예상 PER</dt><dd>{fpeText(r.fpe)}</dd></div>
        <div><dt>매출 증가</dt><dd>{pctText(r.rev_g)}</dd></div>
        <div><dt>빚</dt><dd>{debtText(r.nde)}</dd></div>
        <div><dt>거래대금</dt><dd>{ratioText(r.dv_ratio)}</dd></div>
      </dl>
      <div className="stk-card-acts">
        <button type="button" className={`btn ${saved ? "btn-primary" : "btn-accent"}`} aria-label={`${r.t} ${saved ? "관심 종목에서 빼기" : "관심에 담기"}`} aria-pressed={saved} disabled={busy} onClick={() => void change(r.t, saved ? "remove" : "add")}>
          {saved ? "관심 종목에 있음 · 빼기" : "관심에 담기"}
        </button>
        {SYMBOL[market].test(r.t) ? (
          <a className="btn btn-ghost" aria-label={`${r.t} 분석 보기`} href={`/${ws}/stock/${market}/${r.t}${mock ? "?mock=1" : ""}`}>
            분석 보기
          </a>
        ) : null}
      </div>
    </article>
  );
}
