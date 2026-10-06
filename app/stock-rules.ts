// 주식 분석 화면의 순수 규칙 — 타입, 숫자·날짜 문구, 흐름선 좌표, "오늘 먼저 볼 것". React·fetch 없음(node --test 가 직접 실행).
// 자료 모양의 원천은 automations/analyst (analyst_metrics.build_record · analyst_checks.board_row).

export type Market = "us" | "kr";
export const MARKETS: Market[] = ["us", "kr"];
export const MARKET_LABEL: Record<Market, string> = { us: "미국", kr: "국내" };
export const isMarket = (v: unknown): v is Market => typeof v === "string" && (MARKETS as string[]).includes(v);
export type Currency = "USD" | "KRW";

export type CheckState = "pass" | "care" | "warn" | "na";
export type Check = { key: string; state: CheckState; text: string };
export type LensId = "value" | "growth" | "event" | "flow";
export type LensHit = { id: LensId; why: string };
export type StockEvent = { date: string; kind: string };
export const LENS_ORDER: LensId[] = ["value", "growth", "event", "flow"];
export const LENS_LABEL: Record<LensId, string> = { value: "싸고 탄탄", growth: "실적 개선", event: "사건", flow: "돈 몰림" };
export type BoardRow = {
  t: string; name: string; name_local?: string | null; currency: Currency; price: number; chg_pct: number | null; spark: number[]; ath_pct: number | null; off_hi_pct: number | null;
  fpe: number | null; n_pass: number; n_care: number; n_warn: number; diag: string; next_earn: string | null; warn_keys: string[];
  sector: string; rev_g: number | null; nde: number | null; dv_ratio: number | null; lenses: LensHit[];
};
export type Score = { n: number; days: number; avg: number | null; win: number | null };
export type ScoreGate = { min_n: number; min_days: number };
export const DEFAULT_SCORE_GATE: ScoreGate = { min_n: 30, min_days: 20 };
export type ScoreHorizon = "1w" | "1m" | "3m";
export type Board = { market: string; as_of: string; generated_at?: string; universe: number | null; rows: BoardRow[]; missing: string[]; lens_info: Record<LensId, { label: string; rule: string }>; lens_score: Record<LensId, Record<ScoreHorizon, Score>> | null; score_gate: ScoreGate };
export type StockRecord = {
  t: string; name: string; name_local: string | null; currency: Currency; exchange: string; sector: string; financial: boolean; as_of: string; price: number; chg_pct: number | null;
  hi52: number; lo52: number; off_hi_pct: number | null; ath: number; ath_date: string; ath_pct: number | null; y_ret_pct: number | null;
  spark: number[]; chart: [string, number][]; moves: { date: string; pct: number; close: number }[]; dv_ratio: number | null;
  fpe: number | null; tpe: number | null; pb: number | null; mcap: number | null; rev_g: number | null; eps_g: number | null; opm: number | null;
  net_debt_ebitda: number | null; debt: number | null; cash: number | null; fcf: number | null; ocf: number | null; rev: number | null;
  tgt: { mean: number; lo: number | null; hi: number | null; n: number } | null; next_earn: string | null;
  annual: { fy: number; rev: number | null; ni: number | null; capex: number | null; fcf: number | null }[];
};
export type NewsItem = { title: string; source: string; date: string; url: string };
export type TickerDoc = {
  market: string; as_of: string; rec: StockRecord; checks: Check[]; diag: string;
  peers: { t: string; name: string; fpe: number }[]; ref: { fpe: number | null; opm: number | null; label: string };
  lenses: LensHit[]; events: StockEvent[]; news: NewsItem[] | null; // news null = 기사 제목을 받지 못했거나 받지 않음, [] = 받았는데 0건
};
export type EvidenceSrc = "재무" | "시세" | "뉴스" | "전망";
export type Opinion = { id: string; price: number; as_of: string; next_earn: string | null; verdict: string; good: { text: string; src: EvidenceSrc }[]; bad: { text: string; src: EvidenceSrc }[]; watch: string[] };
export type IndexDoc = { t: string; closes: [string, number][] };
export type WatchRow = (BoardRow & { pending: false }) | { t: string; pending: true; missing: boolean };
export type Flag = { kind: "earnings" | "warn" | "high"; title: string; body: string };

/** 상태 이름표. 색만으로 구분하지 않는다 — 글자와 아이콘(선 그림 path)을 함께 쓴다 */
export const STATE_META: Record<CheckState, { label: string; cls: string; icon: string }> = {
  pass: { label: "통과", cls: "done", icon: "M5 12.5l4.5 4.5L19 7.5" },
  care: { label: "주의", cls: "care", icon: "M12 8v5M12 16.2v.3M12 3a9 9 0 100 18 9 9 0 000-18" },
  warn: { label: "경고", cls: "error", icon: "M12 4l9 16H3zM12 10v4M12 17.2v.3" },
  na: { label: "자료 없음", cls: "planned", icon: "M6 12h12" },
};

export function money(v: number | null | undefined, currency: Currency = "USD"): string {
  if (v == null || Number.isNaN(v)) return "–";
  if (currency === "KRW") return `${v < 0 ? "−" : ""}₩${Math.round(Math.abs(v)).toLocaleString("ko-KR")}`;
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

/** 큰 금액의 단위 글자 — "억 달러" / "억 원" */
export const eokUnit = (currency: Currency = "USD"): string => (currency === "KRW" ? "억 원" : "억 달러");

/** 금액 → "1,691억 달러" / "1,691억 원" (음수는 − 를 붙인다) */
export function eok(v: number | null | undefined, currency: Currency = "USD"): string {
  if (v == null || Number.isNaN(v)) return "–";
  const s = `${Math.round(Math.abs(v) / 1e8).toLocaleString("ko-KR")}${eokUnit(currency)}`;
  return v < 0 ? `−${s}` : s;
}

/** 화면에 보여 줄 종목 이름 — 한글 이름이 있으면 그것, 없으면 원래 이름 */
export const displayName = (r: { name: string; name_local?: string | null }): string => r.name_local || r.name;

export const tickerPlaceholder = (market: Market): string => (market === "kr" ? "종목 코드 (예: 005930)" : "종목 기호 (예: NVDA)");
/** 입력칸의 글자 → 보낼 종목 표기(앞뒤 공백 제거, 대문자). 국내 코드는 신규 상장 `0126Z0` 처럼 영문이 섞일 수 있다 */
export const tickerInput = (_market: Market, s: string): string => s.trim().toUpperCase();
/** Worker 와 같은 종목 모양 — 맞지 않으면 담기 단추를 막는다 */
export const tickerInputValid = (market: Market, s: string): boolean => (market === "kr" ? /^[0-9][0-9A-Z]{5}$/ : /^[A-Z][A-Z0-9.\-]{0,9}$/).test(tickerInput(market, s));
export const indexLabel = (market: Market): string => (market === "kr" ? "코스피" : "S&P 500(SPY)");
/** "다음 갱신(…) 때 들어옵니다" 의 시각 */
export const nextRunText = (market: Market): string => (market === "kr" ? "월~금 16:30" : "화~토 07:00");

/** 주소의 ?market= 읽기 — 없거나 모르는 값이면 미국 */
export function marketFromSearch(search: string): Market {
  const m = new URLSearchParams(search).get("market");
  return isMarket(m) ? m : "us";
}
/** 화면 주소 꼬리 — 미국은 market 을 적지 않아 기존 주소 그대로. ?mock 은 유지 */
export function stockQuery(market: Market, mock: boolean): string {
  const q = [market === "us" ? "" : `market=${market}`, mock ? "mock=1" : ""].filter(Boolean).join("&");
  return q ? `?${q}` : "";
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

/** 관심 목록 순서대로 줄을 만든다. 판에 아직 없는 종목은 "자료를 받는 중", 판이 "받지 못함"이라 적은 종목은 missing */
export function watchRows(board: Board | null, watch: string[]): WatchRow[] {
  const byT = new Map((board?.rows ?? []).map((r) => [r.t, r] as const));
  const miss = new Set(board?.missing ?? []);
  return watch.map((t) => {
    const r = byT.get(t);
    return r ? { ...r, pending: false as const } : { t, pending: true as const, missing: miss.has(t) };
  });
}

/** 발굴 판: 관점 단추(걸린 수)와 카드 목록. 전체는 겹친 관점이 많은 순, 같으면 거래대금 배수가 큰 순 */
export function discoverView(board: Board | null, lens: LensId | "all"): { tabs: { id: LensId | "all"; label: string; count: number }[]; cards: BoardRow[]; rule: string; total: number; universe: number } {
  const rows = board?.rows ?? [];
  const hit = rows.filter((r) => r.lenses.length > 0);
  const tabs: { id: LensId | "all"; label: string; count: number }[] = [
    { id: "all", label: "전체", count: hit.length },
    ...LENS_ORDER.map((id) => ({ id, label: board?.lens_info[id].label ?? LENS_LABEL[id], count: hit.filter((r) => r.lenses.some((x) => x.id === id)).length })),
  ];
  const cards = hit
    .filter((r) => lens === "all" || r.lenses.some((x) => x.id === lens))
    .sort((a, b) => b.lenses.length - a.lenses.length || (b.dv_ratio ?? 0) - (a.dv_ratio ?? 0) || a.t.localeCompare(b.t));
  const rule = lens === "all" ? "여러 관점에 동시에 걸린 종목이 위에 옵니다." : board?.lens_info[lens].rule ?? "";
  return { tabs, cards, rule, total: hit.length, universe: board?.universe ?? rows.length };
}

export function lensDaysText(n: number): string {
  if (!n) return "기준 채점: 아직 기록이 없어요";
  return `기준 채점: 기록 ${n}일째 — 관점별 성적은 표본이 30건·20일 쌓인 뒤에 보여 드립니다(아직 판단하기 이릅니다)`;
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
    { kind: "earnings", title: "실적 발표가 가까운 종목", body: soon.length ? soon.map((x) => `${displayName(x.r)} ${monthDay(x.r.next_earn as string)}`).join(", ") : `${FLAG_EARN_DAYS}일 안에 예정된 발표가 없어요` },
    { kind: "warn", title: "경고가 가장 많은 종목", body: worst ? `${displayName(worst)} · 경고 ${worst.n_warn}개 (${worst.warn_keys.join("·")})` : "경고가 있는 종목이 없어요" },
    { kind: "high", title: "1년 최고가 근처", body: near.length ? near.map((r) => `${displayName(r)} ${pctText(r.off_hi_pct)}`).join(", ") : `최고가 ${FLAG_NEAR_HIGH_PCT}% 안쪽에 있는 종목이 없어요` },
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
/** 받은 값이 정확히 "KRW" 일 때만 원화. 값이 아예 없을 때만 시장(kr)을 따른다 */
const currencyOf = (v: unknown, market: string): Currency => (v === "KRW" || (v === undefined && market === "kr") ? "KRW" : "USD");
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const nums = (v: unknown): number[] => arr(v).filter((x): x is number => typeof x === "number" && Number.isFinite(x));

const lensHits = (v: unknown): LensHit[] =>
  arr(v).filter(isObj).filter((x) => (LENS_ORDER as string[]).includes(x.id as string)).map((x) => ({ id: x.id as LensId, why: str(x.why) }))
    .filter((x, i, all) => all.findIndex((y) => y.id === x.id) === i); // 같은 관점은 첫 번째만 — 화면의 key 가 겹치지 않게

function lensInfo(v: unknown): Board["lens_info"] {
  const src = isObj(v) ? v : {};
  const out = {} as Board["lens_info"];
  for (const id of LENS_ORDER) {
    const o = isObj(src[id]) ? (src[id] as Obj) : {};
    out[id] = { label: str(o.label, LENS_LABEL[id]) || LENS_LABEL[id], rule: str(o.rule) };
  }
  return out;
}

export function normalizeBoard(input: unknown): Board | null {
  if (!isObj(input) || !Array.isArray(input.rows)) return null;
  const rows: BoardRow[] = [];
  for (const raw of input.rows) {
    if (!isObj(raw) || typeof raw.t !== "string" || !raw.t) continue;
    rows.push({
      t: raw.t, name: str(raw.name, raw.t), ...(typeof raw.name_local === "string" && raw.name_local ? { name_local: raw.name_local } : {}), currency: currencyOf(raw.currency, str(input.market)), price: numOr(raw.price, 0), chg_pct: num(raw.chg_pct), spark: nums(raw.spark), ath_pct: num(raw.ath_pct), off_hi_pct: num(raw.off_hi_pct),
      fpe: num(raw.fpe), n_pass: numOr(raw.n_pass, 0), n_care: numOr(raw.n_care, 0), n_warn: numOr(raw.n_warn, 0), diag: str(raw.diag), next_earn: strOrNull(raw.next_earn),
      warn_keys: arr(raw.warn_keys).filter((x): x is string => typeof x === "string"),
      sector: str(raw.sector), rev_g: num(raw.rev_g), nde: num(raw.nde), dv_ratio: num(raw.dv_ratio), lenses: lensHits(raw.lenses),
    });
  }
  return { market: str(input.market), as_of: str(input.as_of), ...(typeof input.generated_at === "string" ? { generated_at: input.generated_at } : {}), universe: num(input.universe), rows,
    missing: arr(input.missing).filter((x): x is string => typeof x === "string"), lens_info: lensInfo(input.lens_info), lens_score: lensScore(input.lens_score), score_gate: scoreGate(input.score_gate) };
}

/** 성적을 숫자로 보여 주는 최소 표본. 없거나 틀리면 기본값(30건·20일) */
function scoreGate(v: unknown): ScoreGate {
  const o = isObj(v) ? v : {};
  const pos = (x: unknown, d: number) => (typeof x === "number" && Number.isInteger(x) && x > 0 ? x : d);
  return { min_n: pos(o.min_n, DEFAULT_SCORE_GATE.min_n), min_days: pos(o.min_days, DEFAULT_SCORE_GATE.min_days) };
}

const SCORE_KEYS: ScoreHorizon[] = ["1w", "1m", "3m"];
/** 관점 성적판: 네 관점 × 세 기간이 모두 {n·days 0 이상의 정수(days 가 없으면 0), avg·win 숫자 또는 null} 일 때만. 하나라도 틀리면 통째로 null */
function lensScore(v: unknown): Board["lens_score"] {
  if (!isObj(v)) return null;
  const out = {} as NonNullable<Board["lens_score"]>;
  for (const id of LENS_ORDER) {
    const o = v[id];
    if (!isObj(o)) return null;
    const row = {} as Record<ScoreHorizon, Score>;
    for (const k of SCORE_KEYS) {
      const c = o[k];
      if (!isObj(c) || typeof c.n !== "number" || !Number.isInteger(c.n) || c.n < 0) return null;
      if (c.days !== undefined && (typeof c.days !== "number" || !Number.isInteger(c.days) || c.days < 0)) return null;
      if ((c.avg !== null && num(c.avg) === null) || (c.win !== null && num(c.win) === null)) return null;
      row[k] = { n: c.n, days: (c.days as number | undefined) ?? 0, avg: c.avg as number | null, win: c.win as number | null };
    }
    out[id] = row;
  }
  return out;
}

const STATES: readonly string[] = ["pass", "care", "warn", "na"];

export function normalizeDoc(input: unknown): TickerDoc | null {
  if (!isObj(input) || !isObj(input.rec)) return null;
  const r = input.rec;
  if (typeof r.t !== "string" || !r.t || num(r.price) === null) return null;
  const tgt = isObj(r.tgt) && num(r.tgt.mean) !== null ? { mean: r.tgt.mean as number, lo: num(r.tgt.lo), hi: num(r.tgt.hi), n: numOr(r.tgt.n, 0) } : null;
  const rec: StockRecord = {
    t: r.t, name: str(r.name, r.t), name_local: strOrNull(r.name_local) || null, currency: currencyOf(r.currency, str(input.market)), exchange: str(r.exchange), sector: str(r.sector), financial: r.financial === true, as_of: str(r.as_of), price: r.price as number, chg_pct: num(r.chg_pct),
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
  const events = arr(input.events).filter(isObj).filter((e) => typeof e.date === "string" && typeof e.kind === "string").map((e) => ({ date: e.date as string, kind: e.kind as string }));
  const news = input.news === null ? null : arr(input.news).filter(isObj).filter((n) => typeof n.title === "string" && typeof n.url === "string" && n.url.startsWith("https://"))
    .slice(0, 8).map((n) => ({ title: n.title as string, source: str(n.source), date: str(n.date), url: n.url as string }));
  return { market: str(input.market), as_of: str(input.as_of), rec, checks, diag: str(input.diag), peers, ref, lenses: lensHits(input.lenses), events, news };
}

// ---- 저장된 해석(opinion): 사람이 대화에서 요청해 AI 가 쓴 글. 받은 값은 믿지 않고 글자로만 그린다 ----
const SRCS: readonly string[] = ["재무", "시세", "뉴스", "전망"];
export const OPINION_MAX = 20;
const cut = (v: string, n: number) => v.slice(0, n);
const evidence = (v: unknown): { text: string; src: EvidenceSrc }[] =>
  arr(v).filter(isObj).filter((e) => typeof e.text === "string" && SRCS.includes(e.src as string)).slice(0, 6).map((e) => ({ text: cut(e.text as string, 300), src: e.src as EvidenceSrc }));

export function normalizeOpinions(input: unknown): Opinion[] {
  const list = Array.isArray(input) ? input : isObj(input) ? arr(input.items) : [];
  const out: Opinion[] = [];
  for (const o of list) {
    if (!isObj(o) || typeof o.id !== "string" || !o.id || num(o.price) === null || typeof o.as_of !== "string" || typeof o.verdict !== "string") continue;
    out.push({ id: o.id, price: o.price as number, as_of: o.as_of, next_earn: strOrNull(o.next_earn), verdict: cut(o.verdict, 300), good: evidence(o.good), bad: evidence(o.bad),
      watch: arr(o.watch).filter((w): w is string => typeof w === "string").slice(0, 6).map((w) => cut(w, 200)) });
  }
  return out.sort((a, b) => (a.id < b.id ? 1 : a.id > b.id ? -1 : 0)).slice(0, OPINION_MAX);
}

/** 기준 지수(1년 종가) — 날짜순으로 맞춘다. 쓸 점이 하나도 없으면 null */
export function normalizeIndex(input: unknown): IndexDoc | null {
  if (!isObj(input) || !Array.isArray(input.closes)) return null;
  const closes = input.closes.filter((p): p is [string, number] => Array.isArray(p) && typeof p[0] === "string" && num(p[1]) !== null).map((p) => [p[0], p[1]] as [string, number])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return closes.length ? { t: str(input.t), closes } : null;
}

const round1 = (v: number): number => Math.round(v * 10) / 10 + 0; // + 0 : -0 → 0
const dayNum = (iso: string): number => Math.round(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / 86400000);

export const STALE_DAYS = 30;
export const STALE_MOVE_PCT = 20;

/** 해석을 쓴 날(KST). id 는 서버가 붙인 UTC 시각이라 9시간을 더해 한국 날짜로 읽는다 */
export function opinionDateKst(op: Pick<Opinion, "id">): string {
  const t = Date.parse(op.id);
  return Number.isNaN(t) ? op.id.slice(0, 10) : new Date(t + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

/** 해석이 오래된 이유 목록(없으면 []). todayIso 는 호출하는 쪽이 정한 오늘(KST) 날짜 */
export function opinionStale(op: Opinion, rec: { price: number }, todayIso: string): string[] {
  const why: string[] = [];
  const age = dayNum(todayIso) - dayNum(opinionDateKst(op));
  if (age > STALE_DAYS) why.push(`쓴 지 ${age}일 지남`);
  if (op.next_earn && op.next_earn < todayIso) why.push("그 뒤 실적 발표가 있었음");
  if (op.price > 0) {
    const move = round1((rec.price / op.price - 1) * 100);
    if (Math.abs(move) > STALE_MOVE_PCT) why.push(`주가가 ${pctText(move)} 움직임`);
  }
  return why;
}

export const OPINION_HORIZONS = [{ key: "1w", label: "1주", days: 7 }, { key: "1m", label: "1개월", days: 30 }, { key: "3m", label: "3개월", days: 91 }] as const;

/** 해석 기준일(as_of, 거래일) + N일 이후 첫 점의 수익률. 종목은 쓸 때 주가(op.price), 지수는 기준일 이후 첫 점이 출발점. 그래프 끝을 넘으면 아직 — 전부 null */
export function opinionReturns(op: Opinion, chart: [string, number][], index: IndexDoc | null): { key: string; label: string; ret: number | null; idx: number | null; excess: number | null }[] {
  const written = dayNum(op.as_of);
  const iso = (n: number) => new Date(n * 86400000).toISOString().slice(0, 10);
  const firstOn = (pts: [string, number][], d: string) => pts.find(([x]) => x >= d);
  const closes = index?.closes ?? [];
  const base = Number.isNaN(written) ? undefined : firstOn(closes, iso(written));
  return OPINION_HORIZONS.map(({ key, label, days }) => {
    const none = { key, label, ret: null, idx: null, excess: null };
    if (Number.isNaN(written) || op.price <= 0) return none;
    const at = firstOn(chart, iso(written + days));
    if (!at) return none;
    const ret = round1((at[1] / op.price - 1) * 100);
    const ip = firstOn(closes, iso(written + days));
    const idx = base && ip && base[1] > 0 ? round1((ip[1] / base[1] - 1) * 100) : null;
    return { key, label, ret, idx, excess: idx === null ? null : round1(ret - idx) };
  });
}

/** 관점 성적 한 줄. 표본(건수·날짜 수)이 기준에 이르기 전에는 판단하지 않는다 */
export function scoreText(s: Score | null | undefined, gate: ScoreGate = DEFAULT_SCORE_GATE): string {
  if (!s || s.n <= 0) return "아직 잴 수 있는 기록이 없어요";
  if (s.n < gate.min_n || s.days < gate.min_days) return `표본 ${s.n}건 · ${s.days}일 — 아직 판단하기 이릅니다`;
  const avg = s.avg === null ? "–" : `${s.avg > 0 ? "+" : ""}${s.avg.toFixed(1)}%p`;
  return `${s.n}건 · ${s.days}일 · 지수 대비 평균 ${avg} · 이긴 비율 ${s.win === null ? "–" : `${s.win.toFixed(1)}%`}`;
}

/** 관심 담기·빼기 실패 안내 문구 */
export function watchErrorText(status: number, code: string | undefined, market: Market = "us"): string {
  if (status === 503) return "저장 공간이 아직 연결되지 않았어요";
  if (code === "watch_full") return "관심 종목은 100개까지 담을 수 있어요";
  if (code === "bad_request") return market === "kr" ? "종목 코드를 확인해 주세요 (예: 005930)" : "종목 기호를 확인해 주세요 (예: NVDA)";
  if (code === "forbidden") return "이 화면에서만 담을 수 있어요";
  return "잠시 뒤 다시 해 주세요";
}
