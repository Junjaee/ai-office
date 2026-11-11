// 시간제보육 예약기 — 아이사랑 예약 화면 위에 떠서 정각에 자리를 잡는다.
//
// 왜 확장인가: 아이사랑은 disable-devtool 로 **개발자 도구를 막는다**(2026-11-11 확인).
// 그래서 Playwright·CDP 로 붙으면 메인으로 튕기거나 연결이 끊긴다.
// 확장의 content script 는 개발자 도구를 쓰지 않으므로 그 영향을 받지 않는다.
// manifest 의 "world": "MAIN" 덕에 페이지의 fnSave() 를 그대로 부를 수 있다.
//
// 쓰는 법: 로그인 → 기관찾기 → 예약 → 아동 선택 → '이용정보 신청' → 반 고르기 →
//          오른쪽 아래 패널에서 설정하고 [시작]. 화면 이동이 없으니 깨질 데가 없다.

(() => {
  "use strict";
  if (window.__childcareMacro) return;        // 주소가 바뀌어도 두 번 뜨지 않게
  window.__childcareMacro = true;

  const KEY = "childcare-macro";
  const CLOCK_URL = "/cms/gen/images/logo.svg";
  const SEATS_URL = "/icms/occasion/occasionCrTmInfoAjax.html";
  const WEEKDAYS = "월화수목금토일";

  const load = () => {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; }
  };
  const save = (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch {} };

  const pad = (n) => String(n).padStart(2, "0");
  const ymdDash = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  // 이용일 기본값 — 독립반은 늘 14일 뒤가 열린다
  const defaultDate = () => {
    const d = new Date();
    d.setDate(d.getDate() + 14);
    return ymdDash(d);
  };

  // ───────── 서버 시계 ─────────
  // 응답의 Date 헤더는 초 단위라, 초가 **넘어가는 순간**을 잡아야 ms 까지 맞출 수 있다.
  // 재면 늘 실제보다 늦게 나오므로(알아채는 시간 + 응답 오는 시간) 여러 번 재서 가장 작은 값을 쓴다.
  async function serverOffsetMs(rounds = 8, aborted = () => false) {
    const probe = async () => {
      const t0 = Date.now();
      const r = await fetch(`${CLOCK_URL}?t=${Math.random()}`, { method: "HEAD", cache: "no-store" });
      const t1 = Date.now();
      return { d: Date.parse(r.headers.get("date") || ""), mid: t0 + (t1 - t0) / 2 };
    };
    let best = Infinity;
    for (let n = 0; n < rounds && !aborted(); n++) {
      const first = await probe();
      if (!first.d) continue;
      const until = Date.now() + 1500;
      while (Date.now() < until && !aborted()) {
        const s = await probe();
        if (!s.d) continue;
        if (s.d !== first.d) { best = Math.min(best, s.mid - s.d); break; }
      }
    }
    if (aborted()) return null;
    if (!isFinite(best)) throw new Error("서버 시각을 못 읽었어요");
    return best;
  }

  // ───────── 자리 확인 ─────────
  // 표 전체(14일치, 약 24KB)가 한 번에 온다. 0.25초 간격 24번 찔러도 막히지 않았다(실측).
  const formVal = (name) => {
    const el = document.querySelector(`#pfrm [name="${name}"]`);
    return el ? el.value : "";
  };

  async function seatsLeft(ymd, hour, clseq) {
    const body = new URLSearchParams({
      chilinnb: formVal("chilinnb"), stcode: formVal("stcode"), clseq,
    }).toString();
    const res = await fetch(SEATS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest" },
      body,
    });
    if (!res.ok) throw new Error(`자리 확인 실패 HTTP ${res.status}`);
    const box = document.createElement("div");
    box.innerHTML = await res.text();
    // 표의 첫 줄이 늘 오늘인 것은 아니다(당일 마감이 지나면 오늘이 빠진다).
    // 그래서 줄 번호를 계산하지 않고, 줄에 적힌 날짜를 보고 찾는다.
    const rows = [...box.querySelectorAll("tr")].filter((tr) => /\d{4}-\d{2}-\d{2}/.test(tr.innerText));
    const days = rows.map((tr) => (tr.innerText.match(/\d{4}-\d{2}-\d{2}/) || [""])[0]);
    const i = days.indexOf(ymd);
    if (i < 0) return -1;                                   // 그 날짜가 아직 안 열렸다
    const cell = box.querySelector(`#tm_${hour}_${i}`);
    const txt = cell ? cell.innerText.trim() : "";
    return /^\d+$/.test(txt) ? Number(txt) : 0;             // X(운영 안 함)도 0
  }

  // ───────── 장전 ─────────
  // 숨은 값을 직접 채워 넣는 방식을 써 봤지만 사이트가
  // "이용정보를 선택해 주시기 바랍니다" 로 막았다(2026-11-11).
  // 처음 손으로 성공했을 때는 앞서 진짜 '추가' 를 눌렀다 지운 화면이라,
  // 사이트가 남긴 무언가가 더 있었던 것이다. 그래서 **사이트의 진짜 버튼을 그대로 누른다.**
  // 한 번의 왕복(중복 확인)이 더 들지만 확실하다.

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function setSelect(id, value) {
    const el = document.getElementById(id);
    if (el && el.value !== String(value)) {
      el.value = String(value);
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  // 화면 표에서 그 날짜가 몇 번째 줄인지. 줄 번호는 칸 id 의 뒷자리다(tm_9_<줄>).
  function pageRowIndex(ymd) {
    const rows = [...document.querySelectorAll("tr")].filter((tr) => tr.querySelector("a.time-option"));
    for (const tr of rows) {
      if ((tr.innerText.match(/\d{4}-\d{2}-\d{2}/) || [""])[0] !== ymd) continue;
      const id = tr.querySelector("a.time-option").id;
      const m = id.match(/_(\d+)$/);
      if (m) return Number(m[1]);
    }
    return -1;
  }

  // 사이트 차례 그대로: 반·시간 고르기 → 표 새로 받기 → 칸 누르기 → 추가
  async function addViaSite(ymd, beginHour, hours, clseq, log) {
    setSelect("clname", clseq);
    setSelect("rtm", hours);
    if (window.fnRefresh) window.fnRefresh();

    const until = Date.now() + 15000;
    let idx = -1;
    while (Date.now() < until && !stop) {
      idx = pageRowIndex(ymd);
      if (idx >= 0) break;
      await sleep(150);
    }
    if (idx < 0) throw new Error(`${ymd} 줄이 화면 표에 없어요`);

    setSelect("clname", clseq);                 // 표를 새로 받으면 되돌아가기도 한다
    setSelect("rtm", hours);
    const cell = document.getElementById(`tm_${beginHour}_${idx}`);
    if (!cell) throw new Error(`${pad(beginHour)}시 칸이 없어요 (${ymd})`);
    const mark = cell.innerText.trim();
    if (mark === "X" || mark === "0") throw new Error(`${pad(beginHour)}시 자리가 없어요 (${mark})`);
    cell.click();                               // selectDay2
    await sleep(120);

    const before = popups.length;
    document.getElementById("timecareTableAddBtn").click();   // f_AddQualRow — 서버 확인 한 번
    const until2 = Date.now() + 10000;
    while (Date.now() < until2 && !stop) {
      if (document.querySelector("#INFOQUALF tr[id^=tId_]")) {
        const got = document.querySelector('#pfrm input[name="resdtArray"]');
        log(`장전됨 — ${got ? got.value : "?"} ${cell.innerText.trim()}자리`);
        return;
      }
      if (popups.length > before) break;                   // 사이트가 거절했다 — 더 기다릴 것 없다
      await sleep(100);
    }
    const said = popups.slice(before).join(" / ");
    throw new Error(said ? `추가 거절 — ${said}` : "추가가 안 됐어요 (사이트가 아무 말도 안 했어요)");
  }

  // ───────── 발사 ─────────
  // 넷퍼넬(대기열)이 걸려 있어 **한 발만** 쏜다. 다시 쏘면 줄 뒤로 밀린다.
  // 대신 확인창은 뜨는 즉시 누른다 — 사람은 0.5~1초, 이건 1프레임이다.
  // 사이트가 띄우는 모든 안내를 받아 적고 닫는다. [시작] 때 한 번 걸어 두고 계속 둔다.
  // 거절 사유가 여기로 오는데, 지금까지는 이걸 안 보고 있어서 원인을 몰랐다(2026-11-11).
  const popups = [];
  let popupWatching = false;

  function watchPopups() {
    if (popupWatching) return;
    popupWatching = true;
    const shown = new Map();                               // 창마다 '지금 떠 있는 글' 을 기억
    const hit = () => {
      for (const id of ["layer-confirm-popup-contents", "layer-confirm-popup-contents2",
                        "layer-popup-contents", "layer-popup-contents2", "layer-popup-contents3",
                        "alertMsg", "layer-alert-popup-contents"]) {
        const box = document.getElementById(id);
        if (!box || box.offsetParent === null) { shown.delete(id); continue; }
        const t = box.innerText.trim();
        // 닫혔다 같은 글로 다시 떠도 새 안내다 — 그래서 닫힐 때 기억을 지운다
        if (t && shown.get(id) !== t) { shown.set(id, t); popups.push(t); }
      }
      for (const id of ["layer-confirm-popup-confirm", "layer-confirm-popup-confirm2",
                        "layer-popup-close", "layer-popup-close2", "layer-popup-close3"]) {
        const el = document.getElementById(id);
        if (el && el.offsetParent !== null) { el.click(); return; }
      }
    };
    new MutationObserver(hit).observe(document.body, { subtree: true, attributes: true, childList: true });
    const nativeAlert = window.alert, nativeConfirm = window.confirm;
    window.alert = (m) => { popups.push(String(m)); };
    window.confirm = (m) => { popups.push(String(m)); return true; };
    void nativeAlert; void nativeConfirm;                  // 되돌리지 않는다 — 끝까지 받아 적어야 한다
    hit();
  }

  // ───────── 발사 ─────────
  // 넷퍼넬(대기열)이 걸려 있어 **한 발만** 쏜다. 다시 쏘면 줄 뒤로 밀린다.
  function fire() {
    const from = popups.length;
    window.fnSave();
    return new Promise((resolve) => {
      let left = 240;
      const timer = setInterval(() => {
        const said = popups.slice(from);
        // 멈춤을 눌러도 이미 보낸 신청은 되돌릴 수 없다 — 기다리기만 그만둔다
        if (said.length || stop || --left <= 0) {
          clearInterval(timer);
          const msg = said.join(" / ");
          if (!msg && stop) return resolve({ ok: false, msg: "기다리기를 멈췄어요 (신청은 이미 보냈습니다)" });
          resolve({ ok: /예약되었습니다|예약완료|신청이 완료|정상적으로/.test(msg), msg: msg || "응답이 없어요" });
        }
      }, 250);
    });
  }

  // ───────── 본체 ─────────
  let stop = false;

  async function run(cfg, log) {
    const clsel = document.getElementById("clname");
    if (!clsel || !clsel.value) throw new Error("반을 먼저 고르세요 ('이용정보 신청' 에서 반명 선택)");
    const clseq = clsel.value;
    const clname = clsel.options[clsel.selectedIndex].text.trim();
    if (!document.getElementById("INFOQUALF")) throw new Error("예약 화면이 아니에요 ('이용정보 신청' 을 여세요)");

    watchPopups();
    const beginHour = Number(cfg.beginHour), hours = Number(cfg.hours);
    log(`${cfg.useDate} ${pad(beginHour)}:00 부터 ${hours}시간 · ${clname}반`);

    // 즉시: 기다리지 않고 지금부터 지켜보다 자리가 나면 바로 잡는다.
    //       취소표 잡기에도 그대로 쓴다. 정해진 시각이 없으니 '보험 한 발' 은 쏘지 않는다
    //       (쏠 시각이 없는데 미리 쏘면 거절당하고 그 한 발을 날린다).
    const NOW_MODE = !!cfg.now;
    let fireAt, watchFrom, giveUp;

    if (NOW_MODE) {
      fireAt = Infinity;                                   // 예정 발사 없음 — 자리가 보일 때만 쏜다
      watchFrom = Date.now();
      giveUp = Date.now() + 60 * 60 * 1000;                // 한 시간 지켜보고 그만둔다
      log("즉시 — 지금부터 지켜보다 자리가 나면 바로 잡습니다 (한 시간)");
    } else {
      log("서버 시각 맞추는 중… (10초쯤 걸립니다)");
      const offset = await serverOffsetMs(8, () => stop);
      if (offset === null) return log("멈췄어요");
      log(`이 PC 시계가 서버보다 ${offset > 0 ? "+" : ""}${Math.round(offset)}ms`);

      const [oh, om, os] = cfg.openAt.split(":").map(Number);
      const openAt = new Date();
      openAt.setHours(oh, om, os || 0, 0);
      if (openAt.getTime() <= Date.now()) openAt.setDate(openAt.getDate() + 1);
      fireAt = openAt.getTime() + offset;                  // 이 PC 시계 기준 발사 시각
      watchFrom = fireAt - Number(cfg.watchBefore) * 1000;
      giveUp = fireAt + 120000;
      log(`${new Date(watchFrom).toLocaleTimeString("ko-KR")} 부터 감시, ${new Date(fireAt).toLocaleTimeString("ko-KR")} 에 발사`);
    }

    const shoot = async (why) => {
      log(`${why} → 장전`);
      await addViaSite(cfg.useDate, beginHour, hours, clseq, log);
      log("발사");
      const r = await fire();
      log((r.ok ? "성공 — " : "실패 — ") + r.msg);
      return r.ok;
    };

    let said30 = -1;
    while (!stop && Date.now() < watchFrom) {
      const left = Math.round((watchFrom - Date.now()) / 1000);
      if (left % 30 === 0 && left !== said30) { said30 = left; log(`감시 시작까지 ${left}초`); }
      await new Promise((r) => setTimeout(r, 250));
    }
    if (stop) return log("멈췄어요");

    log("감시 시작 — 열리는 순간 쏩니다");
    // 보험 한 발은 없앴다 — 줄이 화면 표에 없으면 장전 자체가 안 되므로,
    // 자리가 보이는 것이 곧 방아쇠다.
    let lastSeen = null, lastError = null, fails = 0, shootFails = 0;
    while (!stop && Date.now() < giveUp) {
      try {
        const seats = await seatsLeft(cfg.useDate, beginHour, clseq);
        fails = 0; lastError = null;
        if (seats !== lastSeen) {
          lastSeen = seats;
          log(seats < 0 ? "아직 그 날짜가 표에 없어요" : `남은 자리 ${seats}개`);
        }
        if (seats >= 1) {
          try {
            if (await shoot("열림 확인")) return;
            shootFails++;
          } catch (e) {
            shootFails++;
            log(`${shootFails}번째 실패 — ${String(e.message).slice(0, 90)}`);
          }
          // 중복·이미 예약 같은 사유는 다시 해도 안 된다. 세 번이면 그만두고 사람에게 넘긴다.
          if (shootFails >= 3) return log("세 번 해도 안 됩니다 — 위 문구를 보고 날짜·시각을 바꿔 보세요");
        }
      } catch (e) {
        // 같은 오류를 0.5초마다 쌓으면 기록창이 묻힌다 — 달라질 때만 적는다
        const why = String(e.message).slice(0, 60);
        if (why !== lastError) { lastError = why; log(`확인 실패(계속 감시) — ${why}`); }
        if (++fails === 10) log("열 번 내리 실패했어요 — 로그인이 풀렸는지 확인해 보세요");
      }
      await new Promise((r) => setTimeout(r, Number(cfg.watchInterval)));
    }
    log(stop ? "멈췄어요" : "시간 안에 못 잡았어요");
  }

  // ───────── 패널 ─────────
  const cfg = Object.assign({
    useDate: defaultDate(), beginHour: 9, hours: 4,
    openAt: "09:00:00", watchBefore: 60, watchInterval: 200, now: false,
  }, load());
  if (cfg.useDate < ymdDash(new Date())) cfg.useDate = defaultDate();

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      .box{font:13px/1.5 'Malgun Gothic',sans-serif;background:#fff;border:1px solid #c9d2e3;
           border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.18);width:344px;overflow:hidden}
      .hd{background:#2f4b8b;color:#fff;padding:8px 12px;font-weight:700;display:flex;justify-content:space-between;cursor:pointer}
      .bd{padding:10px 12px}
      label{display:flex;align-items:center;gap:6px;margin:6px 0}
      label span{width:62px;color:#444;flex:none}
      input,select{padding:3px 6px;border:1px solid #c9d2e3;border-radius:5px;font:inherit}
      .row{display:flex;gap:5px;align-items:center;white-space:nowrap}
      .btns{display:flex;gap:6px;margin-top:10px}
      button{flex:1;padding:7px 0;border:0;border-radius:6px;font:inherit;font-weight:700;cursor:pointer}
      .go{background:#2f4b8b;color:#fff} .no{background:#e6e9f0;color:#333}
      pre{margin:10px 0 0;background:#f6f8fc;border-radius:6px;padding:8px;height:120px;overflow:auto;
          white-space:pre-wrap;font:12px/1.45 Consolas,monospace}
      .hide{display:none}
      .chk{margin:0;gap:4px;white-space:nowrap} .chk span{width:auto}
    </style>
    <div class="box">
      <div class="hd"><span>시간제보육 예약기</span><span id="fold">—</span></div>
      <div class="bd" id="bd">
        <label><span>이용일</span><input type="date" id="d"></label>
        <label><span>이용 시간</span>
          <span class="row"><select id="b"></select>시부터 <select id="h"></select>시간</span></label>
        <label><span>오픈 시각</span>
          <span class="row"><input type="time" id="o" step="1">
          <label class="chk"><input type="checkbox" id="now">즉시</label></span></label>
        <label><span>미리 감시</span><input type="number" id="w" style="width:52px">초 전부터</label>
        <div class="btns"><button class="go" id="go">시작</button><button class="no" id="no">멈춤</button></div>
        <pre id="log"></pre>
      </div>
    </div>`;
  document.body.appendChild(host);

  const $ = (id) => root.getElementById(id);
  for (let h = 9; h <= 17; h++) $("b").add(new Option(pad(h), String(h)));
  for (let n = 1; n <= 9; n++) $("h").add(new Option(String(n), String(n)));
  $("d").value = cfg.useDate; $("b").value = String(cfg.beginHour);
  $("h").value = String(cfg.hours); $("o").value = cfg.openAt; $("w").value = cfg.watchBefore;
  // 패널에서 이용 시간을 고르면 화면의 '이용시간' 칸도 바로 따라가게 한다.
  // (발사 직전에도 한 번 더 맞춘다 — arm() 안에서)
  const syncRtm = () => {
    const b = Number($("b").value), h = Number($("h").value);
    const real = Math.min(b + h, 18) - b;                  // 18시를 넘으면 잘린다
    const sel = document.getElementById("rtm");
    if (sel && sel.value !== String(real)) {
      sel.value = String(real);
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return real;
  };
  $("b").onchange = syncRtm;
  $("h").onchange = syncRtm;

  $("now").checked = !!cfg.now;
  const syncNow = () => { $("o").disabled = $("now").checked; $("w").disabled = $("now").checked; };
  $("now").onchange = syncNow;
  syncNow();

  const log = (line) => {
    const el = $("log");
    el.textContent += `${new Date().toLocaleTimeString("ko-KR")}  ${line}\n`;
    el.scrollTop = el.scrollHeight;
  };
  root.querySelector(".hd").onclick = () => $("bd").classList.toggle("hide");

  $("go").onclick = async () => {
    Object.assign(cfg, {
      useDate: $("d").value, beginHour: $("b").value, hours: $("h").value,
      openAt: $("o").value.length === 5 ? `${$("o").value}:00` : $("o").value,
      watchBefore: $("w").value, now: $("now").checked,
    });
    save(cfg);
    stop = false;
    $("go").disabled = true;
    try { await run(cfg, log); } catch (e) { log(`멈춤 — ${e.message}`); }
    $("go").disabled = false;
  };
  $("no").onclick = () => {
    if (stop) return;
    stop = true;
    log("멈추는 중… (이미 보낸 신청은 되돌릴 수 없어요)");
  };

  syncRtm();
  log("반까지 고른 뒤 [시작]을 누르세요");
})();
