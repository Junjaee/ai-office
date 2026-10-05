// 주식 분석 화면 견본 자료 — 개발 서버(저장 공간 없음)에서 ?mock=1 로 화면을 확인할 때만 쓴다.
import type { Board, BoardRow, LensHit, LensId, TickerDoc } from "./stock-rules";

const spark = (a: number, b: number) => Array.from({ length: 60 }, (_, i) => Number((a + ((b - a) * i) / 59 + Math.sin(i / 4) * (Math.abs(b - a) * 0.06 + 1)).toFixed(2)));
const WHY: Record<LensId, string> = {
  value: "점검표의 가치·빚·현금흐름이 모두 통과",
  growth: "최근 분기 매출 +29.6%, 이익 +54.5%",
  event: "9월 30일 실적 발표 공시",
  flow: "최근 5일 거래대금이 60일 평균의 2.1배, 종가가 20일 평균 위",
};
const hits = (ids: LensId[]): LensHit[] => ids.map((id) => ({ id, why: WHY[id] }));
const row = (t: string, name: string, price: number, chg: number, from: number, ath: number, off: number, fpe: number | null, p: number, c: number, w: number, diag: string, next: string | null, warn: string[], lenses: LensId[] = [], dv: number | null = 1, rev_g: number | null = 10, nde: number | null = 1): BoardRow =>
  ({ t, name, price, chg_pct: chg, spark: spark(from, price), ath_pct: ath, off_hi_pct: off, fpe, n_pass: p, n_care: c, n_warn: w, diag, next_earn: next, warn_keys: warn, sector: "Technology", rev_g, nde, dv_ratio: dv, lenses: hits(lenses) });

export function mockBoard(): { board: Board; watch: string[] } {
  return {
    watch: ["NVDA", "MSFT", "ORCL", "TSLA", "NEW1"],
    board: { market: "us", as_of: "2026-10-02", universe: 8, rows: [
      row("NVDA", "NVIDIA Corporation", 233.95, 1.3, 189.0, -0.8, -0.8, 14.9, 7, 0, 0, "좋음: 가치·매출 성장·이익 방향·수익성·빚·현금흐름·추세", "2026-11-18", [], ["value", "growth", "flow"], 2.1, 62.5, 0.2),
      row("MSFT", "Microsoft Corporation", 517.53, 0.9, 519.0, -4.5, -4.5, 21.9, 6, 1, 0, "좋음: 매출 성장·이익 방향·수익성·빚·현금흐름·추세", "2026-10-29", [], ["value", "event"], 1.2, 16.0, 0.1),
      row("ORCL", "Oracle Corporation", 142.3, 3.1, 289.0, -56.7, -54.5, 12.9, 4, 0, 3, "좋음: 가치·매출 성장·이익 방향·수익성 / 경고: 빚·현금흐름·추세", "2026-12-11", ["빚", "현금흐름", "추세"], ["growth"], 0.9, 29.6, 4.4),
      row("TSLA", "Tesla, Inc.", 370.59, 4.7, 430.0, -24.4, -24.4, 171.6, 3, 2, 2, "좋음: 매출 성장·빚·현금흐름 / 경고: 가치·이익 방향", "2026-10-22", ["가치", "이익 방향"], [], 1.4, 12.0, 0.3),
      row("AMD", "Advanced Micro Devices, Inc.", 171.2, 5.2, 140.0, -12.0, -12.0, 24.3, 5, 1, 1, "좋음: 매출 성장·이익 방향·수익성 / 경고: 가치", "2026-10-28", ["가치"], ["growth", "flow"], 3.2, 31.0, 0.4),
      row("PLTR", "Palantir Technologies Inc.", 168.4, 6.8, 120.0, -3.1, -3.1, 98.5, 4, 1, 2, "좋음: 매출 성장·수익성 / 경고: 가치", "2026-11-04", ["가치"], ["flow"], 2.6, 48.0, null),
      row("KO", "The Coca-Cola Company", 71.5, 0.2, 69.0, -2.0, -2.0, 21.0, 6, 1, 0, "좋음: 가치·수익성·빚·현금흐름", "2026-10-21", [], ["value"], 0.8, 6.0, 1.9),
      row("INTC", "Intel Corporation", 24.1, -1.1, 26.0, -60.0, -48.0, null, 2, 1, 4, "경고: 가치·이익 방향·수익성·현금흐름", "2026-10-23", ["이익 방향", "수익성"], [], 0.7, -2.0, 3.8),
    ], missing: [],
    lens_info: {
      value: { label: "싸고 탄탄", rule: "점검표의 가치·빚·현금흐름이 모두 통과" },
      growth: { label: "실적 개선", rule: "최근 분기 매출이 전년보다 15% 이상 늘고 이익도 늘어남" },
      event: { label: "사건", rule: "최근 14일 안에 주요 공시가 있었거나, 하루 ±7% 이상 움직이면서 거래대금이 평소의 3.0배 이상" },
      flow: { label: "돈 몰림", rule: "최근 5일 평균 거래대금이 60일 평균의 1.5배 이상이고 종가가 20일 평균 위" },
    } },
  };
}

export function mockDoc(ticker: string): TickerDoc {
  const chart: [string, number][] = Array.from({ length: 130 }, (_, i) => {
    const d = new Date(Date.UTC(2025, 9, 6) + i * 2.78 * 86400000).toISOString().slice(0, 10);
    return [d, Number((290 - i * 1.15 + Math.sin(i / 6) * 18).toFixed(2))];
  });
  chart[chart.length - 1] = ["2026-10-02", 142.3];
  return {
    market: "us", as_of: "2026-10-02", diag: "좋음: 가치·매출 성장·이익 방향·수익성 / 경고: 빚·현금흐름·추세",
    rec: { t: ticker, name: "Oracle Corporation", exchange: "NYQ", sector: "Technology", financial: false, as_of: "2026-10-02", price: 142.3, chg_pct: 3.1,
      hi52: 313.0, lo52: 114.99, off_hi_pct: -54.5, ath: 328.33, ath_date: "2025-09-10", ath_pct: -56.7, y_ret_pct: -50.8,
      spark: chart.filter((_, i) => i % 2 === 0).map(([, v]) => v), chart, moves: [{ date: chart[60][0], pct: -8.2, close: chart[60][1] }, { date: chart[118][0], pct: 7.4, close: chart[118][1] }], dv_ratio: 1.01,
      fpe: 12.9, tpe: 22.3, pb: 7.0, mcap: 4.3e11, rev_g: 29.6, eps_g: 54.5, opm: 35.6, net_debt_ebitda: 4.4, debt: 169.1e9, cash: 37.1e9, fcf: -45.9e9, ocf: 46.9e9, rev: 71.8e9,
      tgt: { mean: 238, lo: 110, hi: 400, n: 41 }, next_earn: "2026-12-11",
      annual: [{ fy: 2023, rev: 50.0e9, ni: 8.5e9, capex: 8.7e9, fcf: 8.5e9 }, { fy: 2024, rev: 53.0e9, ni: 10.5e9, capex: 6.9e9, fcf: 11.8e9 }, { fy: 2025, rev: 57.4e9, ni: 12.4e9, capex: 21.2e9, fcf: -0.4e9 }, { fy: 2026, rev: 67.4e9, ni: 17.1e9, capex: 55.7e9, fcf: -23.7e9 }] },
    checks: [
      { key: "가치", state: "pass", text: "예상 PER 12.9배 · 업종 중앙값 26.8배보다 낮음" }, { key: "매출 성장", state: "pass", text: "최근 분기 매출 +29.6% (전년 대비)" },
      { key: "이익 방향", state: "pass", text: "최근 분기 이익 +54.5% (전년 대비)" }, { key: "수익성", state: "pass", text: "영업이익률 35.6% · 업종 중앙값 31.0% 이상" },
      { key: "빚", state: "warn", text: "순부채가 연간 영업이익의 4.4배" }, { key: "현금흐름", state: "care", text: "쓰고 남은 현금 −459억 달러 (영업현금은 흑자)" },
      { key: "추세", state: "warn", text: "1년 최고가 대비 -54.5%" },
    ],
    peers: [{ t: "CRM", name: "Salesforce, Inc.", fpe: 19.8 }, { t: "IBM", name: "International Business Machines", fpe: 22.4 }, { t: "ADBE", name: "Adobe Inc.", fpe: 16.1 }],
    ref: { fpe: 26.8, opm: 31.0, label: "업종" },
    lenses: [{ id: "event", why: "9월 30일 실적 발표 공시" }], events: [{ date: "2026-09-30", kind: "실적 발표" }],
  };
}
