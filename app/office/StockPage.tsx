"use client";
// 종목 한 장 — /api/stock?ticker= 를 읽어 그린다. 1단계: 결론은 점검표로 만든 규칙 문장, 사건은 가격에서 계산한 큰 변동일.
import { useCallback, useEffect, useMemo, useState } from "react";
import StockHeader, { StockIcon } from "./StockHeader";
import { LENS_LABEL, STATE_META, chartGeometry, earnText, eok, money, monthDay, normalizeDoc, pctText, tone, watchErrorText, type TickerDoc } from "../stock-rules";
import { mockDoc } from "../stock-mock";

type ApiTicker = { market: string; ticker: string; doc: TickerDoc | null; watched: boolean };
const UP = "M12 19V5M6 11l6-6 6 6";
const DOWN = "M12 5v14M6 13l6 6 6-6";
const eokShort = (v: number | null) => (v == null ? "–" : `${v < 0 ? "−" : ""}${Math.round(Math.abs(v) / 1e8).toLocaleString("ko-KR")}`);

export default function StockPage({ ws, market, ticker }: { ws: string; market: string; ticker: string }) {
  const [data, setData] = useState<ApiTicker | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const mock = useMemo(() => (typeof window !== "undefined" ? new URLSearchParams(window.location.search).has("mock") : false), []);

  const load = useCallback(async () => {
    if (mock) {
      setData({ market, ticker, doc: normalizeDoc(mockDoc(ticker)), watched: true });
      return;
    }
    try {
      const r = await fetch(`/api/stock?market=${encodeURIComponent(market)}&ticker=${encodeURIComponent(ticker)}&t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status === 503 ? "저장 공간이 아직 연결되지 않았어요" : `자료를 불러오지 못했어요 (HTTP ${r.status})`);
      const j = (await r.json()) as { doc?: unknown; watched?: unknown };
      setData({ market, ticker, doc: normalizeDoc(j.doc), watched: j.watched === true });
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "자료를 불러오지 못했어요");
    }
  }, [market, ticker, mock]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleWatch = async () => {
    if (!data) return;
    const action = data.watched ? "remove" : "add";
    setNote("");
    if (mock) {
      setData((d) => (d ? { ...d, watched: !d.watched } : d));
      return;
    }
    setBusy(true);
    try {
      const r = await fetch("/api/stock/watch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ market, ticker, action }) });
      const j = (await r.json().catch(() => ({}))) as { error?: string };
      if (!r.ok) {
        setNote(watchErrorText(r.status, j.error));
        return;
      }
      setData((d) => (d ? { ...d, watched: !d.watched } : d));
    } catch {
      setNote("잠시 뒤 다시 해 주세요");
    } finally {
      setBusy(false);
    }
  };

  const doc = data?.doc ?? null;
  const rec = doc?.rec ?? null;
  const geo = useMemo(() => chartGeometry(rec?.chart ?? [], rec?.moves ?? []), [rec]);
  const today = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  const back = `/${ws}/stock${mock ? "?mock=1" : ""}`;

  if (!rec || !doc) {
    return (
      <main className="page-shell">
        <div className="wrap dash">
          <StockHeader ws={ws} asOf={null} view="page" mock={mock} />
          <a className="stk-back" href={back}>
            <StockIcon d="M15 5l-7 7 7 7" />
            관심 종목으로
          </a>
          <div className="empty-state">{error || (data ? `${ticker} 자료가 아직 없어요. 관심 종목에 담으면 다음 갱신(화~토 07:00) 때 들어옵니다.` : "불러오는 중…")}</div>
        </div>
      </main>
    );
  }

  const good = doc.checks.filter((c) => c.state === "pass");
  const bad = doc.checks.filter((c) => c.state === "warn" || c.state === "care");
  const counts = { pass: good.length, care: doc.checks.filter((c) => c.state === "care").length, warn: doc.checks.filter((c) => c.state === "warn").length };
  const bars = [{ name: rec.name, fpe: rec.fpe, cls: "me" }, ...doc.peers.map((p) => ({ name: p.name, fpe: p.fpe as number | null, cls: "" })), { name: `${doc.ref.label} 중앙값`, fpe: doc.ref.fpe, cls: "ref" }].filter((b) => b.fpe != null && b.fpe > 0);
  const barMax = Math.max(1, ...bars.map((b) => b.fpe as number));
  const e = earnText(rec.next_earn, today);
  const years = rec.annual.slice(-4);

  return (
    <main className="page-shell">
      <div className="wrap dash">
        <StockHeader ws={ws} asOf={doc.as_of} view="page" mock={mock} />

        <section className="stk-hero">
          <div>
            <a className="stk-back" href={back}>
              <StockIcon d="M15 5l-7 7 7 7" />
              관심 종목으로
            </a>
            <h1>{rec.name}</h1>
            <span className="stk-sub">
              {rec.t} · {rec.exchange}
              {rec.sector ? ` · ${rec.sector}` : ""}
            </span>
            {doc.lenses.length ? (
              <div className="stk-chips" aria-label="발굴 관점">
                <span className="stk-sub">발굴:</span>
                {doc.lenses.map((l) => (
                  <span key={l.id} className="stk-chip">{LENS_LABEL[l.id]}</span>
                ))}
              </div>
            ) : null}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div style={{ textAlign: "right" }}>
              <div className="price">{money(rec.price)}</div>
              <span className={`stk-sub stk-${tone(rec.chg_pct)}`}>전일 대비 {pctText(rec.chg_pct)}</span>
            </div>
            <button className={`btn ${data?.watched ? "btn-ghost" : "btn-accent"}`} disabled={busy} onClick={() => void toggleWatch()}>
              {data?.watched ? "관심 종목에서 빼기" : "관심에 담기"}
            </button>
            {note ? <span className="auto-meta" role="status">{note}</span> : null}
          </div>
        </section>

        <section className="stk-verdict">
          <small>한 줄 결론 · 점검표로 만든 문장</small>
          <p>{doc.diag}</p>
          <small>해석이 필요하면 클로드 대화에서 "{rec.t} 해석해 줘"라고 요청하세요. (해석 저장은 다음 단계에서 열립니다)</small>
        </section>

        <div className="stk-two">
          <section className="panel">
            <div className="panel-head">
              <h2>
                <span className="kpi-label">
                  <i className="kpi-ico done">
                    <StockIcon d={UP} />
                  </i>
                  좋게 보는 근거
                </span>
              </h2>
            </div>
            <ul className="stk-list">
              {good.length ? good.map((c) => (
                <li key={c.key}>
                  <b>{c.key}</b> {c.text}
                </li>
              )) : <li className="auto-meta">통과한 항목이 없어요.</li>}
            </ul>
          </section>
          <section className="panel">
            <div className="panel-head">
              <h2>
                <span className="kpi-label">
                  <i className="kpi-ico error">
                    <StockIcon d={DOWN} />
                  </i>
                  나쁘게 보는 근거
                </span>
              </h2>
            </div>
            <ul className="stk-list">
              {bad.length ? bad.map((c) => (
                <li key={c.key}>
                  <b>{c.key}</b> {c.text} <span className="stk-sub">({STATE_META[c.state].label})</span>
                </li>
              )) : <li className="auto-meta">주의·경고 항목이 없어요.</li>}
            </ul>
          </section>
        </div>

        <section className="panel">
          <div className="section-head">
            <h2>점검표</h2>
            <span>
              통과 {counts.pass} · 주의 {counts.care} · 경고 {counts.warn}
            </span>
          </div>
          <ul className="stk-checks">
            {doc.checks.map((c) => (
              <li key={c.key}>
                <span className={`status-pill ${STATE_META[c.state].cls}`}>
                  <StockIcon d={STATE_META[c.state].icon} size={13} />
                  {STATE_META[c.state].label}
                </span>
                <b>{c.key}</b>
                <span>{c.text}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>주가와 큰 변동일</h2>
            <p>최근 1년 종가. 번호는 하루에 7% 넘게 움직인 날입니다.</p>
          </div>
          <div className="stk-chart">
            <svg viewBox="0 0 1000 220" preserveAspectRatio="none" role="img" aria-label={`${rec.name} 최근 1년 주가`}>
              <polyline points={geo.points} fill="none" stroke="var(--accent)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            </svg>
            <span className="y" style={{ top: 0 }}>최고 {money(geo.yMax)}</span>
            <span className="y" style={{ bottom: 4 }}>최저 {money(geo.yMin)}</span>
            {geo.marks.map((m) => (
              <span key={m.n} className="stk-mark" style={{ left: m.left, top: m.top }}>
                {m.n}
              </span>
            ))}
          </div>
          <div className="stk-xaxis" aria-hidden="true">
            {geo.xLabels.map((x, i) => (
              <span key={i}>{x}</span>
            ))}
          </div>
          {geo.marks.length ? (
            <ol className="stk-events">
              {geo.marks.map((m) => (
                <li key={m.n}>
                  <span className="stk-mark inline">{m.n}</span>
                  <b>
                    {m.when} · {money(m.price)}
                  </b>
                  <span>{m.text}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="auto-meta">최근 1년 동안 하루에 7% 넘게 움직인 날이 없어요.</p>
          )}
          {doc.events.length ? (
            <>
              <h3 className="stk-subhead">최근 공시</h3>
              <ul className="stk-list">
                {doc.events.map((ev, i) => (
                  <li key={i}>
                    <b>{/^\d{4}-\d{2}-\d{2}$/.test(ev.date) ? monthDay(ev.date) : ev.date}</b> · {ev.kind}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>

        <div className="stk-two">
          <section className="panel">
            <div className="panel-head">
              <h2>가치: 다른 회사와 견주기</h2>
              <p>예상 PER (낮을수록 이익에 비해 쌈)</p>
            </div>
            {bars.length ? (
              <div className="stk-bars">
                {bars.map((b) => (
                  <div key={b.name} className={`stk-bar ${b.cls}`}>
                    <span>{b.name}</span>
                    <div className="track">
                      <i style={{ width: `${(((b.fpe as number) / barMax) * 100).toFixed(1)}%` }} />
                    </div>
                    <span style={{ textAlign: "right" }}>{(b.fpe as number).toFixed(1)}배</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="auto-meta">예상 이익 자료가 없어 견줄 수 없어요.</p>
            )}
            <dl className="stk-facts">
              <div>
                <dt>PER</dt>
                <dd>{rec.tpe != null && rec.tpe > 0 ? `${rec.tpe.toFixed(1)}배` : "–"}</dd>
              </div>
              <div>
                <dt>예상 PER</dt>
                <dd>{rec.fpe != null && rec.fpe > 0 ? `${rec.fpe.toFixed(1)}배` : "–"}</dd>
              </div>
              <div>
                <dt>PBR</dt>
                <dd>{rec.pb != null ? `${rec.pb.toFixed(1)}배` : "–"}</dd>
              </div>
              <div>
                <dt>평균 목표가{rec.tgt ? ` (${rec.tgt.n}곳)` : ""}</dt>
                <dd>{rec.tgt ? `$${Math.round(rec.tgt.mean).toLocaleString("en-US")}` : "–"}</dd>
              </div>
            </dl>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>실적과 재무: {years.length}년 흐름</h2>
              <p>회계연도 기준, 단위 억 달러</p>
            </div>
            {years.length ? (
              <div className="stk-years" role="table" aria-label="연도별 실적">
                <div className="stk-yr head" role="row" style={{ gridTemplateColumns: `minmax(96px, 1.3fr) repeat(${years.length}, minmax(0, 1fr))` }}>
                  <span role="columnheader">항목</span>
                  {years.map((y) => (
                    <span key={y.fy} role="columnheader">{y.fy}</span>
                  ))}
                </div>
                {([["매출", "rev"], ["순이익", "ni"], ["설비 투자", "capex"], ["쓰고 남은 현금", "fcf"]] as const).map(([label, key]) => (
                  <div key={key} className="stk-yr" role="row" style={{ gridTemplateColumns: `minmax(96px, 1.3fr) repeat(${years.length}, minmax(0, 1fr))` }}>
                    <span role="cell">
                      <b>{label}</b>
                    </span>
                    {years.map((y) => (
                      <span key={y.fy} role="cell" className="stk-num">{eokShort(y[key])}</span>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <p className="auto-meta">연도별 자료가 없어요.</p>
            )}
            <dl className="stk-facts">
              <div>
                <dt>총부채</dt>
                <dd>{eok(rec.debt)}</dd>
              </div>
              <div>
                <dt>현금</dt>
                <dd>{eok(rec.cash)}</dd>
              </div>
              <div>
                <dt>영업으로 번 현금</dt>
                <dd>{eok(rec.ocf)}</dd>
              </div>
              <div>
                <dt>쓰고 남은 현금</dt>
                <dd>{eok(rec.fcf)}</dd>
              </div>
            </dl>
          </section>
        </div>

        <div className="stk-two">
          <section className="panel">
            <div className="panel-head">
              <h2>다음 일정</h2>
            </div>
            <div>
              {rec.next_earn ? (
                <>
                  <b>{e.date}</b> 분기 실적 발표 예정 <span className="stk-sub">({e.days})</span>
                </>
              ) : (
                <span className="auto-meta">예정된 실적 발표일 자료가 없어요.</span>
              )}
            </div>
          </section>
          <section className="panel stk-empty">
            <div className="panel-head">
              <h2>의견 기록과 채점</h2>
            </div>
            <div className="auto-meta">아직 기록이 없습니다. 해석을 저장하는 기능은 다음 단계에서 열립니다.</div>
          </section>
        </div>

        <footer className="dash-foot">
          출처: 야후 파이낸스(시세·재무·전망) · 기준일 {monthDay(doc.as_of)} · 역대 최고가 {money(rec.ath)}({rec.ath_date}) 대비 {pctText(rec.ath_pct, 0)}. 투자 권유가 아니며, 판단은 직접 하셔야 합니다.
        </footer>
      </div>
    </main>
  );
}
