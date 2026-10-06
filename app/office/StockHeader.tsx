"use client";
// 주식 분석 화면 공통 머리글 — 사무실로 돌아가기, 화면 전환(관심 종목 · 발굴), 시장 전환(미국 · 국내), 기준일
import { MARKETS, MARKET_LABEL, stockQuery, type Market } from "../stock-rules";

export function StockIcon({ d, size = 14 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export type StockView = "board" | "discover" | "page";

export default function StockHeader({ ws, asOf, view, mock = false, market = "us" }: { ws: string; asOf: string | null; view: StockView; mock?: boolean; market?: Market }) {
  const q = stockQuery(market, mock);
  const here = `/${ws}/stock${view === "discover" ? "/discover" : ""}`; // 판·발굴은 같은 화면, 종목 한 장은 그 시장의 판으로
  return (
    <header className="dash-top">
      <div className="brand">
        <a className="brand-mark" href={`/${ws}`} aria-label="사무실로 돌아가기">
          <StockIcon d="M4 17l5-5 4 4 7-8M15 8h5v5" size={20} />
        </a>
        <b>AI 오피스 · 주식 분석</b>
      </div>
      <nav className="stk-nav" aria-label="화면">
        <a href={`/${ws}/stock${q}`} className={view === "board" ? "on" : ""} aria-current={view === "board" ? "page" : undefined}>
          관심 종목
        </a>
        <a href={`/${ws}/stock/discover${q}`} className={view === "discover" ? "on" : ""} aria-current={view === "discover" ? "page" : undefined}>
          발굴
        </a>
      </nav>
      <nav className="stk-nav" aria-label="시장">
        {MARKETS.map((m) => (
          <a key={m} href={`${here}${stockQuery(m, mock)}`} className={m === market ? "on" : ""} aria-current={m === market ? "true" : undefined}>
            {MARKET_LABEL[m]}
          </a>
        ))}
      </nav>
      <div className="checked">{asOf ? `${MARKET_LABEL[market]} · ${asOf} 종가 기준` : MARKET_LABEL[market]}</div>
    </header>
  );
}
