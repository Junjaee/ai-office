// 시간제보육 예약기 — 예약하기 · 확인 · 확인을 될 때까지 빠르게 되풀이한다.
//
// 사람이 할 일: 로그인 → 기관 → 아동 선택 → 이용정보 신청 → 반·시간 고르고 **추가까지**.
// 이 프로그램이 할 일: 그 상태에서 [시작] 을 누르면 예약하기를 광클한다. 그게 전부다.
//
// 왜 확장인가: 아이사랑은 disable-devtool 로 개발자 도구를 막는다(2026-11-11 확인).
// Playwright·CDP 로 붙으면 메인으로 튕기거나 연결이 끊긴다. 확장은 그 영향을 받지 않고,
// manifest 의 "world": "MAIN" 덕에 페이지의 fnSave() 를 그대로 부를 수 있다.
//
// 실제 화면에서 확인한 한 바퀴 (2026-11-12 00:30, 아직 안 열린 11-26 으로):
//   예약하기(fnSave)
//     → "예약하시겠습니까?"                  layer-confirm-popup-contents2
//     → 확인                                 layer-confirm-popup-confirm2
//     → "아직 예약 가능한 시간이 아닙니다."    layer-alert-popup-contents2
//     → 확인                                 layer-popup-close2   ← 닫아야 다시 누를 수 있다
//
// 함정 둘 (실제 화면에서만 드러났다):
//   · 거절 문구는 layer-popup-contents 가 아니라 layer-alert-popup-contents2 에 뜬다.
//   · 같은 id 가 문서에 두 벌씩 있다(숨은 것 + 보이는 것). getElementById 는 첫 번째를
//     집으므로 숨은 쪽을 잡아 글도 못 읽고 확인도 못 누른다 → 같은 id 를 전부 훑어 보이는 것을 쓴다.

(() => {
  "use strict";
  if (window.__childcareMacro) return;        // 주소가 바뀌어도 두 번 뜨지 않게
  window.__childcareMacro = true;

  // 실측(2026-11-12, 아이사랑 실제 화면): 확인창 뜨기 0ms · 확인 누른 뒤 결과 107ms · 닫기 0ms.
  // 화면 조작은 공짜고 **서버 왕복 107ms 가 전부**다. 그래서 쉬는 시간을 둘 이유가 없다.
  // 한 바퀴 약 110ms = 초당 9번. 더 줄이려면 응답을 안 기다리고 겹쳐 쏴야 하는데,
  // 확인창이 하나뿐이라 서로 꼬인다.
  const GAP_MS = 0;                           // 한 바퀴 돌고 다음 발사까지
  const GIVE_UP_MS = 30 * 60 * 1000;          // 이만큼 해도 안 되면 그만둔다

  const DONE = /예약되었습니다|예약완료|신청이 완료|정상적으로/;
  const NOT_YET = /아직|가능한 시간이 아닙|기간이 아닙/;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // 같은 id 가 두 벌씩 있어 getElementById 로는 숨은 쪽을 집는다 — 보이는 것을 고른다
  const visible = (id) =>
    [...document.querySelectorAll('[id="' + id + '"]')].find((e) => e.offsetParent !== null);

  const SAY_IDS = ["layer-alert-popup-contents", "layer-alert-popup-contents2",
                   "layer-alert-popup-contents3", "layer-popup-contents",
                   "layer-popup-contents2", "layer-popup-contents3", "alertMsg"];
  const ASK_IDS = ["layer-confirm-popup-contents", "layer-confirm-popup-contents2"];
  const OK_IDS = ["layer-confirm-popup-confirm", "layer-confirm-popup-confirm2",
                  "layer-popup-close", "layer-popup-close2", "layer-popup-close3",
                  "layer-alert-popup-close", "layer-alert-popup-close2"];

  // ───────── 창 감시 ─────────
  // 뜨는 즉시 확인을 누르고, 결과 문구만 따로 모은다.
  // 물어보는 창("예약하시겠습니까?")을 결과로 세면 성공을 실패로 읽는다.
  const said = [];
  let watching = false, lastQueue = "", wake = null;

  function watch(log) {
    if (watching) return;
    watching = true;
    const shown = new Map();

    const tick = () => {
      for (const id of SAY_IDS.concat(ASK_IDS)) {
        const box = visible(id);
        if (!box) { shown.delete(id); continue; }
        const t = box.innerText.trim();
        if (!t || shown.get(id) === t) continue;   // 닫혔다 같은 글로 다시 떠도 새 안내다
        shown.set(id, t);
        if (SAY_IDS.includes(id)) {                // 결과만 모은다
          said.push(t);
          if (wake) { const w = wake; wake = null; w(); }   // 기다리는 쪽을 즉시 깨운다
        }
      }

      // 넷퍼넬 대기열은 보기만 한다. 누르거나 다시 쏘면 대기표를 버리고 맨 뒤로 간다.
      const top = visible("NetFunnel_Skin_Top");
      if (top) {
        const n = visible("NetFunnel_Loading_Popup_Count");
        const left = visible("NetFunnel_Loading_Popup_TimeLeft");
        const line = [n && "앞에 " + n.innerText.trim() + "명",
                      left && "예상 " + left.innerText.trim()]
          .filter(Boolean).join(" · ") || top.innerText.trim().replace(/\s+/g, " ").slice(0, 60);
        if (line !== lastQueue) { lastQueue = line; log("대기열 — " + line); }
        return;                                    // 대기 중에는 아무 버튼도 누르지 않는다
      }

      for (const id of OK_IDS) {
        const btn = visible(id);
        if (btn) { btn.click(); return; }
      }
    };

    new MutationObserver(tick).observe(document.body, { subtree: true, attributes: true, childList: true });
    window.alert = (m) => said.push(String(m));
    window.confirm = () => true;
    tick();
  }

  // 한 발 — 예약하기를 누르고 결과 문구가 올 때까지 기다린다.
  // 들여다보며 기다리지 않고 **결과가 뜨는 순간 깨어난다**(관찰자가 깨운다).
  async function fire(stopped) {
    const from = said.length;
    const got = new Promise((res) => { wake = res; });
    window.fnSave();

    const deadline = Date.now() + 120000;          // 최대 2분
    while (Date.now() < deadline) {
      const hit = await Promise.race([got, sleep(200).then(() => null)]);
      if (said.length > from) { wake = null; return said.slice(from).join(" / "); }
      if (hit !== null) break;
      if (visible("NetFunnel_Skin_Top")) continue; // 줄 서는 동안은 끝까지 기다린다
      if (stopped()) break;
    }
    wake = null;
    return said.length > from ? said.slice(from).join(" / ") : "";
  }

  // ───────── 본체 ─────────
  let stop = false;

  async function run(log) {
    const rows = [...document.querySelectorAll("#INFOQUALF tr[id^=tId_]")];
    if (!rows.length) throw new Error("예약 목록이 비어 있어요 — 칸을 고르고 [추가] 를 먼저 눌러 주세요");
    const what = rows.map((tr) => tr.innerText.replace(/\s+/g, " ").trim().slice(0, 40));
    log("목록 " + rows.length + "건 — " + what.join(" / "));

    watch(log);
    const until = Date.now() + GIVE_UP_MS;
    let tries = 0, last = "", spent = 0;

    while (!stop && Date.now() < until) {
      tries++;
      const t0 = Date.now();
      const msg = await fire(() => stop);
      spent += Date.now() - t0;                    // 한 바퀴가 얼마나 걸리는지 — 내일 보려고
      if (stop) break;

      if (!msg) {                                  // 응답이 안 왔다
        if (tries % 10 === 0) log(tries + "번째 — 응답이 없어요, 계속합니다");
        await sleep(GAP_MS);
        continue;
      }
      if (DONE.test(msg)) {
        return log("성공 — " + msg + " (" + tries + "번째, 한 바퀴 평균 "
                   + Math.round(spent / tries) + "ms)");
      }
      if (!NOT_YET.test(msg)) return log("멈춥니다 — " + msg + " (다시 해도 안 될 사유예요)");

      if (msg !== last) { last = msg; log(tries + "번째 — " + msg); }
      else if (tries % 25 === 0) {
        log(tries + "번째까지 같은 답 — 계속합니다 (한 바퀴 평균 "
            + Math.round(spent / tries) + "ms)");
      }
      await sleep(GAP_MS);
    }
    log(stop ? "멈췄어요" : "시간이 다 됐어요 (30분)");
  }

  // ───────── 패널 ─────────
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = [
    "<style>",
    ".box{font:13px/1.5 'Malgun Gothic',sans-serif;background:#fff;border:1px solid #c9d2e3;",
    "     border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.18);width:330px;overflow:hidden}",
    ".hd{background:#2f4b8b;color:#fff;padding:8px 12px;font-weight:700;cursor:pointer}",
    ".bd{padding:10px 12px}",
    ".btns{display:flex;gap:6px}",
    "button{flex:1;padding:8px 0;border:0;border-radius:6px;font:inherit;font-weight:700;cursor:pointer}",
    ".go{background:#2f4b8b;color:#fff} .no{background:#e6e9f0;color:#333} #cp{flex:0 0 56px}",
    "pre{margin:10px 0 0;background:#f6f8fc;border-radius:6px;padding:8px;height:150px;overflow:auto;",
    "    white-space:pre-wrap;font:12px/1.45 Consolas,monospace}",
    ".hide{display:none}",
    "</style>",
    '<div class="box">',
    '  <div class="hd" id="hd">시간제보육 예약기</div>',
    '  <div class="bd" id="bd">',
    '    <div class="btns">',
    '      <button class="go" id="go">시작</button>',
    '      <button class="no" id="no">멈춤</button>',
    '      <button class="no" id="cp">복사</button>',
    "    </div>",
    '    <pre id="log"></pre>',
    "  </div>",
    "</div>",
  ].join("\n");
  document.body.appendChild(host);

  const $ = (id) => root.getElementById(id);
  const log = (line) => {
    const el = $("log");
    el.textContent += new Date().toLocaleTimeString("ko-KR") + "  " + line + "\n";
    el.scrollTop = el.scrollHeight;
  };

  $("hd").onclick = () => $("bd").classList.toggle("hide");

  $("go").onclick = async () => {
    if ($("go").disabled) return;
    stop = false;
    $("go").disabled = true;
    try { await run(log); } catch (e) { log("멈춤 — " + e.message); }
    $("go").disabled = false;
  };

  $("no").onclick = () => {
    if (stop) return;
    stop = true;
    log("멈추는 중… (이미 보낸 신청은 되돌릴 수 없어요)");
  };

  $("cp").onclick = async () => {
    const text = $("log").textContent.trim();
    try {
      await navigator.clipboard.writeText(text);
      log("기록을 복사했어요");
    } catch (e) {
      const sel = document.createElement("textarea");
      sel.value = text;
      document.body.appendChild(sel);
      sel.select();
      try { document.execCommand("copy"); log("기록을 복사했어요"); }
      catch (e2) { log("복사가 막혔어요 — 기록창을 드래그해서 복사해 주세요"); }
      sel.remove();
    }
  };

  const ready = document.querySelectorAll("#INFOQUALF tr[id^=tId_]").length;
  log(ready ? "목록에 " + ready + "건 있어요 — [시작]을 누르세요"
            : "칸을 고르고 [추가] 까지 누른 뒤 [시작]을 누르세요");
})();
