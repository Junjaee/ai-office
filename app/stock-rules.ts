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

// ---- 받은 자료 정리: /api/stock 이 돌려준 자료가 깨졌어도 화면이 죽지 않게, 그리기 전에 모양을 맞춘다 ----
type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const numOr = (v: unknown, d: number): number => num(v) ?? d;
const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const nums = (v: unknown): number[] => arr(v).filter((x): x is number => typeof x === "number" && Number.isFinite(x));

export function normalizeBoard(input: unknown): Board | null {
  if (!isObj(input) || !Array.isArray(input.rows)) return null;
  const rows: BoardRow[] = [];
  for (const raw of input.rows) {
    if (!isObj(raw) || typeof raw.t !== "string" || !raw.t) continue;
    rows.push({
      t: raw.t, name: str(raw.name, raw.t), price: numOr(raw.price, 0), chg_pct: num(raw.chg_pct), spark: nums(raw.spark), ath_pct: num(raw.ath_pct), off_hi_pct: num(raw.off_hi_pct),
      fpe: num(raw.fpe), n_pass: numOr(raw.n_pass, 0), n_care: numOr(raw.n_care, 0), n_warn: numOr(raw.n_warn, 0), diag: str(raw.diag), next_earn: strOrNull(raw.next_earn),
      warn_keys: arr(raw.warn_keys).filter((x): x is string => typeof x === "string"),
    });
  }
  return { market: str(input.market), as_of: str(input.as_of), ...(typeof input.generated_at === "string" ? { generated_at: input.generated_at } : {}), rows };
}

const STATES: readonly string[] = ["pass", "care", "warn", "na"];

export function normalizeDoc(input: unknown): TickerDoc | null {
  if (!isObj(input) || !isObj(input.rec)) return null;
  const r = input.rec;
  if (typeof r.t !== "string" || !r.t || num(r.price) === null) return null;
  const tgt = isObj(r.tgt) && num(r.tgt.mean) !== null ? { mean: r.tgt.mean as number, lo: num(r.tgt.lo), hi: num(r.tgt.hi), n: numOr(r.tgt.n, 0) } : null;
  const rec: StockRecord = {
    t: r.t, name: str(r.name, r.t), exchange: str(r.exchange), sector: str(r.sector), financial: r.financial === true, as_of: str(r.as_of), price: r.price as number, chg_pct: num(r.chg_pct),
    hi52: numOr(r.hi52, 0), lo52: numOr(r.lo52, 0), off_hi_pct: num(r.off_hi_pct), ath: numOr(r.ath, 0), ath_date: str(r.ath_date), ath_pct: num(r.ath_pct), y_ret_pct: num(r.y_ret_pct),
    spark: nums(r.spark),
    chart: arr(r.chart).filter((p): p is [string, number] => Array.isArray(p) && typeof p[0] === "string" && num(p[1]) !== null).map((p) => [p[0], p[1]] as [string, number]),
    moves: arr(r.moves).filter(isObj).filter((m) => typeof m.date === "string" && num(m.pct) !== null && num(m.close) !== null).map((m) => ({ date: m.date as string, pct: m.pct as number, close: m.close as number })),
    dv_ratio: num(r.dv_ratio), fpe: num(r.fpe), tpe: num(r.tpe), pb: num(r.pb), mcap: num(r.mcap), rev_g: num(r.rev_g), eps_g: num(r.eps_g), opm: num(r.opm),
    net_debt_ebitda: num(r.net_debt_ebitda), debt: num(r.debt), cash: num(r.cash), fcf: num(r.fcf), ocf: num(r.ocf), rev: num(r.rev),
    tgt, next_earn: strOrNull(r.next_earn),
    annual: arr(r.annual).filter(isObj).filter((a) => num(a.fy) !== null).map((a) => ({ fy: a.fy as number, rev: num(a.rev), ni: num(a.ni), capex: num(a.capex), fcf: num(a.fcf) })),
  };
  const checks: Check[] = arr(input.checks).filter(isObj).filter((c) => typeof c.key === "string" && typeof c.text === "string")
    .map((c) => ({ key: c.key as string, text: c.text as string, state: (STATES.includes(c.state as string) ? c.state : "na") as CheckState }));
  const peers = arr(input.peers).filter(isObj).filter((p) => typeof p.t === "string" && typeof p.name === "string" && num(p.fpe) !== null)
    .map((p) => ({ t: p.t as string, name: p.name as string, fpe: p.fpe as number }));
  const ref = isObj(input.ref) ? { fpe: num(input.ref.fpe), opm: num(input.ref.opm), label: str(input.ref.label, "시장") } : { fpe: null, opm: null, label: "시장" };
  return { market: str(input.market), as_of: str(input.as_of), rec, checks, diag: str(input.diag), peers, ref };
}

/** 관심 담기·빼기 실패 안내 문구 */
export function watchErrorText(status: number, code: string | undefined): string {
  if (status === 503) return "저장 공간이 아직 연결되지 않았어요";
  if (code === "watch_full") return "관심 종목은 100개까지 담을 수 있어요";
  if (code === "bad_request") return "종목 기호를 확인해 주세요 (예: NVDA)";
  if (code === "forbidden") return "이 화면에서만 담을 수 있어요";
  return "잠시 뒤 다시 해 주세요";
}
