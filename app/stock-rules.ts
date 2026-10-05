// 주식 분석 화면의 순수 규칙 — 타입, 숫자·날짜 문구, 흐름선 좌표, "오늘 먼저 볼 것". React·fetch 없음(node --test 가 직접 실행).
// 자료 모양의 원천은 automations/analyst (analyst_metrics.build_record · analyst_checks.board_row).

export type CheckState = "pass" | "care" | "warn" | "na";
export type Check = { key: string; state: CheckState; text: string };
export type BoardRow = {
  t: string; name: string; price: number; chg_pct: number | null; spark: number[]; ath_pct: number | null; off_hi_pct: number | null;
  fpe: number | null; n_pass: number; n_care: number; n_warn: number; diag: string; next_earn: string | null; warn_keys: string[];
};
export type Board = { market: string; as_of: string; generated_at?: string; rows: BoardRow[] };
export type StockRecord = {
  t: string; name: string; exchange: string; sector: string; financial: boolean; as_of: string; price: number; chg_pct: number | null;
  hi52: number; lo52: number; off_hi_pct: number | null; ath: number; ath_date: string; ath_pct: number | null; y_ret_pct: number | null;
  spark: number[]; chart: [string, number][]; moves: { date: string; pct: number; close: number }[]; dv_ratio: number | null;
  fpe: number | null; tpe: number | null; pb: number | null; mcap: number | null; rev_g: number | null; eps_g: number | null; opm: number | null;
  net_debt_ebitda: number | null; debt: number | null; cash: number | null; fcf: number | null; ocf: number | null; rev: number | null;
  tgt: { mean: number; lo: number | null; hi: number | null; n: number } | null; next_earn: string | null;
  annual: { fy: number; rev: number | null; ni: number | null; capex: number | null; fcf: number | null }[];
};
export type TickerDoc = {
  market: string; as_of: string; rec: StockRecord; checks: Check[]; diag: string;
  peers: { t: string; name: string; fpe: number }[]; ref: { fpe: number | null; opm: number | null; label: string };
};
export type WatchRow = (BoardRow & { pending: false }) | { t: string; pending: true };
export type Flag = { kind: "earnings" | "warn" | "high"; title: string; body: string };

/** 상태 이름표. 색만으로 구분하지 않는다 — 글자와 아이콘(선 그림 path)을 함께 쓴다 */
export const STATE_META: Record<CheckState, { label: string; cls: string; icon: string }> = {
  pass: { label: "통과", cls: "done", icon: "M5 12.5l4.5 4.5L19 7.5" },
  care: { label: "주의", cls: "care", icon: "M12 8v5M12 16.2v.3M12 3a9 9 0 100 18 9 9 0 000-18" },
  warn: { label: "경고", cls: "error", icon: "M12 4l9 16H3zM12 10v4M12 17.2v.3" },
  na: { label: "자료 없음", cls: "planned", icon: "M6 12h12" },
};

export function money(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "–";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function pctText(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "–";
  if (Math.abs(v) < 0.05) return "0.0%";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function tone(v: number | null | undefined): "up" | "down" | "flat" {
  if (v == null || Math.abs(v) < 0.05) return "flat";
  return v > 0 ? "up" : "down";
}

/** 달러 금액 → "1,691억 달러" (음수는 − 를 붙인다) */
export function eok(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "–";
  const s = `${Math.round(Math.abs(v) / 1e8).toLocaleString("ko-KR")}억 달러`;
  return v < 0 ? `−${s}` : s;
}

/** SVG polyline 좌표. 높은 값이 위, pad 만큼 위아래 여백 */
export function polyPoints(values: number[], w: number, h: number, pad = 2): string {
  if (!values.length) return "";
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo;
  return values
    .map((v, i) => {
      const x = values.length === 1 ? 0 : (i / (values.length - 1)) * w;
      const y = span === 0 ? h / 2 : h - pad - ((v - lo) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function monthDay(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(m)}월 ${Number(d)}일`;
}

export function daysUntil(iso: string | null | undefined, todayIso: string): number | null {
  if (!iso) return null;
  const ms = Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${todayIso}T00:00:00Z`);
  return Number.isNaN(ms) ? null : Math.round(ms / 86400000);
}

export function earnText(iso: string | null | undefined, todayIso: string): { date: string; days: string } {
  const n = daysUntil(iso, todayIso);
  if (!iso || n === null) return { date: "–", days: "" };
  return { date: monthDay(iso), days: n === 0 ? "오늘" : n > 0 ? `${n}일 뒤` : "지남" };
}

/** 관심 목록 순서대로 줄을 만든다. 판에 아직 없는 종목은 "자료를 받는 중" */
export function watchRows(board: Board | null, watch: string[]): WatchRow[] {
  const byT = new Map((board?.rows ?? []).map((r) => [r.t, r] as const));
  return watch.map((t) => {
    const r = byT.get(t);
    return r ? { ...r, pending: false as const } : { t, pending: true as const };
  });
}

export const FLAG_EARN_DAYS = 30;
export const FLAG_NEAR_HIGH_PCT = 3;

/** 오늘 먼저 볼 것 세 칸. 해당이 없으면 없다고 적는다 */
export function buildFlags(rows: BoardRow[], todayIso: string): Flag[] {
  const soon = rows
    .map((r) => ({ r, n: daysUntil(r.next_earn, todayIso) }))
    .filter((x): x is { r: BoardRow; n: number } => x.n !== null && x.n >= 0 && x.n <= FLAG_EARN_DAYS)
    .sort((a, b) => a.n - b.n);
  const worst = rows.filter((r) => r.n_warn > 0).sort((a, b) => b.n_warn - a.n_warn)[0];
  const near = rows.filter((r) => r.off_hi_pct != null && r.off_hi_pct > -FLAG_NEAR_HIGH_PCT);
  return [
    { kind: "earnings", title: "실적 발표가 가까운 종목", body: soon.length ? soon.map((x) => `${x.r.name} ${monthDay(x.r.next_earn as string)}`).join(", ") : `${FLAG_EARN_DAYS}일 안에 예정된 발표가 없어요` },
    { kind: "warn", title: "경고가 가장 많은 종목", body: worst ? `${worst.name} · 경고 ${worst.n_warn}개 (${worst.warn_keys.join("·")})` : "경고가 있는 종목이 없어요" },
    { kind: "high", title: "1년 최고가 근처", body: near.length ? near.map((r) => `${r.name} ${pctText(r.off_hi_pct)}`).join(", ") : `최고가 ${FLAG_NEAR_HIGH_PCT}% 안쪽에 있는 종목이 없어요` },
  ];
}

export type ChartMark = { n: number; left: string; top: string; when: string; price: number; text: string };

/** 종목 한 장 그래프: 선 좌표(1000×220), 큰 변동일 표시 위치(%), 축 글자 */
export function chartGeometry(chart: [string, number][], moves: { date: string; pct: number; close: number }[]): { points: string; marks: ChartMark[]; yMax: number; yMin: number; xLabels: string[] } {
  if (!chart.length) return { points: "", marks: [], yMax: 0, yMin: 0, xLabels: [] };
  const values = chart.map(([, v]) => v);
  const yMax = Math.max(...values);
  const yMin = Math.min(...values);
  const lo = yMin * 0.97;
  const hi = yMax * 1.03;
  const last = chart.length - 1;
  const points = chart.map(([, v], i) => `${((last ? i / last : 0) * 1000).toFixed(1)},${(220 - ((v - lo) / (hi - lo)) * 220).toFixed(1)}`).join(" ");
  const marks: ChartMark[] = [];
  for (const m of moves) {
    if (m.date < chart[0][0] || m.date > chart[last][0]) continue;
    let i = chart.findIndex(([d]) => d >= m.date);
    if (i < 0) i = last;
    marks.push({ n: marks.length + 1, left: `${((last ? i / last : 0) * 100).toFixed(2)}%`, top: `${(100 - ((chart[i][1] - lo) / (hi - lo)) * 100).toFixed(2)}%`, when: monthDay(m.date), price: m.close, text: `하루에 ${pctText(m.pct)} 움직임` });
  }
  const pick = chart.length >= 4 ? [0, Math.round(last / 3), Math.round((last * 2) / 3), last] : chart.map((_, i) => i);
  const xLabels = pick.map((i) => `${chart[i][0].slice(2, 4)}.${chart[i][0].slice(5, 7)}`);
  return { points, marks, yMax, yMin, xLabels };
}
