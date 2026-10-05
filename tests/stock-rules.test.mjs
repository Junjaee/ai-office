import { test } from "node:test";
import assert from "node:assert/strict";
import { STATE_META, money, pctText, tone, eok, polyPoints, monthDay, daysUntil, earnText, watchRows, buildFlags, chartGeometry, normalizeBoard, normalizeDoc, watchErrorText } from "../app/stock-rules.ts";

const row = (o = {}) => ({ t: "AAA", name: "A", price: 100, chg_pct: 1.2, spark: [1, 2, 3], ath_pct: -5, off_hi_pct: -5, fpe: 12, n_pass: 5, n_care: 1, n_warn: 1, diag: "좋음: 가치", next_earn: "2026-10-22", warn_keys: ["빚"], ...o });

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
