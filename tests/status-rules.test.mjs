import { test } from "node:test";
import assert from "node:assert/strict";
import { NOOP_RUN_MS,
  deriveDeptStatus,
  summarize,
  STALE_HOURS,
  LABELS,
  STATE_CLASS,
  SUBTITLES,
  BANNERS,
  phaseToState,
  deriveAutomationView,
  deriveTaskStates,
  deriveDeptView,
  summarizeTasks,
  collectWarnings,
  relativeTime,
  runningSince,
  LOCAL_REQUEST_TTL_MS,
  RUNNER_WAIT_MS,
  RESULT_WAIT_MS,
  historyLabel,
  durationText,
} from "../app/status-rules.ts";

const now = new Date("2026-09-09T15:00:00+09:00");
const base = { id: "minutes", name: "국회회의록 수집", dept: "research", ok: true, running: false,
  updated_at: "2026-09-09T13:38:12+09:00", summary: "신규 0건", counts: { new: 0, replaced: 0, failed: 0, total: 5894 },
  next_run: "매일 09:00", log: [], link: "" };

// ───────── 구버전 API (status.ts 호환) ─────────

test("정상이고 최근이면 완료", () => {
  assert.equal(deriveDeptStatus(base, now), "완료");
});

test("실행 중이면 진행 중", () => {
  assert.equal(deriveDeptStatus({ ...base, running: true }, now), "진행 중");
});

test("실패면 오류", () => {
  assert.equal(deriveDeptStatus({ ...base, ok: false }, now), "오류");
});

test("STALE_HOURS 넘게 갱신이 없으면 대기", () => {
  const old = new Date(now.getTime() - (STALE_HOURS + 1) * 3600 * 1000).toISOString();
  assert.equal(deriveDeptStatus({ ...base, updated_at: old }, now), "대기");
});

test("summarize: ops·secretary 집계", () => {
  const all = [base, { ...base, id: "news", dept: "brand", ok: false }];
  const s = summarize(all, now);
  assert.equal(s.total, 2);
  assert.equal(s.ok, 1);
  assert.equal(s.error, 1);
  assert.equal(s.opsStatus, "오류");
  assert.match(s.brief, /2개 팀.*1개 정상.*1개 오류/);
});

test("summarize: 실제 팀이 없으면 대기", () => {
  const s = summarize([], now);
  assert.equal(s.opsStatus, "대기");
  assert.match(s.brief, /연결된 자동화 없음/);
});

// ───────── 공통 픽스처 (v2) ─────────

const ms = (n) => n;
const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const iso = (offsetMs) => new Date(now.getTime() + offsetMs).toISOString();

const def = {
  id: "minutes", dept: "research", name: "국회회의록 수집", workflow: "minutes.yml", schedule: "매일 09:00",
  tasks: [
    { id: "collect", name: "회의록 수집", role: "수집" },
    { id: "replace", name: "확정본 교체", role: "교체" },
    { id: "summary", name: "요약 작성", role: "요약", planned: true },
  ],
};
const manualDef = { ...def, id: "manual", schedule: undefined };
const plannedDef = { id: "future", dept: "brand", name: "뉴스 요약", tasks: [{ id: "a", name: "A", role: "" }] };

/** 이번 run 의 결과 파일 v2 */
const fileV2 = {
  ...base,
  updated_at: iso(-20 * MIN),
  summary: "신규 3건, 확정본 교체 1건, 1.9분",
  run_id: 100, run_url: "https://github.com/x/y/actions/runs/100", request_id: "req-1", trigger: "manual",
  started_at: iso(-22 * MIN), duration_sec: 112,
  tasks: [
    { id: "collect", status: "done", summary: "신규 3건" },
    { id: "replace", status: "idle", summary: "교체 0건" },
  ],
};
const runOf = (over) => ({ id: 100, status: "completed", conclusion: "success", requestId: "req-1",
  startedAt: iso(-22 * MIN), completedAt: iso(-20 * MIN), url: "https://github.com/x/y/actions/runs/100", ...over });

// ───────── 3.2 문구·매핑 ─────────

test("LABELS·STATE_CLASS 는 5어휘, phase → state 매핑", () => {
  assert.deepEqual(Object.keys(LABELS).sort(), ["done", "error", "idle", "planned", "running"]);
  assert.equal(LABELS.running, "일하는 중");
  assert.equal(STATE_CLASS.idle, "waiting");
  for (const p of ["requested", "queued", "running", "finishing"]) assert.equal(phaseToState(p), "running");
  for (const p of ["planned", "idle", "done", "error"]) assert.equal(phaseToState(p), p);
});

test("상대 시각: 방금/N분 전/N시간 전/N일 전, 시작한 지 N분째", () => {
  assert.equal(relativeTime(iso(-10 * 1000), now), "방금");
  assert.equal(relativeTime(iso(-5 * MIN), now), "5분 전");
  assert.equal(relativeTime(iso(-37 * HOUR), now), "37시간 전");
  assert.equal(relativeTime(iso(-3 * 24 * HOUR), now), "3일 전");
  assert.equal(relativeTime("not-a-date", now), "");
  assert.equal(runningSince(iso(-30 * 1000), now), "시작한 지 1분째");
  assert.equal(runningSince(iso(-7.5 * MIN), now), "시작한 지 7분째");
});

// ───────── 3.3 규칙 1~11 ─────────

test("규칙 1: workflow 없음 → planned '준비 중', 직원 전원 planned", () => {
  const v = deriveAutomationView(plannedDef, fileV2, runOf(), null, now, "github");
  assert.equal(v.phase, "planned");
  assert.equal(v.state, "planned");
  assert.equal(v.sub, SUBTITLES.planned);
  assert.deepEqual(v.tasks, { a: { state: "planned", note: "준비 중" } });
});

test("규칙 2: 3분 이내 local 이 있고 run 이 없으면 requested", () => {
  const v = deriveAutomationView(def, fileV2, null, { requestId: "req-2", at: iso(-30 * 1000) }, now);
  assert.equal(v.phase, "requested");
  assert.equal(v.state, "running");
  assert.equal(v.sub, "시작 요청됨");
});

test("규칙 2: run 의 requestId 가 다르면(이전 run) requested", () => {
  const v = deriveAutomationView(def, fileV2, runOf(), { requestId: "req-2", at: iso(-MIN) }, now);
  assert.equal(v.phase, "requested");
});

test("규칙 2 → 3: local 과 같은 requestId 의 run 이 보이면 run 기준", () => {
  const run = runOf({ id: 101, status: "queued", conclusion: null, requestId: "req-2", startedAt: iso(-20 * 1000), completedAt: undefined });
  const v = deriveAutomationView(def, fileV2, run, { requestId: "req-2", at: iso(-MIN) }, now);
  assert.equal(v.phase, "queued");
  assert.equal(v.sub, "시작 준비 중");
});

test("규칙 2: local 이 3분 지나면 무시", () => {
  const v = deriveAutomationView(def, fileV2, runOf(), { requestId: "req-2", at: iso(-LOCAL_REQUEST_TTL_MS - 1000) }, now);
  assert.equal(v.phase, "done");
});

test("규칙 2: local 없음(skipped) 이면 requested 가 되지 않는다", () => {
  const v = deriveAutomationView(def, fileV2, runOf(), null, now);
  assert.notEqual(v.phase, "requested");
  assert.equal(v.phase, "done");
});

test("규칙 3: queued 90초 미만 '시작 준비 중', 90초 이상 '실행기 기다리는 중' + warn", () => {
  const fresh = runOf({ status: "queued", conclusion: null, startedAt: iso(-60 * 1000) });
  const a = deriveAutomationView(def, fileV2, fresh, null, now);
  assert.equal(a.phase, "queued");
  assert.equal(a.state, "running");
  assert.equal(a.sub, "시작 준비 중");
  assert.equal(a.warn, undefined);

  const stuck = runOf({ status: "queued", conclusion: null, startedAt: iso(-RUNNER_WAIT_MS) });
  const b = deriveAutomationView(def, fileV2, stuck, null, now);
  assert.equal(b.phase, "queued");
  assert.equal(b.sub, "실행기 기다리는 중");
  assert.equal(b.warn, "runner_waiting");
});

test("규칙 4: in_progress → running '시작한 지 N분째'", () => {
  const run = runOf({ status: "in_progress", conclusion: null, startedAt: iso(-4 * MIN), completedAt: null });
  const v = deriveAutomationView(def, fileV2, run, null, now);
  assert.equal(v.phase, "running");
  assert.equal(v.state, "running");
  assert.equal(v.sub, "시작한 지 4분째");
  assert.equal(v.runUrl, run.url);
});

test("규칙 5: 실패 run + 같은 run 파일 → file.summary 우선", () => {
  const failFile = { ...fileV2, ok: false, run_id: 200, summary: "국회 사이트에 연결할 수 없어요" };
  const run = runOf({ id: 200, conclusion: "failure" });
  const v = deriveAutomationView(def, failFile, run, null, now);
  assert.equal(v.phase, "error");
  assert.equal(v.state, "error");
  assert.equal(v.sub, "국회 사이트에 연결할 수 없어요");
});

test("규칙 5: 실패 run 인데 파일이 다른 run 것 → '실행 실패 · 자세한 기록 보기'", () => {
  for (const conclusion of ["failure", "timed_out", "startup_failure"]) {
    const v = deriveAutomationView(def, fileV2, runOf({ id: 200, conclusion }), null, now);
    assert.equal(v.phase, "error", conclusion);
    assert.equal(v.sub, "실행 실패 · 자세한 기록 보기", conclusion);
  }
});

test("규칙 6: 성공 run 인데 파일이 이전 run 것 → github 5분 안엔 finishing, 넘으면 error", () => {
  const oldFile = { ...fileV2, run_id: 99, updated_at: iso(-2 * HOUR) };
  const soon = runOf({ id: 100, startedAt: iso(-6 * MIN), completedAt: iso(-2 * MIN) });
  const a = deriveAutomationView(def, oldFile, soon, null, now, "github");
  assert.equal(a.phase, "finishing");
  assert.equal(a.state, "running");
  assert.equal(a.sub, "결과 정리 중");

  const late = runOf({ id: 100, startedAt: iso(-12 * MIN), completedAt: iso(-RESULT_WAIT_MS.github - 1000) });
  const b = deriveAutomationView(def, oldFile, late, null, now, "github");
  assert.equal(b.phase, "error");
  assert.equal(b.sub, "결과가 올라오지 않았어요 · 자세한 기록 보기");
});

test("규칙 6a: 90초 안에 끝난 성공 run(할 일 없는 예약 확인·예약 수정)은 결과 파일 없어도 오류가 아니다 → 파일 상태 유지", () => {
  const oldFile = { ...fileV2, run_id: 99, updated_at: iso(-2 * HOUR) };
  const quick = runOf({ id: 100, startedAt: iso(-30 * MIN), completedAt: iso(-30 * MIN + 11 * 1000) });
  const v = deriveAutomationView(def, oldFile, quick, null, now, "github");
  assert.equal(v.phase, "done", "이전 파일이 성공이면 그대로 끝남");
  assert.equal(v.sub, oldFile.summary);
  // 파일이 아예 없으면 규칙 8(한 번도 안 돌았음)
  assert.equal(deriveAutomationView(def, null, quick, null, now, "github").phase, "idle");
  // 90초를 넘긴 run 은 종전대로 결과를 기다린다
  const slow = runOf({ id: 100, startedAt: iso(-30 * MIN), completedAt: iso(-30 * MIN + NOOP_RUN_MS + 1000) });
  assert.equal(deriveAutomationView(def, oldFile, slow, null, now, "github").phase, "error");
});

test("규칙 6: static 소스는 T=15분", () => {
  const oldFile = { ...fileV2, run_id: 99, updated_at: iso(-2 * HOUR) };
  const run = runOf({ id: 100, startedAt: iso(-12 * MIN), completedAt: iso(-10 * MIN) });
  assert.equal(deriveAutomationView(def, oldFile, run, null, now, "github").phase, "error");
  assert.equal(deriveAutomationView(def, oldFile, run, null, now, "static").phase, "finishing");
  const veryLate = runOf({ id: 100, startedAt: iso(-20 * MIN), completedAt: iso(-RESULT_WAIT_MS.static - 1000) });
  assert.equal(deriveAutomationView(def, oldFile, veryLate, null, now, "static").phase, "error");
});

test("규칙 6: 파일 자체가 없고 run 만 성공이면 finishing", () => {
  const run = runOf({ completedAt: iso(-MIN) });
  const v = deriveAutomationView(def, null, run, null, now);
  assert.equal(v.phase, "finishing");
});

test("규칙 6 통과: run_id 없는 구버전 파일도 updated_at ≥ startedAt 이면 같은 run → done", () => {
  const legacy = { ...base, updated_at: iso(-20 * MIN) };
  const v = deriveAutomationView(def, legacy, runOf(), null, now);
  assert.equal(v.phase, "done");
  assert.equal(v.sub, legacy.summary);
});

test("규칙 7: 구버전 running:true 파일 → 3×duration 안이면 running, 넘으면 error", () => {
  const a = deriveAutomationView(manualDef, { ...base, running: true, updated_at: iso(-10 * MIN) }, null, null, now);
  assert.equal(a.phase, "running");
  assert.equal(a.sub, "실행 중");
  const b = deriveAutomationView(manualDef, { ...base, running: true, updated_at: iso(-16 * MIN) }, null, null, now);
  assert.equal(b.phase, "error");
  assert.equal(b.sub, "결과를 못 받았어요");
  const c = deriveAutomationView(manualDef, { ...base, running: true, duration_sec: 60, updated_at: iso(-4 * MIN) }, null, null, now);
  assert.equal(c.phase, "error");
});

test("규칙 8: 파일 없음 → idle '아직 실행한 적 없어요'", () => {
  const v = deriveAutomationView(def, null, null, null, now);
  assert.equal(v.phase, "idle");
  assert.equal(v.state, "idle");
  assert.equal(v.sub, "아직 실행한 적 없어요");
  assert.equal(v.lastRunAt, undefined);
});

test("규칙 9: !file.ok → error, file.summary", () => {
  const v = deriveAutomationView(def, { ...fileV2, ok: false, summary: "토큰이 없어요" }, null, null, now);
  assert.equal(v.phase, "error");
  assert.equal(v.sub, "토큰이 없어요");
});

test("규칙 10a: schedule 있고 36시간 넘음 → idle + schedule_missed", () => {
  const stale = { ...fileV2, updated_at: iso(-(STALE_HOURS + 1) * HOUR) };
  const v = deriveAutomationView(def, stale, null, null, now);
  assert.equal(v.phase, "idle");
  assert.equal(v.state, "idle");
  assert.equal(v.warn, "schedule_missed");
  assert.equal(v.sub, "예약 실행이 안 되고 있어요 · 마지막 실행 37시간 전");
});

test("규칙 10b: schedule 없고 36시간 넘음 → idle '마지막 실행 N시간 전', warn 없음", () => {
  const stale = { ...fileV2, updated_at: iso(-40 * HOUR) };
  const v = deriveAutomationView(manualDef, stale, null, null, now);
  assert.equal(v.phase, "idle");
  assert.equal(v.warn, undefined);
  assert.equal(v.sub, "마지막 실행 40시간 전");
});

test("규칙 10: 36시간 안이면 stale 아님", () => {
  const recent = { ...fileV2, updated_at: iso(-(STALE_HOURS - 1) * HOUR) };
  assert.equal(deriveAutomationView(def, recent, null, null, now).phase, "done");
});

test("규칙 11: 그 외 → done, file.summary, 부가 필드 전달", () => {
  const v = deriveAutomationView(def, fileV2, runOf(), null, now);
  assert.equal(v.phase, "done");
  assert.equal(v.state, "done");
  assert.equal(v.sub, fileV2.summary);
  assert.equal(v.lastRunAt, fileV2.updated_at);
  assert.equal(v.nextRun, "매일 09:00");
  assert.equal(v.runUrl, fileV2.run_url);
  assert.deepEqual(v.counts, fileV2.counts);
  assert.equal(v.id, "minutes");
  assert.equal(v.dept, "research");
  assert.equal(v.name, "국회회의록 수집");
});

test("실행기 며칠 꺼짐 흐름: cancelled 제외 뒤 이전 성공 run + 오래된 파일 → 규칙 10a", () => {
  const oldRun = runOf({ id: 100, startedAt: iso(-50 * HOUR), completedAt: iso(-49.9 * HOUR) });
  const oldFile = { ...fileV2, run_id: 100, updated_at: iso(-49.9 * HOUR) };
  const v = deriveAutomationView(def, oldFile, oldRun, null, now);
  assert.equal(v.phase, "idle");
  assert.equal(v.warn, "schedule_missed");
});

test("runs 없는 정적 폴백: 규칙 7~11 만으로 판정", () => {
  assert.equal(deriveAutomationView(def, null, null, null, now, "static").phase, "idle");
  assert.equal(deriveAutomationView(def, { ...fileV2, ok: false }, null, null, now, "static").phase, "error");
  assert.equal(deriveAutomationView(def, { ...fileV2, updated_at: iso(-48 * HOUR) }, null, null, now, "static").phase, "idle");
  assert.equal(deriveAutomationView(def, fileV2, null, null, now, "static").phase, "done");
  assert.equal(deriveAutomationView(def, { ...base, running: true, updated_at: iso(-MIN) }, null, null, now, "static").phase, "running");
});

// ───────── 3.4 직원 판정 ─────────

test("deriveTaskStates: 실행 중이면 planned 제외 전원 running", () => {
  for (const status of ["queued", "in_progress"]) {
    const run = runOf({ status, conclusion: null, startedAt: iso(-MIN), completedAt: null });
    const v = deriveAutomationView(def, fileV2, run, null, now);
    assert.equal(v.tasks.collect.state, "running", status);
    assert.equal(v.tasks.replace.state, "running", status);
    assert.equal(v.tasks.summary.state, "planned", status);
    assert.equal(v.tasks.collect.note, v.sub);
  }
  const requested = deriveAutomationView(def, fileV2, null, { requestId: "r", at: iso(-MIN) }, now);
  assert.equal(requested.tasks.collect.state, "running");
});

test("deriveTaskStates: done 뒤 파일 tasks 반영, 파일에 없는 직원은 자동화 상태 상속, planned 는 항상 planned", () => {
  const withExtra = { ...def, tasks: [...def.tasks, { id: "notify", name: "알림", role: "" }] };
  const v = deriveAutomationView(withExtra, fileV2, runOf(), null, now);
  assert.equal(v.phase, "done");
  assert.deepEqual(v.tasks.collect, { state: "done", note: "신규 3건" });
  assert.deepEqual(v.tasks.replace, { state: "idle", note: "교체 0건" });
  assert.deepEqual(v.tasks.notify, { state: "done", note: fileV2.summary });
  assert.deepEqual(v.tasks.summary, { state: "planned", note: "준비 중" });
});

test("deriveTaskStates: 파일이 실패(ok:false)면 tasks 의 error 반영", () => {
  const failFile = { ...fileV2, ok: false, summary: "연결 실패", tasks: [
    { id: "collect", status: "error", summary: "국회 사이트 응답 없음" },
    { id: "replace", status: "idle", summary: "" },
  ] };
  const v = deriveAutomationView(def, failFile, null, null, now);
  assert.equal(v.phase, "error");
  assert.deepEqual(v.tasks.collect, { state: "error", note: "국회 사이트 응답 없음" });
  assert.equal(v.tasks.replace.state, "idle");
});

test("deriveTaskStates: 실패 run 인데 파일이 이전 성공 것이면 옛 결과를 쓰지 않고 error 상속", () => {
  const v = deriveAutomationView(def, fileV2, runOf({ id: 200, conclusion: "failure" }), null, now);
  assert.equal(v.phase, "error");
  assert.equal(v.tasks.collect.state, "error");
  assert.equal(v.tasks.replace.state, "error");
});

test("deriveTaskStates: 36시간 stale 이면 전원 idle", () => {
  const v = deriveAutomationView(def, { ...fileV2, updated_at: iso(-48 * HOUR) }, null, null, now);
  assert.equal(v.tasks.collect.state, "idle");
  assert.equal(v.tasks.replace.state, "idle");
  assert.equal(v.tasks.summary.state, "planned");
});

test("deriveTaskStates: 직접 호출도 같은 결과", () => {
  const view = { id: "minutes", dept: "research", name: "n", phase: "done", state: "done", sub: "s", tasks: {} };
  const t = deriveTaskStates(def, view, fileV2);
  assert.equal(t.collect.state, "done");
  assert.equal(t.replace.state, "idle");
  assert.equal(t.summary.state, "planned");
});

// ───────── 3.5 부서·집계 ─────────

const mkView = (id, state, extra = {}) => ({ id, dept: "research", name: id, phase: state, state, sub: "", tasks: {}, ...extra });

test("deriveDeptView: 최악값 error > running > done > idle", () => {
  const defs = [{ ...def, id: "a" }, { ...def, id: "b" }, { ...def, id: "c" }];
  assert.equal(deriveDeptView(defs, [mkView("a", "idle"), mkView("b", "done"), mkView("c", "idle")]).state, "done");
  assert.equal(deriveDeptView(defs, [mkView("a", "done"), mkView("b", "running"), mkView("c", "idle")]).state, "running");
  const d = deriveDeptView(defs, [mkView("a", "running"), mkView("b", "error"), mkView("c", "running")]);
  assert.equal(d.state, "error");
  assert.equal(d.runningCount, 2);
  assert.deepEqual(d.automationIds, ["a", "b", "c"]);
  assert.equal(deriveDeptView(defs, [mkView("a", "idle"), mkView("b", "idle"), mkView("c", "idle")]).state, "idle");
});

test("deriveDeptView: workflow 있는 자동화가 0개면 none, planned 자동화는 제외", () => {
  assert.deepEqual(deriveDeptView([], []), { state: "none", runningCount: 0, automationIds: [] });
  assert.equal(deriveDeptView([plannedDef], [mkView("future", "planned")]).state, "none");
  const d = deriveDeptView([plannedDef, { ...def, id: "x" }], [mkView("future", "planned"), mkView("x", "done")]);
  assert.equal(d.state, "done");
  assert.deepEqual(d.automationIds, ["x"]);
});

test("summarizeTasks: planned 아닌 직원 수 + '자동화 N개 중 M개 실행 중'", () => {
  const running = deriveAutomationView(def, fileV2, runOf({ status: "in_progress", conclusion: null, startedAt: iso(-MIN) }), null, now);
  const done = deriveAutomationView({ ...def, id: "b" }, fileV2, runOf(), null, now);
  const planned = deriveAutomationView(plannedDef, null, null, null, now);
  const s = summarizeTasks([running, done, planned], [def, { ...def, id: "b" }, plannedDef]);
  assert.deepEqual(s.counts, { idle: 1, running: 2, done: 1, error: 0 });
  assert.equal(s.automations, 2);
  assert.equal(s.running, 1);
  assert.equal(s.brief, "자동화 2개 중 1개 실행 중");
});

test("collectWarnings: 사유별 배너 1줄, 예약 밀림은 가장 오래된 마지막 실행 기준", () => {
  assert.deepEqual(collectWarnings([mkView("a", "done")], now), []);
  const views = [
    mkView("a", "running", { warn: "runner_waiting" }),
    mkView("b", "running", { warn: "runner_waiting" }),
    mkView("c", "idle", { warn: "schedule_missed", lastRunAt: iso(-40 * HOUR) }),
    mkView("d", "idle", { warn: "schedule_missed", lastRunAt: iso(-3 * 24 * HOUR) }),
  ];
  const banners = collectWarnings(views, now);
  assert.equal(banners.length, 2);
  assert.deepEqual(banners[0], { kind: "runner_waiting", level: "warn", text: BANNERS.runnerWaiting, ids: ["a", "b"] });
  assert.equal(banners[0].text, "실행기가 꺼져 있는 것 같아요 · 켜지면 자동으로 시작돼요");
  assert.deepEqual(banners[1].ids, ["c", "d"]);
  assert.equal(banners[1].text, "예약 실행이 밀리고 있어요 (마지막 실행 3일 전) · 실행기가 켜져 있는지 확인해 주세요");
});

test("문구 상수: 배너·부제 확정 문구", () => {
  assert.equal(BANNERS.failed("국회회의록 수집"), "국회회의록 수집이(가) 실패했어요 · 자세한 기록 보기");
  assert.equal(BANNERS.tokenExpiring(7), "실행 연결이 7일 뒤 끊겨요 · 설정 안내 보기");
  assert.equal(BANNERS.staleSource(3), "최신 상태를 못 가져왔어요 (3분 전 기준)");
  assert.equal(SUBTITLES.logLink, "자세한 기록 보기");
});

test("historyLabel: queued/in_progress/success/failure/cancelled", () => {
  assert.deepEqual(historyLabel("queued", null), { text: "시작 준비 중", cls: "working" });
  assert.equal(historyLabel("in_progress", null).text, "일하는 중");
  assert.deepEqual(historyLabel("completed", "success"), { text: "끝남", cls: "done" });
  assert.deepEqual(historyLabel("completed", "failure"), { text: "오류", cls: "error" });
  assert.deepEqual(historyLabel("completed", "cancelled"), { text: "취소됨", cls: "planned" });
});

test("durationText: 초·분 표기, 값이 없으면 빈 문자열", () => {
  assert.equal(durationText("2026-09-11T00:00:00Z", "2026-09-11T00:00:45Z"), "45초");
  assert.equal(durationText("2026-09-11T00:00:00Z", "2026-09-11T00:04:48Z"), "4.8분");
  assert.equal(durationText("2026-09-11T00:00:00Z", null), "");
  assert.equal(durationText(null, null), "");
});
