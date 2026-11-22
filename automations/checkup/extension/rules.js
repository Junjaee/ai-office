// 영유아검진 예약기 — 화면을 건드리지 않는 계산만 모아 둔다(rules.test.mjs 가 node 로 돌린다).
(() => {
  "use strict";
  const two = (n) => String(n).padStart(2, "0");
  const ymd = (d) => d.getFullYear() + "-" + two(d.getMonth() + 1) + "-" + two(d.getDate());

  // 하이엔은 "매주 월요일 09시에 다음 주 월~금"을 연다(2026-11-16 예약 화면 안내문).
  // 그래서 목표는 '다가오는 여는 월요일(오늘이 월요일이면 오늘)'의 다음 주 월~금이다.
  function nextWeekDates(now) {
    const open = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    open.setDate(open.getDate() + ((8 - open.getDay()) % 7));      // 월요일이면 0
    return [7, 8, 9, 10, 11].map((n) => {
      const d = new Date(open);
      d.setDate(d.getDate() + n);
      return ymd(d);
    });
  }

  const list = (text) => String(text || "").split(/[\s,]+/).filter(Boolean);

  // 화면의 시간 단추는 12시간제("1:30")다. 설정은 24시간제("13:30")로 받는다.
  function to12h(hm) {
    const m = /^(\d{1,2}):(\d{2})$/.exec(hm);
    if (!m) return hm;
    const h = +m[1];
    return (h > 12 ? h - 12 : h) + ":" + m[2];
  }

  // slots: [{text, disabled}] · prefs: ["10:30","13:30"] (앞이 먼저) · 비어 있으면 빈 칸 아무거나.
  // 고른 칸의 번호, 없으면 -1.
  function pickSlot(slots, prefs) {
    const free = (s) => !s.disabled;
    if (!prefs.length) return slots.findIndex(free);
    for (const p of prefs) {
      const i = slots.findIndex((s) => free(s) && s.text.trim() === to12h(p));
      if (i >= 0) return i;
    }
    return -1;
  }

  // 같은 숫자가 달력에 두 번 나올 수 있다(이번 달 1일과 끝줄의 다음 달 1일) — 열린 쪽을 고른다.
  // cells: [{day, disabled, cls}] → {index, status: open|closed|locked|missing}
  function findDay(cells, day) {
    const rank = { open: 0, closed: 1, locked: 2 };
    let best = { index: -1, status: "missing" };
    cells.forEach((c, index) => {
      if (c.day !== day) return;
      const status = /closed/.test(c.cls) ? "closed"
                   : (c.disabled || /unselectable/.test(c.cls)) ? "locked" : "open";
      if (best.index < 0 || rank[status] < rank[best.status]) best = { index, status };
    });
    return best;
  }

  // "HH:MM:SS" → 서버 기준 오늘 그 시각의 epoch(ms). 못 읽으면 null.
  function targetEpoch(hms, serverNow) {
    const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(String(hms).trim());
    if (!m) return null;
    const d = new Date(serverNow);
    d.setHours(+m[1], +m[2], +(m[3] || 0), 0);
    return d.getTime();
  }

  // 시간표 응답(hourly)에서 희망 날짜·시간 순서대로 빈 칸 하나를 고른다. {date, time} 또는 null.
  // 빈 칸 = 영업 칸이고 예약 수 < 정원 (2026-11-16 화면의 단추 상태와 맞춰 봤다).
  function pickFromSchedule(hourly, dates, times) {
    const free = hourly.filter((h) => h.isUnitBusinessDay && h.isUnitSaleDay !== false && h.isSaleDay !== false
                                      && !h.isHoliday && h.unitBookingCount < h.unitStock);
    const want = times.map((t) => t.padStart(5, "0"));             // "9:30" → "09:30"
    for (const date of dates) {
      const open = free.filter((h) => h.unitStartTime.slice(0, 10) === date)
                       .map((h) => h.unitStartTime.slice(11, 16)).sort();
      const time = want.length ? want.find((t) => open.includes(t)) : open[0];
      if (time) return { date, time };
    }
    return null;
  }

  // 고르기 질문의 보기 중 무엇을 누를지. 번호, 고를 게 없으면 -1.
  //   ① "있음"·"동의" 딱 그 글자  ② 보기가 하나뿐이면 그것  ③ 동의·확인하는 뜻의 보기(거절하는 보기는 뺀다)
  // 뜻을 모르는 보기를 아무거나 누르지는 않는다 — 그때는 비워 두고 사람에게 넘긴다.
  function pickOption(texts) {
    const no = /비동의|없음|아니|안 ?함|미동의|거부/;
    let i = texts.findIndex((t) => /^(있음|동의)$/.test(t));
    if (i < 0 && texts.length === 1) i = 0;
    if (i < 0) i = texts.findIndex((t) => /동의|확인|있음|^(네|예)\b|^(네|예)[ ,.]/.test(t) && !no.test(t));
    return i;
  }

  // 여는 시각 전의 다음 단추 글자 "26. 11. 23.(월) 09:00 예약오픈" → 그 시각(epoch ms). 그런 글자가 아니면 null.
  function openTime(label) {
    const m = /(\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*\([^)]*\)\s*(\d{1,2}):(\d{2})\s*예약\s*오픈/.exec(String(label || ""));
    return m ? new Date(2000 + +m[1], +m[2] - 1, +m[3], +m[4], +m[5]).getTime() : null;
  }

  globalThis.checkupRules = { nextWeekDates, list, to12h, pickSlot, findDay, targetEpoch, pickFromSchedule, pickOption, openTime };
})();
