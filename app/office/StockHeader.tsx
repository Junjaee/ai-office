"use client";
// 주식 분석 화면 공통 머리글 — 사무실로 돌아가기, 화면 전환(관심 종목 · 발굴은 2단계), 시장(미국 · 국내는 4단계), 기준일
export function StockIcon({ d, size = 14 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export default function StockHeader({ ws, asOf, onBoard }: { ws: string; asOf: string | null; onBoard: boolean }) {
  return (
    <header className="dash-top">
      <div className="brand">
        <a className="brand-mark" href={`/${ws}`} aria-label="사무실로 돌아가기">
          <StockIcon d="M4 17l5-5 4 4 7-8M15 8h5v5" size={20} />
        </a>
        <b>AI 오피스 · 주식 분석</b>
      </div>
      <nav className="stk-nav" aria-label="화면">
        <a href={`/${ws}/stock`} className={onBoard ? "on" : ""} aria-current={onBoard ? "page" : undefined}>
          관심 종목
        </a>
        <span title="다음 단계에서 열립니다">발굴 (준비 중)</span>
      </nav>
      <div className="checked">{asOf ? `미국 · ${asOf} 종가 기준` : "미국"}</div>
    </header>
  );
}
