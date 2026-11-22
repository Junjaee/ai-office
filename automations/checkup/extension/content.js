// 영유아검진 예약기 — 하이엔 소아청소년과 네이버 예약.
//
// 사람이 할 일: 네이버 로그인 → 검진 상품 화면 열기 → 패널에 희망 날짜·시간·아이 정보 적고 [시작].
// 이 프로그램이 할 일: 서버 시계로 월요일 09:00 을 기다렸다가 새로고침 → 열린 날짜·시간 고르기 →
//   다음단계 → 신청서 채우기. 마지막 단추는 "끝까지 자동"을 켰을 때만 누른다.
//
// 실제 화면에서 확인한 것 (2026-11-16, 로그인 없이 볼 수 있는 데까지):
//   주소      …/items/<상품>?startDate=YYYY-MM-DD   ← 날짜가 주소에 실린다
//   달력      button[class*="calendar_date"]  안 열림 = unselectable(+disabled) · 다 참 = closed · 고름 = selected
//   시간      button[class*="btn_time"]       찬 칸 = unselectable(+disabled). 글자는 12시간제("1:30")
//   필수 선택  input[type=checkbox][data-click-code^="options"]  (영유아검진(2~8차))
//   다음단계   button[class*="NextButton__btn_next"]  못 누를 때 class 에 disabled
//   시간표(hourlySchedule)는 화면을 열 때 한 번만 받는다 → 새 자리를 보려면 새로고침뿐이다.
// 확인 못 한 것: 로그인 뒤의 신청서 화면. 질문 목록은 알지만(README) 칸의 모양은 모른다 →
//   글칸(textarea)·고르기(select·radio)를 질문 글로 찾아 채우고, 화면 모양을 기록에 남긴다.

(() => {
  "use strict";
  if (window.__checkupMacro) return;
  window.__checkupMacro = true;
  const R = globalThis.checkupRules;

  // 간격을 둔다. 쉬지 않고 묻게 했다가(초당 25번) 8초쯤 만에 네이버가 화면을 통째로
  // /error/too-many-requests 로 보내 버렸다(2026-11-22 실측). 막히면 화면을 못 쓰니 정각에 가장 나쁜 일이다.
  // 70번을 초당 14번으로 물은 것은 괜찮았다 → 처음 10초만 초당 4번(40번), 그 뒤로는 2초에 한 번.
  // 화면을 다시 여는 것은 한 번에 요청이 열댓 개 나가므로 1.5초에 한 번을 넘기지 않는다.
  const BURST_MS = 10000, BURST_GAP_MS = 250, GAP_MS = 2000, RELOAD_GAP_MS = 1500;
  const OPEN_GAP_MS = 125;   // 여는 시각 앞뒤 '열렸나' 확인만 초당 8번(사용자 결정 2026-11-22). 빈 자리 확인은 BURST_GAP_MS 그대로
  const ERROR_REST_MS = 1000, BLOCK_REST_MS = 20000;
  const pace = (run) => (Date.now() - (run.began || 0) < BURST_MS ? BURST_GAP_MS : GAP_MS);
  // 막혔다는 답(429, 또는 오류 화면으로 돌려보냄)이면 길게 쉰다
  const check = (r) => {
    if (r.status === 429 || /too-many-requests/.test(r.url)) throw Object.assign(new Error("네이버가 요청이 많다고 막았어요"), { blocked: true });
    if (!r.ok) throw new Error("서버 응답 " + r.status);
  };
  const rest = (e) => sleep(e.blocked ? BLOCK_REST_MS : ERROR_REST_MS);

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $$ = (sel) => [...document.querySelectorAll(sel)];
  const waitFor = async (fn, ms) => {
    const until = Date.now() + ms;
    for (;;) {
      const v = fn();
      if (v) return v;
      if (Date.now() > until) return null;
      await sleep(30);
    }
  };

  const dayBtns = () => $$('button[class*="calendar_date"]');
  const slotBtns = () => $$('button[class*="btn_time"]');
  const nextBtn = () => $$('button[class*="NextButton__btn_next"]')[0];

  // ───────── 기억 ─────────
  // 새로고침을 넘겨야 하는 진행 상태·기록은 이 탭의 sessionStorage 에,
  // 아이 정보가 든 설정은 확장 저장소(chrome.storage)에 둔다 — 페이지 스크립트가 못 읽는 곳이다.
  const ss = (key, val) => {
    if (val === undefined) { try { return JSON.parse(sessionStorage.getItem(key)); } catch (e) { return null; } }
    sessionStorage.setItem(key, JSON.stringify(val));
  };
  const getRun = () => ss("checkup.run") || {};
  const setRun = (r) => ss("checkup.run", r);
  const ext = typeof chrome !== "undefined" && chrome.storage ? chrome.storage.local : null;
  const getCfg = async () => (ext ? (await ext.get("cfg")).cfg : ss("checkup.cfg")) || {};
  const setCfg = async (cfg) => (ext ? ext.set({ cfg }) : ss("checkup.cfg", cfg));

  // ───────── 서버 시계 ─────────
  // 응답의 Date 헤더는 초 단위다 — 초가 넘어가는 순간을 잡아 ms 까지 맞추고, 여러 번 재서
  // 가장 작은 값을 쓴다(시간제보육 확장과 같은 방법). 새로고침마다 다시 재지 않게 10분 기억한다.
  let offset = null;                          // 이 PC 시계 − 서버 시계 (ms)
  async function syncClock(rounds = 5) {
    const saved = ss("checkup.clock");
    if (saved && Date.now() - saved.at < 10 * 60 * 1000) return (offset = saved.offset);
    const probe = async () => {
      const t0 = Date.now();
      try {
        const r = await fetch("/robots.txt?t=" + Math.random(), { method: "HEAD", cache: "no-store" });
        return { d: Date.parse(r.headers.get("date") || ""), mid: t0 + (Date.now() - t0) / 2 };
      } catch (e) { return { d: 0, mid: t0 }; }
    };
    let best = Infinity;
    for (let n = 0; n < rounds; n++) {
      const first = await probe();
      if (!first.d) continue;
      const until = Date.now() + 1500;
      while (Date.now() < until) {
        const s2 = await probe();
        if (s2.d && s2.d !== first.d) { best = Math.min(best, s2.mid - s2.d); break; }
        await sleep(40);                      // 네이버에 초당 수십 번 묻지 않는다
      }
    }
    if (isFinite(best)) { offset = best; ss("checkup.clock", { offset, at: Date.now() }); }
    return offset;
  }
  const serverNow = () => Date.now() - (offset || 0);

  // ───────── 패널 ─────────
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = [
    "<style>",
    ".box{font:13px/1.5 'Malgun Gothic',sans-serif;background:#fff;border:1px solid #c9d2e3;color:#222;",
    "     border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.18);width:340px;overflow:hidden}",
    ".hd{background:#1f8f5f;color:#fff;padding:8px 12px;font-weight:700;cursor:pointer}",
    ".bd{padding:10px 12px}",
    "label{display:block;margin:0 0 6px;color:#444}",
    "input[type=text]{width:100%;box-sizing:border-box;font:inherit;padding:3px 6px;border:1px solid #c9d2e3;border-radius:5px}",
    ".row{display:flex;gap:8px;align-items:center;margin:0 0 6px}",
    "#clock{color:#1f8f5f;font:700 15px/1.2 Consolas,monospace}",
    ".btns{display:flex;gap:6px}",
    "button{flex:1;padding:8px 0;border:0;border-radius:6px;font:inherit;font-weight:700;cursor:pointer}",
    ".go{background:#1f8f5f;color:#fff} .go:disabled{opacity:.5} .no{background:#e6e9f0;color:#333} #cp{flex:0 0 56px}",
    "pre{margin:10px 0 0;background:#f6f8fc;border-radius:6px;padding:8px;height:140px;overflow:auto;",
    "    white-space:pre-wrap;font:12px/1.45 Consolas,monospace}",
    ".hide{display:none}",
    "</style>",
    '<div class="box">',
    '  <div class="hd" id="hd">영유아검진 예약기</div>',
    '  <div class="bd" id="bd">',
    '    <div class="row">서버 시각 <b id="clock">맞추는 중…</b></div>',
    '    <label>시작 시각 (비우면 누른 때부터)<input type="text" id="at" placeholder="예: 09:00:00"></label>',
    '    <label>지켜볼 시간 (분)<input type="text" id="mins" placeholder="30"></label>',
    '    <label>희망 날짜 (앞이 먼저)<input type="text" id="dates"></label>',
    '    <label>희망 시간 (앞이 먼저, 비우면 아무 시간)<input type="text" id="times"></label>',
    '    <label>아이 이름 / 생일 6자리<input type="text" id="child" placeholder="홍길동 / 240101"></label>',
    '    <label>엄마 생일, 아빠 생일 (6자리)<input type="text" id="parents" placeholder="900101, 880202"></label>',
    '    <label class="row"><input type="checkbox" id="auto"> 끝까지 자동 (마지막 예약 단추도 누름)</label>',
    '    <div class="btns">',
    '      <button class="go" id="go">시작</button>',
    '      <button class="no" id="no">멈춤</button>',
    '      <button class="no" id="cp">복사</button>',
    "    </div>",
    '    <div id="stat" style="margin:8px 0 0;color:#1f8f5f;font-weight:700"></div>',
    '    <pre id="log"></pre>',
    "  </div>",
    "</div>",
  ].join("\n");
  const $ = (id) => root.getElementById(id);

  const log = (line) => {
    const lines = (ss("checkup.log") || []).concat(new Date().toLocaleTimeString("ko-KR") + "  " + line).slice(-300);
    ss("checkup.log", lines);
    $("log").textContent = lines.join("\n") + "\n";
    $("log").scrollTop = $("log").scrollHeight;
  };

  // ───────── 진행 ─────────
  let stop = false;

  function finish(line) {
    const run = getRun();
    run.on = false;
    setRun(run);
    $("go").disabled = false;
    log(line);
  }

  // ───────── 시간표 지켜보기 ─────────
  // 화면이 쓰는 것과 같은 시간표 요청(hourlySchedule)을 희망 날짜 범위로만, 필요한 값만 받아 온다.
  // 화면을 다시 여는 것(0.8초)보다 여덟 배 빠르다. 빈 칸 = 영업 칸이고 예약 수 < 정원
  // (2026-11-16 화면의 단추 상태와 맞춰 봤다).
  const QUERY = "query hourlySchedule($scheduleParams: ScheduleParams) { schedule(input: $scheduleParams) "
    + "{ bizItemSchedule { hourly { unitStartTime unitBookingCount unitStock isSaleDay isUnitSaleDay "
    + "isUnitBusinessDay isHoliday } } } }";

  async function peek(run) {
    const days = run.dates.slice().sort();
    const r = await fetch("/graphql?opName=hourlySchedule", {
      method: "POST",
      headers: { "content-type": "application/json" },
      signal: AbortSignal.timeout(5000),            // 응답이 안 오는 요청 하나에 영영 묶이지 않게
      body: JSON.stringify({ operationName: "hourlySchedule", query: QUERY, variables: { scheduleParams: {
        businessTypeId: 13, businessId: "1432168", bizItemId: /\/items\/(\d+)/.exec(run.item)[1],
        startDateTime: days[0] + "T00:00:00", endDateTime: days[days.length - 1] + "T23:59:59",
        fixedTime: true, includesHolidaySchedules: true } } }),
    });
    check(r);
    const hourly = (((await r.json()).data || {}).schedule || {}).bizItemSchedule;
    if (!hourly) throw new Error("시간표가 비어 왔어요");
    return R.pickFromSchedule(hourly.hourly || [], run.dates, run.times);
  }

  // 이 상품이 열렸는지(화면이 쓰는 bizItems 요청에서 열림 여부만 받는다 — 2026-11-22 실제 응답으로 확인)
  async function isOpen(run) {
    const r = await fetch("/graphql?opName=bizItems", {
      method: "POST",
      headers: { "content-type": "application/json" },
      signal: AbortSignal.timeout(5000),
      body: JSON.stringify({ operationName: "bizItems",
        query: "query bizItems($input: BizItemsParams) { bizItems(input: $input) { bizItemId bookableSettingJson } }",
        variables: { input: { businessId: "1432168", lang: "ko", projections: "RESOURCE" } } }),
    });
    check(r);
    const id =/\/items\/(\d+)/.exec(run.item)[1];
    const me = ((((await r.json()).data || {}).bizItems) || []).find((b) => b.bizItemId === id);
    if (!me) throw new Error("상품 정보가 비어 왔어요");
    return (me.bookableSettingJson || {}).isOpened !== false;
  }

  // 표시가 안 된다고 예약이 멈추면 안 된다(2026-11-16: 표시 칸이 없어 매크로가 통째로 멈췄다)
  const stat = (text) => { const el = $("stat"); if (el) el.textContent = text; };

  async function watch(run) {
    let n = 0, spent = 0, said = Date.now(), lastErr = "";
    while (!stop) {
      if (Date.now() > run.until) return finish(run.mins + "분 동안 못 잡았어요 — 멈춥니다 (" + n + "번 확인)");
      const t0 = Date.now();
      let hit = null;
      try { hit = await peek(run); lastErr = ""; }
      catch (e) {                                  // 막힌 채로 두드리면 더 오래 막힌다
        if (e.message !== lastErr) { lastErr = e.message; log(e.message + " — 쉬고 다시 확인합니다"); }
        stat("오류 — " + e.message + " (" + new Date().toLocaleTimeString("ko-KR") + ")");
        await rest(e);
        continue;
      }
      n++;
      spent += Date.now() - t0;
      // 기록창은 30초에 한 줄뿐이라 멈춘 것처럼 보인다 — 돌고 있는지는 이 숫자로 본다
      stat("확인 " + n + "번 · 방금 " + new Date().toLocaleTimeString("ko-KR") + " · 빈 자리 없음");
      if (hit) {
        log("빈 자리 — " + hit.date + " " + hit.time + " (" + n + "번째 확인)");
        run.phase = "hunt";
        run.dates = [hit.date].concat(run.dates.filter((d) => d !== hit.date));   // 그 날짜부터 누른다
        setRun(run);
        return go(run, hit.date);
      }
      if (Date.now() - said > 30000) {
        said = Date.now();
        log(n + "번 확인 — 아직 빈 자리 없음 (한 번에 평균 " + Math.round(spent / n) + "ms)");
      }
      await sleep(pace(run));
    }
  }

  // 같은 상품 화면을 그 날짜로 다시 연다 — 화면이 새 시간표를 받는 유일한 길이다.
  // 연달아 열면 그것만으로 막힌다 — 앞서 연 지 1.5초가 안 됐으면 그만큼 기다렸다 연다.
  async function go(run, date) {
    const wait = (run.lastGo || 0) + RELOAD_GAP_MS - Date.now();
    if (wait > 0) await sleep(wait);
    if (stop) return;
    run.lastGo = Date.now();
    setRun(run);
    const u = new URL(run.item, location.origin);
    u.searchParams.set("startDate", date);
    location.replace(u.href);
  }

  async function waitStart(run) {
    let lastSec = -1;
    while (!stop) {
      const left = run.startAt - serverNow();
      if (left <= 0) return true;
      const sec = Math.ceil(left / 1000);
      if (sec !== lastSec && (sec <= 5 || sec % 30 === 0)) { lastSec = sec; log("시작까지 " + sec + "초"); }
      await sleep(left > 1500 ? 500 : left > 300 ? 40 : 2);
    }
    return false;
  }

  // 희망 날짜를 차례로 눌러 보고 빈 시간을 고른다. 고르면 "날짜 시간", 아니면 날짜별 상태를 돌려준다.
  async function scan(run) {
    const seen = {};
    for (const date of run.dates) {
      const cells = dayBtns().map((b) => ({ day: parseInt(b.innerText, 10), disabled: b.disabled, cls: b.className }));
      const hit = R.findDay(cells, +date.slice(8));
      seen[date] = hit.status;
      if (hit.status !== "open") continue;
      const btn = dayBtns()[hit.index];
      if (!/selected/.test(btn.className)) {
        btn.click();
        await waitFor(() => /selected/.test((dayBtns()[hit.index] || {}).className || ""), 1000);
        await sleep(60);
      }
      await waitFor(() => slotBtns().length, 800);
      const slots = slotBtns();
      const i = R.pickSlot(slots.map((b) => ({ text: b.innerText, disabled: b.disabled || /unselectable/.test(b.className) })), run.times);
      if (i < 0) { seen[date] = "full"; continue; }
      const what = date + " " + slots[i].innerText.trim();
      slots[i].click();
      return { picked: what, date, seen };
    }
    return { seen };
  }

  async function hunt(run) {
    // 여는 시각 전에는 달력 없이 "오픈예정"만 보일 수 있다 — 길게 기다리지 않고 다시 연다
    await waitFor(() => dayBtns().length, 2500);
    // 달력이 뜬 직후엔 시간표가 아직 덜 그려졌을 수 있다 — 0.6초 동안 되풀이해 본다
    let res = { seen: {} };
    for (const until = Date.now() + 600; !stop; await sleep(50)) {
      res = await scan(run);
      if (res.picked || Date.now() > until) break;
    }
    if (stop) return;

    if (res.picked) {
      log("잡았어요 — " + res.picked + " (" + (run.tries + 1) + "번째 화면)");
      $$('input[type=checkbox][data-click-code^="options"]').filter((c) => !c.checked).forEach((c) => c.click());
      const ready = () => { const b = nextBtn(); return b && !/disabled/.test(b.className) && b; };
      const toForm = (b) => { b.click(); run.phase = "form"; setRun(run); return form(run); };
      const locked = () => R.openTime((nextBtn() || {}).innerText);
      const next = await waitFor(() => ready() || (locked() && "locked"), 700);   // 잠긴 게 보이면 더 안 기다린다
      if (next && next !== "locked") return toForm(next);

      // 여는 시각 전이면 날짜·시간은 눌리지만 다음 단추가 "26. 11. 23.(월) 09:00 예약오픈" 으로 잠겨 있다
      // (2026-11-22 실제 화면). 그 시각까지 기다렸다가 화면을 다시 연다 — 그 전에 단추가 저절로 풀리면 바로 누른다.
      const label = ((nextBtn() || {}).innerText || "").trim();
      const openAt = R.openTime(label);
      if (openAt) {
        if (offset === null) await syncClock();
        if (run.openAt !== openAt) { run.openAt = openAt; setRun(run); log("아직 안 열렸어요 — " + label + ". 자리를 골라 두고 열릴 때까지 계속 확인합니다"); }
        // [시작]을 누른 때부터 서버에 '열렸나'를 계속 묻는다(사용자 결정 2026-11-22) — 2초에 한 번,
        // 여는 시각 2초 전부터 10초 뒤까지는 초당 8번. 더 촘촘히 물으면 네이버가 막는다(초당 25번 → 8초 만에 차단, 실측).
        // 열렸다는 답이 오는 즉시 넘어간다(이 PC 시계가 어긋나거나 병원이 일찍 열어도 서버의 답을 따른다).
        for (let n = 0, lastErr = ""; !stop;) {
          const b = ready();
          if (b) return toForm(b);
          const left = openAt - serverNow();
          try {
            if (await isOpen(run)) { log("열렸어요 — " + (left > 0 ? "예정보다 " + left + "ms 일찍" : "여는 시각 " + (-left) + "ms 뒤") + " (" + (n + 1) + "번째 확인)"); break; }
            n++; lastErr = "";
            stat("열렸는지 확인 " + n + "번 · " + (left > 0 ? "여는 시각까지 " + Math.ceil(left / 1000) + "초" : "여는 시각 지남, 아직 잠김"));
          } catch (e) {
            if (e.message !== lastErr) { lastErr = e.message; log(e.message + " — 쉬고 다시 확인합니다"); }
            await rest(e);
          }
          // 느린 구간에서도 '2초 전'을 넘겨 자지 않는다
          await sleep(left > 2000 ? Math.max(OPEN_GAP_MS, Math.min(GAP_MS, left - 2000)) : left > -BURST_MS ? OPEN_GAP_MS : GAP_MS);
        }
        if (stop) return;
        run.began = Date.now();                      // 열린 순간부터 10초가 가장 급하다
        run.until = Date.now() + run.mins * 60000;   // 지켜볼 시간은 열린 뒤부터 센다
        setRun(run);
        return go(run, res.date);                    // 열렸다 — 새 화면을 받아야 단추가 풀린다
      }
      log("다음단계가 안 눌려요 (" + label.slice(0, 30) + ") — 다시 찾습니다");
    }

    // 시간표엔 비었는데 화면에선 못 눌렀다 — 그 사이 자리가 나갔다. 다시 지켜본다.
    res.seen = res.seen || {};
    const sig = run.dates.map((d) => d.slice(5) + ":" + (res.seen[d] || "?")).join(" ");
    if (sig !== run.sig) {
      run.sig = sig;
      log("화면에서 못 눌렀어요 — " + sig.replace(/locked/g, "안 열림").replace(/closed/g, "마감")
        .replace(/full/g, "원하는 시간 없음").replace(/open/g, "열림").replace(/missing/g, "달력에 없음"));
    }
    run.tries++;
    run.phase = "watch";
    setRun(run);
    return watch(run);
  }

  // ───────── 신청서 ─────────
  // 네이버 예약 화면 코드(ExtraInputForm·SubmitButton 조각, 2026-11-16)에서 읽은 모양:
  //   section.section_booking_extra > .booking_inner > div(질문마다) > .form_title + 칸
  //   글칸    div.form_text.textarea > label > textarea#extraN   (onInput 으로 값을 읽는다)
  //   고르기  div.form_select > button.select_btn(안 골랐으면 안에 .placeholder)
  //           누르면 ul.select_list > li > button.select_item(글자 = 보기)
  //   예약    button[data-tst_submit_click]  "동의하고 예약하기" — 누르면 검사 → 접수 →
  //           /my/bookings/<번호> 로 화면이 바뀐다(location.replace)
  // 고르기의 답은 rules.js 의 pickOption 이 정한다 — 영유아 검진은 "있음"·"동의",
  // 교정 클리닉(연습)은 "네 확인했습니다." 처럼 상품마다 보기가 다르다(2026-11-22 실제 화면에서 확인).

  function setValue(el, v) {                      // React 가 쥔 칸은 원래 setter 로 넣고 input 을 알린다
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  async function form(run) {
    const box = await waitFor(() => document.querySelector("section.section_booking_extra"), 10000);
    if (!box) {
      if (dayBtns().length) {                      // 달력으로 되돌아왔다 — 그 사이 자리가 나갔다
        log("신청서로 못 넘어갔어요 — 다시 찾습니다");
        run.phase = "hunt";
        setRun(run);
        return go(run, run.dates[0]);
      }
      return finish("신청서(추가 정보) 칸을 못 찾았어요 — 직접 입력해 주세요");
    }
    await waitFor(() => box.querySelector(".form_title"), 2000);   // 질문은 한 박자 늦게 그려진다
    const cfg = await getCfg();
    const left = [];                               // 못 채운 질문

    for (const title of box.querySelectorAll(".form_title")) {
      const q = title.textContent.replace(/\s+/g, " ").trim();
      const row = title.parentElement;
      const ta = row.querySelector("textarea"), sel = row.querySelector(".form_select");
      if (ta) {
        const v = /엄마|아빠/.test(q) ? cfg.parents : /아이|이름/.test(q) ? cfg.child : "";
        if (v) setValue(ta, v);
        if (!ta.value.trim()) left.push(q.slice(0, 20));
      } else if (sel) {
        const btn = sel.querySelector("button.select_btn");
        if (btn.querySelector(".placeholder")) {
          btn.click();
          // 목록 첫 줄은 "선택해주세요" 안내다 — 진짜 보기만 추려 고른다
          const items = await waitFor(() => {
            const all = [...sel.querySelectorAll("button.select_item")].filter((b) => !/선택해 ?주세요/.test(b.textContent));
            return all.length && all;
          }, 1000);
          const i = items ? R.pickOption(items.map((b) => b.textContent.trim())) : -1;
          if (i >= 0) items[i].click();
          else btn.click();                        // 고를 것이 없으면 목록을 도로 닫는다
          await waitFor(() => !sel.querySelector(".select_list"), 500);
        }
        if (sel.querySelector(".select_btn .placeholder")) left.push(q.slice(0, 20));
      } else if (row.querySelector(".form_checkbox")) {
        // 체크칸 질문(영유아 검진에는 없다 — 교정 클리닉 연습용): 필수인데 하나도 안 골랐으면 첫 칸
        const boxes = [...row.querySelectorAll(".form_checkbox input[type=checkbox]")];
        if (title.querySelector(".necessary_text") && !boxes.some((b) => b.checked)) boxes[0].click();
      } else if (title.querySelector(".necessary_text")) {
        left.push(q.slice(0, 20));                 // 모르는 종류의 필수 칸
      }
    }
    const total = box.querySelectorAll(".form_title").length;
    log("신청서 " + total + "칸 중 " + (total - left.length) + "칸 채움"
        + (left.length ? " — 남은 칸: " + left.join(" / ") : ""));

    if (left.length) return finish("남은 칸을 채우고 맨 아래 예약 단추를 직접 눌러 주세요");
    if (!cfg.auto) return finish("[끝까지 자동]이 꺼져 있어요 — 내용을 보고 예약 단추를 직접 눌러 주세요");
    if (!run.real) return finish("연습 — 영유아 검진 상품이 아니라서 예약 단추는 누르지 않았어요");

    const submit = await waitFor(() => {
      const b = document.querySelector("button[data-tst_submit_click]");
      return b && !b.disabled && !/disabled|unclickable/.test(b.className) && b;
    }, 4000);
    if (!submit) return finish("예약 단추가 안 눌리는 상태예요 — 화면을 확인해 주세요");
    run.phase = "sent";                            // 성공하면 화면이 바뀌어 이 스크립트는 끝난다 → boot 가 알린다
    setRun(run);
    log("예약 단추를 눌렀어요 — " + submit.textContent.trim());
    submit.click();
    await sleep(7000);
    const pop = $$('[class*="popup"]').filter((e) => e.offsetParent !== null)
      .map((e) => e.innerText.replace(/\s+/g, " ").trim()).filter(Boolean)[0] || "";
    finish("화면이 안 넘어갔어요" + (pop ? " — " + pop.slice(0, 120) : "") + " — 직접 확인해 주세요");
  }

  async function drive() {
    const run = getRun();
    if (!run.on) return;
    $("go").disabled = true;
    stop = false;
    try {
      if (run.phase === "wait") {
        if (offset === null) await syncClock();
        log("대기 — 서버 " + $("at").value + " 에 출발 ([멈춤] 누르면 취소)");
        if (!(await waitStart(run))) return;
        run.phase = "watch";
        run.began = Date.now();
        run.until = Date.now() + run.mins * 60000;
        setRun(run);
        log("출발!");
      }
      if (run.phase === "form") return await form(run);
      if (run.phase === "watch") return await watch(run);
      await hunt(run);
    } catch (e) { finish("멈춤 — " + e.message); }
  }

  // ───────── 단추 ─────────
  async function start() {
    const dates = R.list($("dates").value), times = R.list($("times").value);
    await saveCfg();
    const mins = Math.max(1, parseFloat($("mins").value) || 30);
    if (!/\/items\/\d+/.test(location.pathname)) return log("검진 상품(영유아 검진) 화면에서 눌러 주세요");
    if (!dates.length || dates.some((d) => !/^\d{4}-\d{2}-\d{2}$/.test(d))) return log("희망 날짜는 2026-11-30 처럼 적어 주세요");
    if (times.some((t) => !/^\d{1,2}:\d{2}$/.test(t))) return log("희망 시간은 13:30 처럼 적어 주세요");
    if ($$('[class*="Footer__anchor"]').some((e) => e.innerText.trim() === "로그인")) {
      return log("네이버 로그인을 먼저 해 주세요 — 안 하면 다음단계에서 로그인 화면으로 튕겨요");
    }
    if (!$("child").value.trim() || !$("parents").value.trim()) log("아이·부모 정보가 비어 있어요 — 신청서는 직접 채워야 해요");

    const real = /영유아/.test(document.title);       // 다른 상품(교정 클리닉)에서는 연습만 — 예약 단추를 안 누른다
    const run = { on: true, phase: "watch", dates, times, tries: 0, real, mins, item: location.pathname,
                  began: Date.now(), until: Date.now() + mins * 60000 };
    log(!real ? "연습 — 영유아 검진 상품이 아니에요. 신청서까지만 채웁니다"
        : $("auto").checked ? "끝까지 자동 — 자리를 잡으면 예약 단추까지 누릅니다"
        : "신청서까지만 — 예약 단추는 직접 눌러야 해요");
    const at = $("at").value.trim();
    if (at) {
      $("go").disabled = true;
      if ((await syncClock()) === null) log("서버 시각을 못 읽었어요 — 이 PC 시계로 맞춥니다");
      const target = R.targetEpoch(at, serverNow());
      if (target === null) { $("go").disabled = false; return log("시작 시각은 08:59:59 처럼 적어 주세요"); }
      if (target > serverNow()) { run.phase = "wait"; run.startAt = target; }
      else log("그 시각은 이미 지났어요 — 바로 시작합니다");
    }
    setRun(run);
    if (run.phase !== "wait") log("출발!");
    drive();
  }

  // 적는 족족 저장한다 — [시작]을 안 눌러도, 확장을 ↻ 해도, 크롬을 껐다 켜도 남는다
  const saveCfg = () => setCfg({ blankAt: true, at: $("at").value.trim(), mins: $("mins").value.trim(), dates: $("dates").value,
    times: $("times").value, child: $("child").value.trim(), parents: $("parents").value.trim(), auto: $("auto").checked });

  async function boot() {
    const run = getRun();
    // 다른 가게 화면이면 띄우지 않는다. 단 네이버 예약은 새로고침 없이 화면을 바꾸므로(예: 내 예약 →
    // 병원 화면) 주소가 우리 병원으로 바뀌는지 계속 본다 — 안 그러면 패널이 끝내 안 뜬다.
    if (!/\/bizes\/1432168(\/|$)/.test(location.pathname) && !run.on) {
      const t = setInterval(() => {
        if (/\/bizes\/1432168(\/|$)/.test(location.pathname)) { clearInterval(t); boot(); }
      }, 500);
      return;
    }
    document.body.appendChild(host);
    const cfg = await getCfg();
    // 기본은 빈 칸(여는 시각은 화면에서 스스로 읽는다). 예전 기본값 "09:00:00" 이 저장돼 있으면 한 번 비운다.
    $("at").value = cfg.blankAt ? cfg.at || "" : "";
    // 저장한 날짜는 지난 날만 빼고 그대로 둔다. 전부 지났으면 다음에 열리는 주로 다시 채운다.
    const now = new Date(), today = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0")
      + "-" + String(now.getDate()).padStart(2, "0");
    const kept = R.list(cfg.dates).filter((d) => d > today);
    $("dates").value = (run.on ? run.dates : kept.length ? kept : R.nextWeekDates(now)).join(", ");
    $("mins").value = cfg.mins || "30";
    for (const id of ["at", "mins", "dates", "times", "child", "parents", "auto"]) $(id).addEventListener("input", saveCfg);
    $("times").value = cfg.times || "";
    $("child").value = cfg.child || "";
    $("parents").value = cfg.parents || "";
    $("auto").checked = cfg.auto !== false;         // 기본은 끝까지 자동
    $("log").textContent = (ss("checkup.log") || []).join("\n");

    $("hd").onclick = () => $("bd").classList.toggle("hide");
    $("go").onclick = () => { if (!$("go").disabled) start(); };
    $("no").onclick = () => { stop = true; finish("멈췄어요"); };
    $("cp").onclick = () => navigator.clipboard.writeText($("log").textContent.trim())
      .then(() => log("기록을 복사했어요"), () => log("복사가 막혔어요 — 기록창을 드래그해서 복사해 주세요"));

    setInterval(() => {
      if (offset === null) return;
      const d = new Date(serverNow());
      $("clock").textContent = d.toTimeString().slice(0, 8) + "." + Math.floor(d.getMilliseconds() / 100);
    }, 100);
    syncClock().then((o) => { if (o === null) log("서버 시각을 못 읽었어요 — 이 PC 시계로 보세요"); });
    if (run.on && /\/error\/too-many-requests/.test(location.pathname)) {   // 네이버가 막고 이 화면으로 보냈다
      log("네이버가 요청이 많다고 막았어요 — " + BLOCK_REST_MS / 1000 + "초 쉬고 예약 화면으로 돌아갑니다");
      await sleep(BLOCK_REST_MS);
      if (!getRun().on) return;
      run.phase = "watch";
      run.began = 0;                               // 돌아가서는 천천히
      return go(run, run.dates[0]);
    }
    if (run.on && run.phase === "sent") {          // 예약 단추를 누른 뒤 화면이 바뀌었다
      return finish(/\/my\/bookings\//.test(location.pathname)
        ? "성공 — 예약이 접수됐어요. 이 화면과 네이버 알림에서 날짜·시간을 확인하세요"
        : "예약 단추를 누른 뒤 이 화면으로 왔어요 — 예약됐는지 '내 예약'에서 확인해 주세요");
    }
    if (run.on) return drive();                    // 새로고침을 넘겨 이어 간다
    if (!ss("checkup.log")) log("검진 상품 화면에서 날짜·시간·아이 정보를 적고 [시작]");
  }

  if (document.body) boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
