import { test } from "node:test";
import assert from "node:assert/strict";
import {
  decideRun, parseRequestId, latestValidRunByWorkflow, kstDateKey, dailyCount, addDailyCount,
  createRunApiStores, handleRun, handleStatus, isCrossOrigin, handleHistory, isValidDate, kstDayRangeUtc, historyFromRuns, parseArchive, archiveDate, mergeHistory,
  handleReview, parseRunInputs,
} from "../worker/run-api.ts";
import { GitHubClient, GitHubAuthError, GitHubUnavailableError, GitHubNotFoundError } from "../worker/github.ts";
import { DAILY_RUN_LIMIT, STATUS_CACHE_MS, TOO_SOON_MS, HISTORY_START, HISTORY_TODAY_CACHE_MS, HISTORY_PAST_CACHE_MS } from "../worker/config.ts";

// ── 공통 가짜 객체 ──
const ORIGIN = "https://ai-office.example.workers.dev";
const NOW = Date.parse("2026-09-11T00:00:00Z"); // KST 09:00

const workspaces = {
  assembly: {
    id: "assembly",
    automations: [
      { id: "minutes", workflow: "minutes.yml", inputs: { mode: "full" }, tasks: [] },
      { id: "news", tasks: [] }, // workflow 없음 → 준비 중
      { id: "mail", workflow: "mail.yml", tasks: [] },
    ],
  },
  home: { id: "home", automations: [] },
};

function run(over = {}) {
  const id = over.id ?? 100;
  return {
    id, path: ".github/workflows/minutes.yml", status: "completed", conclusion: "success",
    display_title: "수집 · req-20260911090001-a1b2", event: "workflow_dispatch", run_started_at: "2026-09-11T00:01:00Z",
    updated_at: "2026-09-11T00:03:00Z", html_url: `https://github.com/Junjaee/ai-office/actions/runs/${id}`, ...over,
  };
}

/** 가짜 GitHub 클라이언트 — 호출 기록을 남긴다 */
function fakeGithub({ runs = [], files = {}, dispatchError = null, runsError = null, fileError = null, tokenExpiresAt = "2027-09-01T00:00:00.000Z", ranged = [], texts = {}, rangedError = null, textError = null } = {}) {
  const calls = { dispatch: [], listRuns: 0, readStatusFile: [], listRunsBetween: [], readRepoText: [] };
  return {
    calls,
    tokenExpiresAt,
    async dispatch(file, inputs) {
      calls.dispatch.push({ file, inputs });
      if (dispatchError) throw dispatchError;
    },
    async listRuns() {
      calls.listRuns += 1;
      if (runsError) throw runsError;
      return runs;
    },
    async readStatusFile(ws, id) {
      calls.readStatusFile.push(`${ws}/${id}`);
      if (fileError) throw fileError;
      return files[id] ?? null;
    },
    async listRunsBetween(from, to) {
      calls.listRunsBetween.push([from, to]);
      if (rangedError) throw rangedError;
      return ranged;
    },
    async readRepoText(path) {
      calls.readRepoText.push(path);
      if (textError) throw textError;
      return texts[path] ?? null;
    },
  };
}

function fakeEnv(staticFiles = {}) {
  return {
    GITHUB_TOKEN: "x",
    ASSETS: {
      async fetch(request) {
        const path = new URL(request.url).pathname;
        const body = staticFiles[path];
        return body ? Response.json(body) : new Response("not found", { status: 404 });
      },
    },
  };
}

function makeDeps(over = {}) {
  return { ...createRunApiStores(), now: () => NOW, workspaces, github: fakeGithub(), ...over };
}

function runRequest(body, { headers = {}, method = "POST", raw } = {}) {
  const init = { method, headers: { "Content-Type": "application/json", ...headers } };
  if (method !== "GET") init.body = raw ?? JSON.stringify(body);
  return new Request(`${ORIGIN}/api/run`, init);
}

const validBody = { ws: "assembly", automation: "minutes", requestId: "req-20260911090001-a1b2" };

async function call(body, deps = makeDeps(), opts = {}) {
  const res = await handleRun(runRequest(body, opts), fakeEnv(), deps);
  return { status: res.status, json: await res.json(), deps };
}

// ── decideRun ──
test("decideRun: 최신 run 이 queued/in_progress 면 already_running", () => {
  assert.deepEqual(decideRun({ status: "queued", conclusion: null }, undefined, NOW), { kind: "skipped", reason: "already_running" });
  assert.deepEqual(decideRun({ status: "in_progress", conclusion: null }, NOW - 999_999, NOW), { kind: "skipped", reason: "already_running" });
});

test("decideRun: 60초 안에 dispatch 했으면 too_soon", () => {
  assert.deepEqual(decideRun({ status: "completed", conclusion: "success" }, NOW - TOO_SOON_MS + 1, NOW), { kind: "skipped", reason: "too_soon" });
  assert.deepEqual(decideRun(null, NOW - 1000, NOW), { kind: "skipped", reason: "too_soon" });
});

test("decideRun: 그 외는 accepted", () => {
  assert.deepEqual(decideRun(null, undefined, NOW), { kind: "accepted" });
  assert.deepEqual(decideRun({ status: "completed", conclusion: "failure" }, NOW - TOO_SOON_MS, NOW), { kind: "accepted" });
});

// ── 보조 함수 ──
test("parseRequestId: display_title 에서 req-… 만 추출", () => {
  assert.equal(parseRequestId("수집 · req-20260911090001-a1b2"), "req-20260911090001-a1b2");
  assert.equal(parseRequestId("수집 · 예약"), null);
  assert.equal(parseRequestId(null), null);
});

test("latestValidRunByWorkflow: cancelled/skipped 제외, 파일명 기준 최신 1건", () => {
  const map = latestValidRunByWorkflow([
    run({ id: 300, conclusion: "cancelled", status: "completed" }),
    run({ id: 200, status: "in_progress", conclusion: null }),
    run({ id: 100 }),
    run({ id: 150, path: ".github/workflows/mail.yml", conclusion: "skipped" }),
    run({ id: 120, path: ".github/workflows/mail.yml" }),
  ]);
  assert.equal(map.get("minutes.yml").id, 200);
  assert.equal(map.get("mail.yml").id, 120);
});

test("kstDateKey: UTC 15:00 은 KST 다음날", () => {
  assert.equal(kstDateKey(Date.parse("2026-09-10T14:59:59Z")), "2026-09-10");
  assert.equal(kstDateKey(Date.parse("2026-09-10T15:00:00Z")), "2026-09-11");
});

test("dailyCount: 사무실별로 세고 KST 날짜가 바뀌면 초기화", () => {
  const store = createRunApiStores().dailyCounter;
  addDailyCount(store, "assembly", NOW, 3);
  addDailyCount(store, "home", NOW, 1);
  assert.equal(dailyCount(store, "assembly", NOW), 3);
  assert.equal(dailyCount(store, "home", NOW), 1);
  assert.equal(dailyCount(store, "assembly", NOW + 24 * 3600 * 1000), 0);
  assert.equal(dailyCount(store, "home", NOW + 24 * 3600 * 1000), 0);
});

test("isCrossOrigin: Origin 호스트 다름 · Sec-Fetch-Site cross-site 만 true", () => {
  const req = (h) => new Request(`${ORIGIN}/api/run`, { method: "POST", headers: h });
  assert.equal(isCrossOrigin(req({})), false);
  assert.equal(isCrossOrigin(req({ Origin: ORIGIN })), false);
  assert.equal(isCrossOrigin(req({ Origin: "https://evil.example" })), true);
  assert.equal(isCrossOrigin(req({ "Sec-Fetch-Site": "same-origin" })), false);
  assert.equal(isCrossOrigin(req({ "Sec-Fetch-Site": "cross-site" })), true);
});

// ── handleRun: 요청 검증 ──
test("handleRun: POST 아니면 405", async () => {
  const { status } = await call(validBody, makeDeps(), { method: "GET" });
  assert.equal(status, 405);
});

test("handleRun: JSON 아니면 400", async () => {
  assert.equal((await call(null, makeDeps(), { raw: "not json" })).status, 400);
  assert.equal((await call(validBody, makeDeps(), { headers: { "Content-Type": "text/plain" } })).status, 400);
});

test("handleRun: 본문 2KB 초과면 400", async () => {
  const big = { ...validBody, pad: "x".repeat(2200) };
  assert.equal((await call(big)).status, 400);
});

test("handleRun: ws/automation/requestId 누락·형식 오류면 400", async () => {
  assert.equal((await call({ automation: "minutes", requestId: "req-1" })).status, 400);
  assert.equal((await call({ ws: "assembly", requestId: "req-1" })).status, 400);
  assert.equal((await call({ ws: "assembly", automation: "minutes" })).status, 400);
  assert.equal((await call({ ...validBody, requestId: "bad id" })).status, 400);
});

test("handleRun: Origin 호스트가 다르면 403, Sec-Fetch-Site cross-site 면 403", async () => {
  assert.equal((await call(validBody, makeDeps(), { headers: { Origin: "https://evil.example" } })).status, 403);
  assert.equal((await call(validBody, makeDeps(), { headers: { "Sec-Fetch-Site": "cross-site" } })).status, 403);
  assert.equal((await call(validBody, makeDeps(), { headers: { Origin: ORIGIN, "Sec-Fetch-Site": "same-origin" } })).status, 200);
});

test("handleRun: 사무실 없음·자동화 없음·workflow 없음이면 404", async () => {
  assert.equal((await call({ ...validBody, ws: "nope" })).status, 404);
  assert.equal((await call({ ...validBody, automation: "nope" })).status, 404);
  assert.equal((await call({ ...validBody, automation: "news" })).status, 404);
  assert.equal((await call({ ...validBody, ws: "home", automation: "all" })).status, 404);
});

// ── handleRun: 결과 ──
test("handleRun: dispatch 204 → 200 accepted, inputs 는 설정값 + request_id", async () => {
  const { status, json, deps } = await call(validBody);
  assert.equal(status, 200);
  assert.deepEqual(json, { results: [{ id: "minutes", accepted: true, requestedAt: new Date(NOW).toISOString() }] });
  assert.deepEqual(deps.github.calls.dispatch, [{ file: "minutes.yml", inputs: { mode: "full", request_id: validBody.requestId } }]);
  assert.equal(deps.dispatchLog.get("assembly/minutes"), NOW);
  assert.equal(dailyCount(deps.dailyCounter, "assembly", NOW), 1);
});

test("handleRun: 최신 run 이 in_progress 면 skipped already_running (dispatch 없음)", async () => {
  const deps = makeDeps({ github: fakeGithub({ runs: [run({ status: "in_progress", conclusion: null })] }) });
  const { status, json } = await call(validBody, deps);
  assert.equal(status, 200);
  assert.deepEqual(json, { results: [{ id: "minutes", skipped: "already_running" }] });
  assert.equal(deps.github.calls.dispatch.length, 0);
});

test("handleRun: cancelled 된 최신 run 은 무시하고 accepted", async () => {
  const deps = makeDeps({ github: fakeGithub({ runs: [run({ id: 200, status: "in_progress", conclusion: "cancelled" }), run({ id: 100 })] }) });
  const { json } = await call(validBody, deps);
  assert.equal(json.results[0].accepted, true);
});

test("handleRun: 60초 안 재요청이면 skipped too_soon", async () => {
  const deps = makeDeps();
  await call(validBody, deps);
  const second = await call({ ...validBody, requestId: "req-2" }, deps);
  assert.deepEqual(second.json, { results: [{ id: "minutes", skipped: "too_soon" }] });
  assert.equal(deps.github.calls.dispatch.length, 1);
  deps.now = () => NOW + TOO_SOON_MS;
  const third = await call({ ...validBody, requestId: "req-3" }, deps);
  assert.equal(third.json.results[0].accepted, true);
});

test("handleRun: all 이면 workflow 있는 자동화 전부를 설정 순서대로, 같은 requestId 전파", async () => {
  const deps = makeDeps({ github: fakeGithub({ runs: [run({ path: ".github/workflows/mail.yml", status: "queued", conclusion: null })] }) });
  const { status, json } = await call({ ...validBody, automation: "all" }, deps);
  assert.equal(status, 200);
  assert.deepEqual(json.results, [
    { id: "minutes", accepted: true, requestedAt: new Date(NOW).toISOString() },
    { id: "mail", skipped: "already_running" },
  ]);
  assert.deepEqual(deps.github.calls.dispatch.map((d) => [d.file, d.inputs.request_id]), [["minutes.yml", validBody.requestId]]);
  assert.equal(deps.github.calls.listRuns, 1, "runs 는 한 번만 조회");
});

test("handleRun: GitHub 401/403 → 502 github_auth", async () => {
  const a = await call(validBody, makeDeps({ github: fakeGithub({ dispatchError: new GitHubAuthError(401) }) }));
  assert.equal(a.status, 502);
  assert.deepEqual(a.json, { error: "github_auth" });
  const b = await call(validBody, makeDeps({ github: fakeGithub({ runsError: new GitHubAuthError(403) }) }));
  assert.equal(b.status, 502);
  assert.deepEqual(b.json, { error: "github_auth" });
});

test("handleRun: GitHub 5xx/네트워크 → 502 github_unavailable", async () => {
  const a = await call(validBody, makeDeps({ github: fakeGithub({ dispatchError: new GitHubUnavailableError(503) }) }));
  assert.equal(a.status, 502);
  assert.deepEqual(a.json, { error: "github_unavailable" });
  const b = await call(validBody, makeDeps({ github: fakeGithub({ runsError: new GitHubUnavailableError(null) }) }));
  assert.deepEqual(b.json, { error: "github_unavailable" });
});

test("handleRun: 토큰 없음(github null) → 502 github_auth", async () => {
  const { status, json } = await call(validBody, makeDeps({ github: null }));
  assert.equal(status, 502);
  assert.deepEqual(json, { error: "github_auth" });
});

test("handleRun: 하루 상한 — 50회 초과 429, skipped 는 세지 않음, 날짜 바뀌면 초기화", async () => {
  const deps = makeDeps();
  let t = NOW;
  for (let i = 0; i < DAILY_RUN_LIMIT; i++) {
    t += TOO_SOON_MS;
    deps.now = () => t;
    const r = await call({ ...validBody, requestId: `req-${i}` }, deps);
    assert.equal(r.status, 200, `${i}번째`);
    assert.equal(r.json.results[0].accepted, true);
  }
  assert.equal(dailyCount(deps.dailyCounter, "assembly", t), DAILY_RUN_LIMIT);

  // 51번째 accepted 후보 → 429, dispatch 없음
  t += TOO_SOON_MS;
  deps.now = () => t;
  const over = await call({ ...validBody, requestId: "req-over" }, deps);
  assert.equal(over.status, 429);
  assert.deepEqual(over.json, { error: "daily_limit" });
  assert.equal(deps.github.calls.dispatch.length, DAILY_RUN_LIMIT);

  // skipped 는 세지 않음: 상한에서도 200 skipped (방금 dispatch 한 것으로 표시 → too_soon)
  deps.dispatchLog.set("assembly/minutes", t);
  const soon = await call({ ...validBody, requestId: "req-soon" }, deps);
  assert.equal(soon.status, 200);
  assert.deepEqual(soon.json.results, [{ id: "minutes", skipped: "too_soon" }]);
  assert.equal(dailyCount(deps.dailyCounter, "assembly", t), DAILY_RUN_LIMIT);

  // 다른 사무실은 별도 카운터 (home 은 workflow 없어 404 — 카운터만 확인)
  assert.equal(dailyCount(deps.dailyCounter, "home", t), 0);

  // KST 자정이 지나면 초기화
  const nextDay = Date.parse("2026-09-11T15:00:01Z"); // KST 2026-09-12 00:00:01
  deps.now = () => nextDay;
  const fresh = await call({ ...validBody, requestId: "req-fresh" }, deps);
  assert.equal(fresh.status, 200);
  assert.equal(fresh.json.results[0].accepted, true);
  assert.equal(dailyCount(deps.dailyCounter, "assembly", nextDay), 1);
});

test("handleRun: all 로 상한을 넘기면 하나도 dispatch 하지 않고 429", async () => {
  const deps = makeDeps();
  addDailyCount(deps.dailyCounter, "assembly", NOW, DAILY_RUN_LIMIT - 1);
  const { status } = await call({ ...validBody, automation: "all" }, deps); // accepted 후보 2 → 49 + 2 > 50
  assert.equal(status, 429);
  assert.equal(deps.github.calls.dispatch.length, 0);
});

// ── handleStatus ──
function statusRequest(ws = "assembly", method = "GET") {
  return new Request(`${ORIGIN}/api/status?ws=${ws}`, { method });
}

test("handleStatus: GET 아니면 405, 사무실 없으면 404", async () => {
  assert.equal((await handleStatus(statusRequest("assembly", "POST"), fakeEnv(), makeDeps())).status, 405);
  assert.equal((await handleStatus(statusRequest("nope"), fakeEnv(), makeDeps())).status, 404);
});

test("handleStatus: runs 를 자동화별로 매핑, cancelled 제외, requestId 파싱, files 는 Contents API", async () => {
  const github = fakeGithub({
    runs: [
      run({ id: 300, status: "completed", conclusion: "cancelled", display_title: "수집 · req-cancelled" }),
      run({ id: 200, status: "in_progress", conclusion: null, display_title: "수집 · req-20260911090001-a1b2", updated_at: "2026-09-11T00:02:00Z" }),
      run({ id: 100 }),
      run({ id: 50, path: ".github/workflows/other.yml" }),
    ],
    files: { minutes: { id: "minutes", ok: true } },
  });
  const deps = makeDeps({ github });
  const res = await handleStatus(statusRequest(), fakeEnv(), deps);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.checkedAt, new Date(NOW).toISOString());
  assert.deepEqual(body.config, { canRun: true, tokenExpiresAt: "2027-09-01T00:00:00.000Z", githubError: null });
  assert.equal(body.source, "github");
  assert.deepEqual(body.runs, {
    minutes: {
      id: 200, status: "in_progress", conclusion: null, requestId: "req-20260911090001-a1b2",
      startedAt: "2026-09-11T00:01:00Z", completedAt: null, url: "https://github.com/Junjaee/ai-office/actions/runs/200",
    },
    mail: null,
  });
  assert.deepEqual(body.files, { minutes: { id: "minutes", ok: true }, mail: null });
  assert.equal(github.calls.listRuns, 1);
  assert.deepEqual(github.calls.readStatusFile, ["assembly/minutes", "assembly/mail"]);
  assert.equal("news" in body.runs, false, "workflow 없는 자동화는 포함하지 않음");
});

test("handleStatus: 완료된 run 은 completedAt = updated_at", async () => {
  const deps = makeDeps({ github: fakeGithub({ runs: [run()] }) });
  const body = await (await handleStatus(statusRequest(), fakeEnv(), deps)).json();
  assert.equal(body.runs.minutes.completedAt, "2026-09-11T00:03:00Z");
  assert.equal(body.runs.minutes.conclusion, "success");
});

test("handleStatus: Contents API 실패 시 정적 파일 폴백 + source static", async () => {
  const github = fakeGithub({ runs: [run()], fileError: new GitHubAuthError(401) });
  const env = fakeEnv({ "/status/assembly/minutes.json": { id: "minutes", from: "static" } });
  const body = await (await handleStatus(statusRequest(), env, makeDeps({ github }))).json();
  assert.equal(body.source, "static");
  assert.deepEqual(body.files, { minutes: { id: "minutes", from: "static" }, mail: null });
  assert.equal(body.runs.minutes.id, 100, "runs 는 여전히 GitHub 값");
  assert.equal(body.config.canRun, true);
});

test("handleStatus: runs API 실패 시 runs 빈 객체 + source static", async () => {
  const github = fakeGithub({ runsError: new GitHubUnavailableError(500), files: { minutes: { id: "minutes" } } });
  const body = await (await handleStatus(statusRequest(), fakeEnv(), makeDeps({ github }))).json();
  assert.equal(body.source, "static");
  assert.deepEqual(body.runs, {});
  assert.deepEqual(body.files.minutes, { id: "minutes" });
});

test("handleStatus: 토큰이 저장소를 못 보면(404) canRun false · githubError not_found · 정적 파일 폴백", async () => {
  const github = fakeGithub({ runsError: new GitHubNotFoundError(), files: {} });
  const env = fakeEnv({ "/status/assembly/minutes.json": { id: "minutes", from: "static" } });
  const body = await (await handleStatus(statusRequest(), env, makeDeps({ github }))).json();
  assert.equal(body.config.canRun, false);
  assert.equal(body.config.githubError, "not_found");
  assert.equal(body.source, "static");
  assert.deepEqual(body.files.minutes, { id: "minutes", from: "static" }, "Contents 404 여도 정적 파일을 쓴다");
});

test("handleStatus: 인증 실패(401)면 canRun false · githubError auth", async () => {
  const github = fakeGithub({ runsError: new GitHubAuthError(401), fileError: new GitHubAuthError(401) });
  const env = fakeEnv({ "/status/assembly/minutes.json": { id: "minutes" } });
  const body = await (await handleStatus(statusRequest(), env, makeDeps({ github }))).json();
  assert.equal(body.config.canRun, false);
  assert.equal(body.config.githubError, "auth");
});

test("handleStatus: 5xx 는 canRun 유지 · githubError unavailable", async () => {
  const github = fakeGithub({ runsError: new GitHubUnavailableError(500), files: { minutes: { id: "minutes" } } });
  const body = await (await handleStatus(statusRequest(), fakeEnv(), makeDeps({ github }))).json();
  assert.equal(body.config.canRun, true);
  assert.equal(body.config.githubError, "unavailable");
});

// ── 실행 이력 (날짜별) ──
test("isValidDate · kstDayRangeUtc: KST 하루 → UTC 범위", () => {
  assert.equal(isValidDate("2026-09-10"), true);
  assert.equal(isValidDate("2026-02-30"), false);
  assert.equal(isValidDate("2026-9-10"), false);
  assert.deepEqual(kstDayRangeUtc("2026-09-10"), { from: "2026-09-09T15:00:00Z", to: "2026-09-10T14:59:59Z" });
});

test("historyFromRuns: 이 사무실 자동화 run 만, 방식 분류, 요약 없음", () => {
  const h = historyFromRuns([
    run({ id: 1, event: "schedule" }),
    run({ id: 2, path: ".github/workflows/other.yml" }),
    run({ id: 3, path: ".github/workflows/mail.yml", event: "push", status: "in_progress", conclusion: null }),
  ], workspaces.assembly.automations);
  assert.deepEqual(h.map((x) => [x.id, x.automationId, x.trigger]), [["1", "minutes", "schedule"], ["3", "mail", "other"]]);
  assert.equal(h[0].summary, null);
  assert.equal(h[1].completedAt, null);
});

test("parseArchive · archiveDate: 깨진 줄은 건너뛰고, 날짜는 KST", () => {
  const text = [
    JSON.stringify({ run_id: 1, automation: "minutes", started_at: "2026-09-10T23:59:00+09:00", ok: true, summary: "어제" }),
    "{깨진 줄",
    JSON.stringify({ run_id: 2, started_at: "2026-09-10T15:30:00Z", ok: true, summary: "오늘 00:30" }),
    JSON.stringify({ automation: "minutes", recorded_at: "2026-09-11T08:00:00+09:00", trigger: "local", ok: false, summary: "이 PC" }),
    "",
  ].join("\n");
  const lines = parseArchive(text, "minutes");
  assert.deepEqual(lines.map((l) => l.summary), ["어제", "오늘 00:30", "이 PC"]);
  assert.equal(lines[1].automation, "minutes");
  assert.deepEqual(lines.map(archiveDate), ["2026-09-10", "2026-09-11", "2026-09-11"]);
});

test("mergeHistory: GitHub 상태 + 일지 요약, 일지에만 있는 실행, 최신순", () => {
  const gh = historyFromRuns([
    run({ id: 10, run_started_at: "2026-09-11T00:10:00Z" }),
    run({ id: 11, conclusion: "cancelled", run_started_at: "2026-09-11T01:00:00Z" }),
  ], workspaces.assembly.automations);
  const archive = [
    { run_id: 10, automation: "minutes", started_at: "2026-09-11T09:10:05+09:00", ok: true, summary: "신규 3건" },
    { run_id: 9, automation: "minutes", trigger: "schedule", started_at: "2026-09-11T08:00:00+09:00", duration_sec: 90, ok: false, summary: "실패", url: "u9" },
    { automation: "minutes", trigger: "local", started_at: "2026-09-11T11:00:00+09:00", ok: true, summary: "이 PC" },
  ];
  const m = mergeHistory(gh, archive, "2026-09-11", false);
  assert.deepEqual(m.map((x) => x.id), ["local:minutes:2026-09-11T11:00:00+09:00", "11", "10", "9"]);
  assert.equal(m[2].summary, "신규 3건");
  assert.equal(m[2].url, "https://github.com/Junjaee/ai-office/actions/runs/10");
  assert.equal(m[1].summary, null);
  assert.deepEqual([m[3].status, m[3].conclusion, m[3].trigger, m[3].completedAt], ["completed", "failure", "schedule", "2026-09-10T23:01:30.000Z"]);
  assert.equal(m[0].url, null);
  assert.equal(m[3].durationSec, 90);
  // GitHub 이 믿을 만하면(성공·90일 안) 그날 목록에 없는 실행 번호는 다른 날(만든 날) 것이다
  assert.deepEqual(mergeHistory(gh, archive, "2026-09-11", true).map((x) => x.id), ["local:minutes:2026-09-11T11:00:00+09:00", "11", "10"]);
});

test("mergeHistory: 밤새 대기한 실행 — 요청한 날(GitHub)에 요약·걸린 시간을 붙이고 다음 날에는 안 보인다", () => {
  const lines = [{ run_id: 50, automation: "minutes", trigger: "manual", started_at: "2026-09-11T08:56:49+09:00", duration_sec: 325, ok: true, summary: "신규 5건" }];
  const created = historyFromRuns([run({ id: 50, run_started_at: "2026-09-10T09:44:58Z", updated_at: "2026-09-11T00:02:56Z" })], workspaces.assembly.automations);
  assert.deepEqual(mergeHistory(created, lines, "2026-09-10", true).map((x) => [x.id, x.summary, x.durationSec]), [["50", "신규 5건", 325]]);
  assert.deepEqual(mergeHistory([], lines, "2026-09-11", true), []);
  assert.equal(mergeHistory([], lines, "2026-09-11", false).length, 1); // GitHub 실패·보관 기간 밖이면 일지대로
});

function historyRequest(query) {
  return new Request(ORIGIN + "/api/history?" + query, { method: "GET" });
}

test("handleHistory: 날짜 검증 · 모르는 사무실", async () => {
  const deps = makeDeps();
  assert.equal((await handleHistory(historyRequest("ws=assembly&date=2026-9-1"), deps)).status, 400);
  assert.equal((await handleHistory(historyRequest("ws=assembly&date=2026-09-12"), deps)).status, 400); // KST 오늘 9/11 → 미래
  assert.equal((await handleHistory(historyRequest("ws=nope&date=2026-09-11"), deps)).status, 404);
  assert.equal((await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), deps)).status, 200);
});

test("handleHistory: GitHub 목록 + 그 달 일지(workflow 있는 자동화) 합치기", async () => {
  const github = fakeGithub({
    ranged: [run({ id: 100, run_started_at: "2026-09-11T00:01:00Z" })],
    texts: { "history/assembly/minutes/2026-09.jsonl": JSON.stringify({ run_id: 100, automation: "minutes", started_at: "2026-09-11T09:01:10+09:00", ok: true, summary: "신규 3건" }) + "\n" },
  });
  const body = await (await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), makeDeps({ github }))).json();
  assert.deepEqual(github.calls.listRunsBetween, [["2026-09-10T15:00:00Z", "2026-09-11T14:59:59Z"]]);
  assert.deepEqual([...github.calls.readRepoText].sort(), ["history/assembly/mail/2026-09.jsonl", "history/assembly/minutes/2026-09.jsonl"]);
  assert.deepEqual([body.date, body.today, body.start, body.source, body.partial], ["2026-09-11", "2026-09-11", HISTORY_START, "github", false]);
  assert.deepEqual(body.items.map((x) => [x.id, x.summary]), [["100", "신규 3건"]]);
});

test("handleHistory: GitHub 실패 → 일지만(archive·partial), 토큰 없음 → static, 시작일 이전 → 빈 목록", async () => {
  const github = fakeGithub({ rangedError: new GitHubUnavailableError(502), texts: { "history/assembly/minutes/2026-09.jsonl": JSON.stringify({ run_id: 7, started_at: "2026-09-11T08:00:00+09:00", ok: true, summary: "일지" }) } });
  const a = await (await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), makeDeps({ github }))).json();
  assert.deepEqual([a.source, a.partial, a.items.map((x) => x.summary)], ["archive", true, ["일지"]]);
  const s = await (await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), makeDeps({ github: null }))).json();
  assert.deepEqual([s.source, s.items], ["static", []]);
  const g2 = fakeGithub();
  const old = await (await handleHistory(historyRequest("ws=assembly&date=2026-09-01"), makeDeps({ github: g2 }))).json();
  assert.deepEqual([old.items, g2.calls.listRunsBetween.length], [[], 0]);
});

test("handleHistory: 캐시 — 오늘 30초, 지난 날 10분", async () => {
  let now = NOW;
  const github = fakeGithub();
  const deps = makeDeps({ github, now: () => now });
  await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), deps);
  await handleHistory(historyRequest("ws=assembly&date=2026-09-10"), deps);
  now += HISTORY_TODAY_CACHE_MS - 1;
  await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), deps);
  assert.equal(github.calls.listRunsBetween.length, 2);
  now += 2;
  await handleHistory(historyRequest("ws=assembly&date=2026-09-11"), deps);
  await handleHistory(historyRequest("ws=assembly&date=2026-09-10"), deps);
  assert.equal(github.calls.listRunsBetween.length, 3);
  now += HISTORY_PAST_CACHE_MS;
  await handleHistory(historyRequest("ws=assembly&date=2026-09-10"), deps);
  assert.equal(github.calls.listRunsBetween.length, 4);
});

test("handleHistory: 월말이면 다음 달 일지도 읽는다 (요청한 날 뒤에 돈 실행의 요약)", async () => {
  const github = fakeGithub();
  await handleHistory(historyRequest("ws=assembly&date=2026-09-28"), makeDeps({ github, now: () => Date.parse("2026-09-30T03:00:00Z") }));
  assert.deepEqual([...github.calls.readRepoText].sort(), [
    "history/assembly/mail/2026-09.jsonl", "history/assembly/mail/2026-10.jsonl",
    "history/assembly/minutes/2026-09.jsonl", "history/assembly/minutes/2026-10.jsonl",
  ]);
});

test("handleHistory: GitHub 보관 기간(90일) 밖의 날은 일지의 실행을 그대로 보여 준다", async () => {
  const line = JSON.stringify({ run_id: 77, automation: "minutes", started_at: "2026-09-15T09:00:00+09:00", ok: true, summary: "옛 실행" });
  const texts = { "history/assembly/minutes/2026-09.jsonl": line };
  const old = await (await handleHistory(historyRequest("ws=assembly&date=2026-09-15"), makeDeps({ github: fakeGithub({ texts }), now: () => Date.parse("2026-12-31T03:00:00Z") }))).json();
  assert.deepEqual(old.items.map((x) => x.summary), ["옛 실행"]);
  const recent = await (await handleHistory(historyRequest("ws=assembly&date=2026-09-15"), makeDeps({ github: fakeGithub({ texts }), now: () => Date.parse("2026-09-20T03:00:00Z") }))).json();
  assert.deepEqual(recent.items, []); // 90일 안: GitHub 이 이 실행을 만든 날에 둔다
});

test("handleStatus: history 는 보내지 않는다 (표는 /api/history)", async () => {
  const body = await (await handleStatus(statusRequest(), fakeEnv(), makeDeps({ github: fakeGithub({ runs: [run()] }) }))).json();
  assert.equal("history" in body, false);
});

test("handleStatus: 토큰 없으면 runs 빈 객체 · canRun false · static 파일", async () => {
  const env = fakeEnv({ "/status/assembly/minutes.json": { id: "minutes", from: "static" } });
  env.GITHUB_TOKEN = undefined;
  const body = await (await handleStatus(statusRequest(), env, makeDeps({ github: null }))).json();
  assert.deepEqual(body.config, { canRun: false, tokenExpiresAt: null, githubError: null });
  assert.deepEqual(body.runs, {});
  assert.deepEqual(body.files, { minutes: { id: "minutes", from: "static" }, mail: null });
  assert.equal(body.source, "static");
});

test("handleStatus: 같은 ws 는 15초 메모리 캐시, ws 별 별도", async () => {
  const github = fakeGithub({ runs: [run()] });
  const deps = makeDeps({ github });
  await handleStatus(statusRequest(), fakeEnv(), deps);
  deps.now = () => NOW + STATUS_CACHE_MS - 1;
  const cached = await (await handleStatus(statusRequest(), fakeEnv(), deps)).json();
  assert.equal(cached.checkedAt, new Date(NOW).toISOString());
  assert.equal(github.calls.listRuns, 1);
  await handleStatus(statusRequest("home"), fakeEnv(), deps);
  assert.equal(github.calls.listRuns, 2, "다른 ws 는 캐시를 공유하지 않음");
  deps.now = () => NOW + STATUS_CACHE_MS;
  const fresh = await (await handleStatus(statusRequest(), fakeEnv(), deps)).json();
  assert.equal(fresh.checkedAt, new Date(NOW + STATUS_CACHE_MS).toISOString());
  assert.equal(github.calls.listRuns, 3);
});

// ── GitHubClient (가짜 fetch) ──
function fakeFetch(handler) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    return handler(url, init);
  };
  impl.calls = calls;
  return impl;
}

test("GitHubClient: 공통 헤더 · dispatch 204 · 토큰 만료 헤더 기록", async () => {
  const f = fakeFetch(() => new Response(null, { status: 204, headers: { "github-authentication-token-expiration": "2027-09-01 00:00:00 UTC" } }));
  const gh = new GitHubClient("tok", f);
  await gh.dispatch("minutes.yml", { request_id: "req-1" });
  const { url, init } = f.calls[0];
  assert.equal(url, "https://api.github.com/repos/Junjaee/ai-office/actions/workflows/minutes.yml/dispatches");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, "Bearer tok");
  assert.equal(init.headers.Accept, "application/vnd.github+json");
  assert.equal(init.headers["X-GitHub-Api-Version"], "2022-11-28");
  assert.equal(init.headers["User-Agent"], "ai-office-worker");
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { request_id: "req-1" } });
  assert.equal(gh.tokenExpiresAt, "2027-09-01T00:00:00.000Z");
});

test("GitHubClient: 401/403 → GitHubAuthError, 5xx/네트워크 → GitHubUnavailableError", async () => {
  await assert.rejects(new GitHubClient("t", fakeFetch(() => new Response("", { status: 401 }))).dispatch("a.yml", {}), GitHubAuthError);
  await assert.rejects(new GitHubClient("t", fakeFetch(() => new Response("", { status: 403 }))).listRuns(30), GitHubAuthError);
  await assert.rejects(new GitHubClient("t", fakeFetch(() => new Response("", { status: 502 }))).listRuns(30), GitHubUnavailableError);
  await assert.rejects(new GitHubClient("t", fakeFetch(() => { throw new TypeError("fetch failed"); })).dispatch("a.yml", {}), GitHubUnavailableError);
  await assert.rejects(new GitHubClient("t", fakeFetch(() => new Response("", { status: 422 }))).dispatch("a.yml", {}), GitHubUnavailableError);
});

test("GitHubClient: listRuns 는 필요한 필드만 추린다", async () => {
  const f = fakeFetch(() => Response.json({ workflow_runs: [{ ...run({ id: 7 }), name: "minutes", extra: "drop" }] }));
  const runs = await new GitHubClient("t", f).listRuns(30);
  assert.equal(f.calls[0].url, "https://api.github.com/repos/Junjaee/ai-office/actions/runs?per_page=30");
  assert.deepEqual(Object.keys(runs[0]).sort(), ["conclusion", "display_title", "event", "html_url", "id", "path", "run_started_at", "status", "updated_at"]);
  assert.equal(runs[0].id, 7);
});

test("GitHubClient: readStatusFile 은 raw Accept, JSON 반환, 404 면 null", async () => {
  const f = fakeFetch((url) => (url.includes("/mail.json") ? new Response("", { status: 404 }) : Response.json({ id: "minutes" })));
  const gh = new GitHubClient("t", f);
  assert.deepEqual(await gh.readStatusFile("assembly", "minutes"), { id: "minutes" });
  assert.equal(f.calls[0].url, "https://api.github.com/repos/Junjaee/ai-office/contents/public/status/assembly/minutes.json?ref=main");
  assert.equal(f.calls[0].init.headers.Accept, "application/vnd.github.raw+json");
  assert.equal(await gh.readStatusFile("assembly", "mail"), null);
});

test("GitHubClient.listRunsBetween: created 범위 · 100개씩 · 최대 3페이지", async () => {
  const page = (n) => ({ workflow_runs: Array.from({ length: n }, (_, i) => ({ id: i + 1, path: ".github/workflows/minutes.yml", status: "completed", conclusion: "success", display_title: "t", event: "schedule", run_started_at: null, updated_at: "u", html_url: "h" })) });
  const bodies = [page(100), page(100), page(100), page(5)];
  const f = fakeFetch(() => Response.json(bodies.shift()));
  const runs = await new GitHubClient("t", f).listRunsBetween("2026-09-09T15:00:00Z", "2026-09-10T14:59:59Z");
  assert.equal(runs.length, 300);
  assert.equal(f.calls.length, 3);
  assert.equal(f.calls[0].url, "https://api.github.com/repos/Junjaee/ai-office/actions/runs?per_page=100&page=1&created=2026-09-09T15:00:00Z..2026-09-10T14:59:59Z");
  const one = fakeFetch(() => Response.json(page(2)));
  assert.equal((await new GitHubClient("t", one).listRunsBetween("a", "b")).length, 2);
  assert.equal(one.calls.length, 1);
});

test("GitHubClient.readRepoText: raw 글자, 404 → null, 5xx → Unavailable", async () => {
  const f = fakeFetch(() => new Response("line1\nline2\n"));
  assert.equal(await new GitHubClient("t", f).readRepoText("history/assembly/news/2026-09.jsonl"), "line1\nline2\n");
  assert.equal(f.calls[0].url, "https://api.github.com/repos/Junjaee/ai-office/contents/history/assembly/news/2026-09.jsonl?ref=main");
  assert.equal(f.calls[0].init.headers.Accept, "application/vnd.github.raw+json");
  assert.equal(await new GitHubClient("t", fakeFetch(() => new Response("", { status: 404 }))).readRepoText("x"), null);
  await assert.rejects(new GitHubClient("t", fakeFetch(() => new Response("", { status: 502 }))).readRepoText("x"), GitHubUnavailableError);
});


// ── /api/run inputs (mode·picks) ──
test("parseRunInputs: 허용 목록·형식만 통과, 그 밖은 null", () => {
  assert.deepEqual(parseRunInputs(undefined), {});
  assert.deepEqual(parseRunInputs({ mode: "queue", picks: "0123abcd,89ef0123" }), { mode: "queue", picks: "0123abcd,89ef0123" });
  assert.equal(parseRunInputs({ mode: "run" }), null, "run 은 화면에서 못 고른다");
  assert.equal(parseRunInputs({ picks: "x" }), null);
  assert.equal(parseRunInputs({ account: "other" }), null, "계정은 바꿀 수 없다");
  assert.equal(parseRunInputs("mode=queue"), null);
});

test("handleRun: inputs 가 있으면 설정값 뒤에 덧붙여 dispatch, all 에는 못 붙인다", async () => {
  const deps = makeDeps({ github: fakeGithub() });
  const res = await handleRun(runRequest({ ...validBody, inputs: { mode: "queue", picks: "0123abcd" } }), fakeEnv(), deps);
  assert.equal(res.status, 200);
  assert.deepEqual(deps.github.calls.dispatch, [{ file: "minutes.yml", inputs: { mode: "queue", picks: "0123abcd", request_id: validBody.requestId } }]);
  const bad = await handleRun(runRequest({ ...validBody, automation: "all", inputs: { mode: "queue" } }), fakeEnv(), makeDeps({ github: fakeGithub() }));
  assert.equal(bad.status, 400);
  const bad2 = await handleRun(runRequest({ ...validBody, inputs: { mode: "run" } }), fakeEnv(), makeDeps({ github: fakeGithub() }));
  assert.equal(bad2.status, 400);
});

// ── /api/review ──
function reviewRequest(ws, automation) {
  return new Request(`${ORIGIN}/api/review?ws=${ws}&automation=${automation}`);
}

test("handleReview: 저장소 파일을 그대로 돌려주고 15초 캐시, 없으면 file null", async () => {
  const file = { date: "2026-09-12", count: 1, candidates: [{ id: "0123abcd", title: "t" }], queue: [] };
  const deps = makeDeps({ github: fakeGithub({ texts: { "public/review/assembly/minutes.json": JSON.stringify(file) } }) });
  const res = await handleReview(reviewRequest("assembly", "minutes"), fakeEnv(), deps);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.deepEqual(body.file, file);
  assert.equal(body.source, "github");
  await handleReview(reviewRequest("assembly", "minutes"), fakeEnv(), deps);
  assert.equal(deps.github.calls.readRepoText.length, 1, "15초 안 재요청은 캐시");
  const none = await (await handleReview(reviewRequest("assembly", "mail"), fakeEnv(), deps)).json();
  assert.equal(none.file, null);
});

test("handleReview: 사무실·자동화 없으면 404, 토큰 없으면 정적 파일", async () => {
  assert.equal((await handleReview(reviewRequest("nope", "minutes"), fakeEnv(), makeDeps({ github: fakeGithub() }))).status, 404);
  assert.equal((await handleReview(reviewRequest("assembly", "unknown"), fakeEnv(), makeDeps({ github: fakeGithub() }))).status, 404);
  const deps = makeDeps({ github: null });
  const env = fakeEnv({ "/review/assembly/minutes.json": { date: "2026-09-12", candidates: [], queue: [] } });
  const body = await (await handleReview(reviewRequest("assembly", "minutes"), env, deps)).json();
  assert.equal(body.source, "static");
  assert.equal(body.file.date, "2026-09-12");
});
