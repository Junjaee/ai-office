import { test } from "node:test";
import assert from "node:assert/strict";
import { STATE_META, money, pctText, tone, eok, polyPoints, monthDay, daysUntil, earnText, watchRows, buildFlags, chartGeometry, normalizeBoard, normalizeDoc, watchErrorText, discoverView, lensDaysText, normalizeOpinions, normalizeIndex, opinionStale, opinionReturns, scoreText, OPINION_HORIZONS } from "../app/stock-rules.ts";

const row = (o = {}) => ({ t: "AAA", name: "A", price: 100, chg_pct: 1.2, spark: [1, 2, 3], ath_pct: -5, off_hi_pct: -5, fpe: 12, n_pass: 5, n_care: 1, n_warn: 1, diag: "좋음: 가치", next_earn: "2026-10-22", warn_keys: ["빚"], sector: "Tech", rev_g: 5, nde: 1, dv_ratio: 1.2, lenses: [], ...o });

test("숫자 문구", () => {
  assert.equal(money(142.3), "$142.30");
  assert.equal(money(1097.39), "$1,097.39");
  assert.equal(money(null), "–");
  assert.equal(pctText(1.234), "+1.2%");
  assert.equal(pctText(-57.9, 0), "-58%");
  assert.equal(pctText(0.01), "0.0%");
  assert.equal(pctText(null), "–");
  assert.equal(tone(0.3), "up"); assert.equal(tone(-0.3), "down"); assert.equal(tone(0.01), "flat"); assert.equal(tone(null), "flat");
  assert.equal(eok(169.1e9), "1,691억 달러");
  assert.equal(eok(-45.9e9), "−459억 달러");
});

test("상태 이름표: 색만이 아니라 글자·아이콘 이름이 있다", () => {
  assert.deepEqual(Object.keys(STATE_META), ["pass", "care", "warn", "na"]);
  assert.equal(STATE_META.pass.label, "통과"); assert.equal(STATE_META.care.label, "주의");
  assert.equal(STATE_META.warn.label, "경고"); assert.equal(STATE_META.na.label, "자료 없음");
  for (const m of Object.values(STATE_META)) assert.ok(m.cls && m.icon);
});

test("흐름선 좌표: 처음은 왼쪽, 끝은 오른쪽, 높은 값이 위", () => {
  assert.equal(polyPoints([1, 3, 2], 100, 30, 2), "0.0,28.0 50.0,2.0 100.0,15.0");
  assert.equal(polyPoints([5, 5], 100, 30, 2), "0.0,15.0 100.0,15.0");
  assert.equal(polyPoints([], 100, 30), "");
});

test("날짜 문구", () => {
  assert.equal(monthDay("2026-10-22"), "10월 22일");
  assert.equal(daysUntil("2026-10-22", "2026-10-05"), 17);
  assert.equal(daysUntil(null, "2026-10-05"), null);
  assert.deepEqual(earnText("2026-10-22", "2026-10-05"), { date: "10월 22일", days: "17일 뒤" });
  assert.deepEqual(earnText("2026-10-05", "2026-10-05"), { date: "10월 5일", days: "오늘" });
  assert.deepEqual(earnText("2026-10-01", "2026-10-05"), { date: "10월 1일", days: "지남" });
  assert.deepEqual(earnText(null, "2026-10-05"), { date: "–", days: "" });
});

test("관심 줄: 관심 목록 순서대로, 아직 자료가 없는 종목은 받는 중", () => {
  const board = { market: "us", as_of: "2026-10-02", rows: [row({ t: "AAA" }), row({ t: "BBB" })] };
  const out = watchRows(board, ["BBB", "NEW", "AAA"]);
  assert.deepEqual(out.map((r) => [r.t, r.pending]), [["BBB", false], ["NEW", true], ["AAA", false]]);
  assert.deepEqual(watchRows(null, ["X"]).map((r) => [r.t, r.pending]), [["X", true]]);
});

test("관심 줄: 판의 missing 에 든 종목은 찾지 못함으로 표시", () => {
  const board = normalizeBoard({ market: "us", as_of: "2026-10-02", rows: [row({ t: "AAA" })], missing: ["BAD", 7] });
  assert.deepEqual(board.missing, ["BAD"]);
  assert.deepEqual(normalizeBoard({ rows: [] }).missing, []);
  const out = watchRows(board, ["AAA", "BAD", "NEW"]);
  assert.deepEqual(out.map((r) => [r.t, r.pending, r.pending && r.missing]), [["AAA", false, false], ["BAD", true, true], ["NEW", true, false]]);
});

test("오늘 먼저 볼 것 세 칸", () => {
  const rows = [row({ t: "A", name: "가", next_earn: "2026-10-22", n_warn: 0, warn_keys: [], off_hi_pct: -0.8 }),
    row({ t: "B", name: "나", next_earn: "2026-12-11", n_warn: 3, warn_keys: ["빚", "현금흐름", "추세"], off_hi_pct: -57 }),
    row({ t: "C", name: "다", next_earn: null, n_warn: 1, off_hi_pct: -12 })];
  const f = buildFlags(rows, "2026-10-05");
  assert.deepEqual(f.map((x) => x.kind), ["earnings", "warn", "high"]);
  assert.equal(f[0].body, "가 10월 22일");
  assert.equal(f[1].body, "나 · 경고 3개 (빚·현금흐름·추세)");
  assert.equal(f[2].body, "가 -0.8%");
  const none = buildFlags([row({ next_earn: null, n_warn: 0, warn_keys: [], off_hi_pct: -40 })], "2026-10-05");
  assert.equal(none[0].body, "30일 안에 예정된 발표가 없어요");
  assert.equal(none[1].body, "경고가 있는 종목이 없어요");
  assert.equal(none[2].body, "최고가 3% 안쪽에 있는 종목이 없어요");
  assert.equal(buildFlags([], "2026-10-05").length, 3);
});

test("그래프 좌표와 큰 변동일 표시", () => {
  const chart = [["2026-01-02", 100], ["2026-04-01", 200], ["2026-07-01", 150], ["2026-10-02", 120]];
  const g = chartGeometry(chart, [{ date: "2026-04-01", pct: 12.3, close: 200 }, { date: "2020-01-01", pct: 9, close: 1 }]);
  assert.equal(g.points.split(" ").length, 4);
  assert.equal(g.marks.length, 1);                       // 그래프 범위 밖 날짜는 뺀다
  assert.deepEqual({ n: g.marks[0].n, left: g.marks[0].left, when: g.marks[0].when, text: g.marks[0].text },
    { n: 1, left: "33.33%", when: "4월 1일", text: "하루에 +12.3% 움직임" });
  assert.equal(g.yMax, 200); assert.equal(g.yMin, 100);
  assert.deepEqual(g.xLabels, ["26.01", "26.04", "26.07", "26.10"]);
  assert.equal(chartGeometry([], []).points, "");
});

test("판 자료 정리: 깨진 자료는 null, 줄은 모양을 맞춘다", () => {
  assert.equal(normalizeBoard(null), null);
  assert.equal(normalizeBoard({}), null);
  assert.equal(normalizeBoard({ rows: "x" }), null);
  const b = normalizeBoard({ rows: [{}, { t: "AAA" }, 5] });
  assert.equal(b.rows.length, 1);
  assert.deepEqual({ t: b.rows[0].t, name: b.rows[0].name, spark: b.rows[0].spark, warn_keys: b.rows[0].warn_keys, n_warn: b.rows[0].n_warn, fpe: b.rows[0].fpe, price: b.rows[0].price, next_earn: b.rows[0].next_earn },
    { t: "AAA", name: "AAA", spark: [], warn_keys: [], n_warn: 0, fpe: null, price: 0, next_earn: null });
  const good = { market: "us", as_of: "2026-10-02", rows: [row(), row({ t: "BBB" })] };
  const n = normalizeBoard(good);
  assert.equal(n.market, "us"); assert.equal(n.as_of, "2026-10-02");
  assert.deepEqual(n.rows, good.rows);
  assert.doesNotThrow(() => { const w = watchRows(b, ["AAA", "ZZZ"]); buildFlags(w.filter((r) => !r.pending), "2026-10-05"); });
});

test("종목 자료 정리: 깨진 자료는 null, 없는 칸은 기본값", () => {
  assert.equal(normalizeDoc({}), null);
  assert.equal(normalizeDoc({ rec: {} }), null);
  const d = normalizeDoc({ rec: { t: "ORCL", price: 1 }, checks: [{ key: "빚", state: "weird", text: "x" }, { state: "pass" }], peers: "nope" });
  assert.equal(d.checks.length, 1); assert.equal(d.checks[0].state, "na");
  assert.deepEqual(d.peers, []);
  assert.equal(d.ref.label, "시장");
  assert.deepEqual([d.rec.annual, d.rec.chart, d.rec.moves, d.rec.tgt], [[], [], [], null]);
  assert.equal(d.rec.name, "ORCL");
  assert.doesNotThrow(() => chartGeometry(d.rec.chart, d.rec.moves));
  const full = normalizeDoc({ market: "us", as_of: "2026-10-02", diag: "d", rec: { t: "X", price: 2, chart: [["2026-01-02", 1], ["bad"], ["2026-01-03", "x"]], moves: [{ date: "2026-01-02", pct: 8, close: 1 }, {}], annual: [{ fy: 2025, rev: 1 }, { rev: 2 }], tgt: { mean: 5, n: 3 } }, peers: [{ t: "P", name: "Pn", fpe: 10 }, { t: "Q" }], ref: { fpe: 20, label: "S&P" } });
  assert.deepEqual(full.rec.chart, [["2026-01-02", 1]]);
  assert.equal(full.rec.moves.length, 1);
  assert.deepEqual(full.rec.annual, [{ fy: 2025, rev: 1, ni: null, capex: null, fcf: null }]);
  assert.deepEqual(full.rec.tgt, { mean: 5, lo: null, hi: null, n: 3 });
  assert.equal(full.peers.length, 1); assert.deepEqual(full.ref, { fpe: 20, opm: null, label: "S&P" });
  assert.equal(full.diag, "d");
});

test("관심 담기 실패 문구", () => {
  assert.equal(watchErrorText(503, undefined), "저장 공간이 아직 연결되지 않았어요");
  assert.equal(watchErrorText(409, "watch_full"), "관심 종목은 100개까지 담을 수 있어요");
  assert.equal(watchErrorText(400, "bad_request"), "종목 기호를 확인해 주세요 (예: NVDA)");
  assert.equal(watchErrorText(403, "forbidden"), "이 화면에서만 담을 수 있어요");
  assert.equal(watchErrorText(500, undefined), "잠시 뒤 다시 해 주세요");
});

const lrow = (t, ids, extra = {}) => ({ t, name: t, price: 10, lenses: ids.map((id) => ({ id, why: `${id} 이유` })), ...extra });

test("normalizeBoard: 관점은 아는 id 만, 이유는 글자만 남긴다", () => {
  const b = normalizeBoard({ market: "us", as_of: "2026-10-02", rows: [
    { t: "A", price: 1, sector: "Tech", rev_g: 12.5, nde: "x", dv_ratio: 1.7, lenses: [{ id: "value", why: "w" }, { id: "hack", why: "x" }, { id: "flow" }, "bad"] },
    { t: "B", price: 1 },
  ], lens_info: { value: { label: "<b>싸고</b>", rule: 5 }, bogus: { label: "x", rule: "y" } } });
  assert.deepEqual(b.rows[0].lenses, [{ id: "value", why: "w" }, { id: "flow", why: "" }]);
  assert.deepEqual([b.rows[0].sector, b.rows[0].rev_g, b.rows[0].nde, b.rows[0].dv_ratio], ["Tech", 12.5, null, 1.7]);
  assert.deepEqual(b.rows[1].lenses, []);
  assert.deepEqual(Object.keys(b.lens_info), ["value", "growth", "event", "flow"]);
  assert.equal(b.lens_info.value.label, "<b>싸고</b>");   // 글자 그대로 — React 가 글자로 그린다
  assert.equal(b.lens_info.value.rule, "");
  assert.equal(b.lens_info.growth.label, "실적 개선");
});

test("discoverView: 전체는 겹친 관점이 많은 순, 단추마다 걸린 수", () => {
  const board = normalizeBoard({ market: "us", as_of: "2026-10-02", rows: [
    lrow("ONE", ["flow"], { dv_ratio: 3 }), lrow("NONE", []), lrow("TWO", ["value", "growth"]), lrow("ONEB", ["flow"], { dv_ratio: 5 }),
  ], lens_info: { flow: { label: "돈 몰림", rule: "기준 문장" } } });
  const all = discoverView(board, "all");
  assert.deepEqual(all.cards.map((r) => r.t), ["TWO", "ONEB", "ONE"]);       // 같은 수면 거래대금 배수가 큰 순
  assert.deepEqual(all.tabs.map((t) => [t.id, t.count]), [["all", 3], ["value", 1], ["growth", 1], ["event", 0], ["flow", 2]]);
  assert.equal(all.total, 3);
  assert.equal(all.universe, 4);
  const flow = discoverView(board, "flow");
  assert.deepEqual(flow.cards.map((r) => r.t), ["ONEB", "ONE"]);
  assert.equal(flow.rule, "기준 문장");
  assert.deepEqual(discoverView(null, "all").cards, []);
});

test("normalizeBoard: 같은 관점이 여러 번 와도 첫 번째만", () => {
  const b = normalizeBoard({ rows: [{ t: "A", price: 1, lenses: [{ id: "flow", why: "첫째" }, { id: "value", why: "v" }, { id: "flow", why: "둘째" }] }] });
  assert.deepEqual(b.rows[0].lenses, [{ id: "flow", why: "첫째" }, { id: "value", why: "v" }]);
  assert.deepEqual(normalizeDoc({ rec: { t: "A", price: 1 }, lenses: [{ id: "event", why: "a" }, { id: "event", why: "b" }] }).lenses, [{ id: "event", why: "a" }]);
});

test("Board.universe: 숫자면 그대로, 아니면 null — 발굴 판은 없을 때 줄 수로 센다", () => {
  assert.equal(normalizeBoard({ rows: [], universe: 480 }).universe, 480);
  assert.equal(normalizeBoard({ rows: [], universe: "x" }).universe, null);
  assert.equal(normalizeBoard({ rows: [] }).universe, null);
  const withUni = normalizeBoard({ rows: [lrow("A", ["flow"]), lrow("B", [])], universe: 480 });
  assert.equal(discoverView(withUni, "all").universe, 480);
  assert.equal(discoverView(normalizeBoard({ rows: [lrow("A", []), lrow("B", [])] }), "all").universe, 2);
});

test("normalizeDoc: 관점과 공시 목록", () => {
  const d = normalizeDoc({ rec: { t: "A", price: 1 }, lenses: [{ id: "event", why: "w" }, { id: "nope", why: "" }], events: [{ date: "2026-09-30", kind: "실적 발표" }, { date: 5, kind: "x" }, null] });
  assert.deepEqual(d.lenses, [{ id: "event", why: "w" }]);
  assert.deepEqual(d.events, [{ date: "2026-09-30", kind: "실적 발표" }]);
  assert.deepEqual(normalizeDoc({ rec: { t: "A", price: 1 } }).events, []);
});

test("lensDaysText", () => {
  assert.equal(lensDaysText(0), "기준 채점: 아직 기록이 없어요");
  assert.match(lensDaysText(12), /기록 12일째/);
  assert.match(lensDaysText(12), /판단하기 이릅니다/);
});

// ---- 3단계: 해석·오래됨·수익률·관점 성적 ----
const rawOp = (o = {}) => ({ id: "2026-10-06T09:12:33.000Z", price: 142.3, as_of: "2026-10-02", next_earn: "2026-12-10", verdict: "한 줄", good: [{ text: "좋다", src: "재무" }], bad: [{ text: "나쁘다", src: "시세" }], watch: ["볼 것"], ...o });

test("normalizeOpinions: 정상 값은 그대로, 최신순", () => {
  const out = normalizeOpinions([rawOp({ id: "2026-09-01T00:00:00.000Z" }), rawOp()]);
  assert.deepEqual(out.map((o) => o.id), ["2026-10-06T09:12:33.000Z", "2026-09-01T00:00:00.000Z"]);
  assert.deepEqual(out[0], rawOp());
  assert.deepEqual(normalizeOpinions(null), []);
  assert.deepEqual(normalizeOpinions({}), []);
  assert.deepEqual(normalizeOpinions([null, "x", 3]), []);
});

test("normalizeOpinions: <script> 는 지우지 않고 글자로 둔다, 길이만 자른다", () => {
  const [o] = normalizeOpinions([rawOp({ verdict: "<script>alert(1)</script>" + "가".repeat(400), good: [{ text: "<b>x</b>" + "나".repeat(400), src: "뉴스" }], watch: ["<i>w</i>" + "다".repeat(300)] })]);
  assert.ok(o.verdict.startsWith("<script>alert(1)</script>"));
  assert.equal(o.verdict.length, 300);
  assert.ok(o.good[0].text.startsWith("<b>x</b>"));
  assert.equal(o.good[0].text.length, 300);
  assert.ok(o.watch[0].startsWith("<i>w</i>"));
  assert.equal(o.watch[0].length, 200);
});

test("normalizeOpinions: 이상한 src 근거는 버리고, 깨진 해석은 통째로 버린다", () => {
  const [o] = normalizeOpinions([rawOp({ good: [{ text: "a", src: "재무" }, { text: "b", src: "소문" }, { text: 5, src: "뉴스" }, "x"], bad: [{ text: "c", src: "전망" }], watch: ["w", 3, null] })]);
  assert.deepEqual(o.good, [{ text: "a", src: "재무" }]);
  assert.deepEqual(o.bad, [{ text: "c", src: "전망" }]);
  assert.deepEqual(o.watch, ["w"]);
  assert.deepEqual(normalizeOpinions([rawOp({ price: "142.3" })]), []);   // price 가 문자열이면 그 해석을 버린다
  assert.deepEqual(normalizeOpinions([rawOp({ id: 5 })]), []);
  assert.deepEqual(normalizeOpinions([rawOp({ verdict: 5 })]), []);
  assert.deepEqual(normalizeOpinions([rawOp({ as_of: null })]), []);
  assert.equal(normalizeOpinions([rawOp({ next_earn: 5 })])[0].next_earn, null);
});

test("normalizeOpinions: 21개 중 최신 20개", () => {
  const many = Array.from({ length: 21 }, (_, i) => rawOp({ id: `2026-09-${String(i + 1).padStart(2, "0")}T00:00:00.000Z` }));
  const out = normalizeOpinions(many);
  assert.equal(out.length, 20);
  assert.equal(out[0].id, "2026-09-21T00:00:00.000Z");
  assert.equal(out[19].id, "2026-09-02T00:00:00.000Z");   // 가장 오래된 하나가 잘림
});

test("normalizeIndex", () => {
  assert.deepEqual(normalizeIndex({ t: "SPY", closes: [["2025-10-07", 2], ["2025-10-06", 1], ["x", "y"], [5, 5], "z"] }), { t: "SPY", closes: [["2025-10-06", 1], ["2025-10-07", 2]] });
  assert.equal(normalizeIndex(null), null);
  assert.equal(normalizeIndex({ t: "SPY" }), null);
  assert.equal(normalizeIndex({ t: "SPY", closes: [] }), null);
  assert.equal(normalizeIndex({ t: "SPY", closes: [["a", "b"]] }), null);
});

test("normalizeDoc: news 는 https 링크만, 최대 8개, 없으면 []", () => {
  const n = (i, url = "https://x.test/a") => ({ title: `제목${i}`, source: "S", date: "2026-10-03", url });
  const d = normalizeDoc({ rec: { t: "A", price: 1 }, news: [n(1), n(2, "http://x.test"), n(3, "javascript:alert(1)"), { title: "t", url: "https://a" }, "x", ...Array.from({ length: 10 }, (_, i) => n(10 + i))] });
  assert.equal(d.news.length, 8);
  assert.deepEqual(d.news[0], n(1));
  assert.ok(d.news.every((x) => x.url.startsWith("https://")));
  assert.deepEqual(normalizeDoc({ rec: { t: "A", price: 1 } }).news, []);
  assert.deepEqual(normalizeDoc({ rec: { t: "A", price: 1 }, news: "x" }).news, []);
});

const cell = (n, avg, win) => ({ n, avg, win });
const lensRow = (c) => ({ "1w": c, "1m": c, "3m": c });
const goodScore = () => ({ value: lensRow(cell(120, 0.4, 52.5)), growth: lensRow(cell(0, null, null)), event: lensRow(cell(5, -1.2, 40)), flow: lensRow(cell(30, null, null)) });

test("normalizeBoard: lens_score 는 모양이 맞을 때만, 아니면 통째로 null", () => {
  assert.deepEqual(normalizeBoard({ rows: [], lens_score: goodScore() }).lens_score, goodScore());
  assert.equal(normalizeBoard({ rows: [] }).lens_score, null);
  assert.equal(normalizeBoard({ rows: [], lens_score: "x" }).lens_score, null);
  const noFlow = goodScore(); delete noFlow.flow;
  assert.equal(normalizeBoard({ rows: [], lens_score: noFlow }).lens_score, null);
  const no3m = goodScore(); delete no3m.value["3m"];
  assert.equal(normalizeBoard({ rows: [], lens_score: no3m }).lens_score, null);
  const badN = goodScore(); badN.event["1m"] = cell(-1, 0, 0);
  assert.equal(normalizeBoard({ rows: [], lens_score: badN }).lens_score, null);
  const fracN = goodScore(); fracN.event["1m"] = cell(1.5, 0, 0);
  assert.equal(normalizeBoard({ rows: [], lens_score: fracN }).lens_score, null);
  const strAvg = goodScore(); strAvg.value["1w"] = cell(3, "0.4", 1);
  assert.equal(normalizeBoard({ rows: [], lens_score: strAvg }).lens_score, null);
  const extra = goodScore(); extra.bogus = lensRow(cell(1, 1, 1)); extra.value["1y"] = cell(1, 1, 1);
  assert.deepEqual(normalizeBoard({ rows: [], lens_score: extra }).lens_score, goodScore());   // 모르는 키는 무시
});

test("opinionStale: 30일·±20%·실적 발표 경계", () => {
  const op = (o = {}) => normalizeOpinions([rawOp({ id: "2026-09-06T00:00:00.000Z", price: 100, next_earn: "2026-12-10", ...o })])[0];
  const rec = { price: 100 };
  assert.deepEqual(opinionStale(op(), rec, "2026-10-06"), []);                                    // 30일
  assert.deepEqual(opinionStale(op(), rec, "2026-10-07"), ["쓴 지 31일 지남"]);                    // 31일
  assert.deepEqual(opinionStale(op({ price: 100 }), { price: 120 }, "2026-10-06"), []);           // +20.0%
  assert.deepEqual(opinionStale(op({ price: 100 }), { price: 80 }, "2026-10-06"), []);            // -20.0%
  assert.deepEqual(opinionStale(op({ price: 100 }), { price: 123.4 }, "2026-10-06"), ["주가가 +23.4% 움직임"]);
  assert.deepEqual(opinionStale(op({ price: 100 }), { price: 70 }, "2026-10-06"), ["주가가 -30.0% 움직임"]);
  assert.deepEqual(opinionStale(op({ next_earn: "2026-10-06" }), rec, "2026-10-06"), []);          // 오늘 발표는 아직
  assert.deepEqual(opinionStale(op({ next_earn: "2026-10-05" }), rec, "2026-10-06"), ["그 뒤 실적 발표가 있었음"]);
  assert.deepEqual(opinionStale(op({ next_earn: null }), rec, "2026-10-06"), []);
  assert.deepEqual(opinionStale(op({ next_earn: "2026-10-05", price: 100 }), { price: 130 }, "2026-10-20"), ["쓴 지 44일 지남", "그 뒤 실적 발표가 있었음", "주가가 +30.0% 움직임"]);
  assert.deepEqual(opinionStale(op({ price: 0 }), rec, "2026-10-06"), []);                          // 0 으로 나누지 않는다
});

test("opinionReturns: 쓴 날 + 7·30·91일 이후 첫 점, 지수는 쓴 날 이후 첫 점이 기준", () => {
  assert.deepEqual(OPINION_HORIZONS, [{ key: "1w", label: "1주", days: 7 }, { key: "1m", label: "1개월", days: 30 }, { key: "3m", label: "3개월", days: 91 }]);
  const op = normalizeOpinions([rawOp({ id: "2026-01-01T09:00:00.000Z", price: 100 })])[0];
  const chart = [["2026-01-01", 99], ["2026-01-09", 110], ["2026-01-31", 120], ["2026-02-10", 90]];
  const idx = { t: "SPY", closes: [["2025-12-31", 400], ["2026-01-02", 500], ["2026-01-08", 510], ["2026-01-31", 550], ["2026-02-10", 450]] };
  const r = opinionReturns(op, chart, idx);
  assert.deepEqual(r.map((x) => x.key), ["1w", "1m", "3m"]);
  assert.deepEqual(r.map((x) => x.label), ["1주", "1개월", "3개월"]);
  // 1주: 1/8 이후 첫 점 = 1/9(110) → +10.0%, 지수 1/8(510) vs 기준 1/2(500) → +2.0%
  assert.deepEqual(r[0], { key: "1w", label: "1주", ret: 10, idx: 2, excess: 8 });
  // 1개월: 1/31 → 120(+20.0%), 지수 550 → +10.0%
  assert.deepEqual(r[1], { key: "1m", label: "1개월", ret: 20, idx: 10, excess: 10 });
  // 3개월: 4/2 → 그래프 끝(2/10)을 넘음 → 아직
  assert.deepEqual(r[2], { key: "3m", label: "3개월", ret: null, idx: null, excess: null });
});

test("opinionReturns: 지수가 없으면 idx·excess 만 null, 끝을 넘는 구간은 전부 null", () => {
  const op = normalizeOpinions([rawOp({ id: "2026-01-01T09:00:00.000Z", price: 100 })])[0];
  const chart = [["2026-01-09", 105.6], ["2026-02-10", 90]];
  const r = opinionReturns(op, chart, null);
  assert.deepEqual(r[0], { key: "1w", label: "1주", ret: 5.6, idx: null, excess: null });   // 소수 1자리
  assert.deepEqual(r[1], { key: "1m", label: "1개월", ret: -10, idx: null, excess: null });
  assert.equal(r[2].ret, null);
  // 지수가 짧아 그 구간 값이 없으면 idx 만 null
  const short = { t: "SPY", closes: [["2026-01-02", 500], ["2026-01-09", 505]] };
  const r2 = opinionReturns(op, chart, short);
  assert.deepEqual(r2[0], { key: "1w", label: "1주", ret: 5.6, idx: 1, excess: 4.6 });
  assert.deepEqual(r2[1], { key: "1m", label: "1개월", ret: -10, idx: null, excess: null });
  assert.deepEqual(opinionReturns(op, [], null).map((x) => x.ret), [null, null, null]);
});

test("scoreText: 표본 부족·없음·충분", () => {
  assert.equal(scoreText({ n: 12, avg: 0.3, win: 50 }), "표본 12건 — 아직 판단하기 이릅니다");
  assert.equal(scoreText({ n: 29, avg: 0.3, win: 50 }), "표본 29건 — 아직 판단하기 이릅니다");
  assert.equal(scoreText({ n: 0, avg: null, win: null }), "아직 잴 수 있는 기록이 없어요");
  assert.equal(scoreText(null), "아직 잴 수 있는 기록이 없어요");
  assert.equal(scoreText(undefined), "아직 잴 수 있는 기록이 없어요");
  assert.equal(scoreText({ n: 120, avg: 0.4, win: 52.5 }), "120건 · 지수 대비 평균 +0.4%p · 이긴 비율 52.5%");
  assert.equal(scoreText({ n: 30, avg: -1.25, win: 40 }), "30건 · 지수 대비 평균 -1.3%p · 이긴 비율 40.0%");
  assert.equal(scoreText({ n: 30, avg: null, win: null }), "30건 · 지수 대비 평균 – · 이긴 비율 –");
});
