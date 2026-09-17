/** 자동화 예약표와 cron 판정 (순수 함수).
 *
 * **예약은 Cloudflare 가 관리한다** (사용자 결정 2026-09-17). GitHub 의 `schedule` 은 부하가 높으면
 * 지연되거나 **버려진다**(공식 문서). 실제로 5분 예약이 4시간 43분 동안 1번만 돌았다.
 * 그래서 워크플로의 `schedule:` 을 모두 걷어내고, 여기 적은 시각에 Worker 가 workflow_dispatch 로 깨운다.
 *
 * cron 은 5필드(분 시 일 월 요일) **UTC**. 요일은 0~6(일=0, 7도 일).
 * 쓸 수 있는 표기: 전부(별표), 간격(별표-슬래시-숫자), 목록(쉼표), 범위(붙임표).
 */

export type ScheduledJob = {
  /** .github/workflows 의 파일 이름 */
  workflow: string;
  /** UTC cron. 여러 시각이면 항목을 나눈다 */
  cron: string;
  /** workflow_dispatch 로 넘길 값 (request_id 는 Worker 가 채운다) */
  inputs?: Record<string, string>;
  /** 사람이 읽을 설명 (KST 기준) */
  note: string;
};

/** 같은 분에 여러 항목이 맞으면 **앞의 것이 이긴다**(아래 인스타 06:30·11:30 처럼 겹치는 경우). */
export const SCHEDULES: ScheduledJob[] = [
  { workflow: "mail.yml", cron: "*/5 * * * *", note: "상임위 메일 — 5분마다" },
  { workflow: "news.yml", cron: "0 */3 * * *", note: "기사 수집 — 3시간마다(KST 00·03·06…)" },
  { workflow: "ledger.yml", cron: "0 */6 * * *", note: "가계부 — 6시간마다(KST 09·15·21·03)" },
  { workflow: "hscity.yml", cron: "0 23 * * *", note: "화성시 — KST 08:00" },
  { workflow: "hscity.yml", cron: "0 9 * * *", note: "화성시 — KST 18:00" },
  { workflow: "weekend.yml", cron: "0 8 * * 4", note: "주말 일정 — 목 KST 17:00" },
  // 인스타: 후보 뽑기가 먼저 온다 — 같은 분(06:30·11:30)에 게시 확인과 겹치면 후보 뽑기를 쓴다
  { workflow: "insta.yml", cron: "30 21 * * *", inputs: { account: "all", mode: "topics" },
    note: "인스타 후보 — KST 06:30" },
  { workflow: "insta.yml", cron: "30 2 * * *", inputs: { account: "all", mode: "topics" },
    note: "인스타 후보 — KST 11:30" },
  { workflow: "insta.yml", cron: "30 * * * *", inputs: { account: "all", mode: "publish" },
    note: "인스타 게시 확인 — 매시 30분" },
];

function matchesField(field: string, value: number, min: number, max: number): boolean {
  for (const part of field.split(",")) {
    const [spec, stepText] = part.split("/");
    const step = stepText ? Number(stepText) : 1;
    if (!Number.isInteger(step) || step < 1) continue;
    let from = min;
    let to = max;
    if (spec !== "*" && spec !== "") {
      const [a, b] = spec.split("-");
      from = Number(a);
      to = b === undefined ? (stepText ? max : Number(a)) : Number(b);
      if (!Number.isFinite(from) || !Number.isFinite(to)) continue;
    }
    if (value < from || value > to) continue;
    if ((value - from) % step === 0) return true;
  }
  return false;
}

/** UTC 기준으로 이 시각(분)에 해당하는 cron 인지. 형식이 틀리면 false. */
export function matchesCron(expr: string, date: Date): boolean {
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) return false;
  const dow = date.getUTCDay();
  return (
    matchesField(fields[0], date.getUTCMinutes(), 0, 59) &&
    matchesField(fields[1], date.getUTCHours(), 0, 23) &&
    matchesField(fields[2], date.getUTCDate(), 1, 31) &&
    matchesField(fields[3], date.getUTCMonth() + 1, 1, 12) &&
    (matchesField(fields[4], dow, 0, 6) || (dow === 0 && matchesField(fields[4], 7, 0, 7)))
  );
}

/** 이 시각에 깨울 것들. 같은 워크플로가 여러 번 맞으면 앞의 하나만 남긴다. */
export function dueJobs(jobs: ScheduledJob[], date: Date): ScheduledJob[] {
  const out: ScheduledJob[] = [];
  const seen = new Set<string>();
  for (const job of jobs) {
    if (seen.has(job.workflow) || !matchesCron(job.cron, date)) continue;
    seen.add(job.workflow);
    out.push(job);
  }
  return out;
}

/** 예약 실행의 요청 번호 — 같은 분에 두 번 깨워도 같은 값이라 화면에서 한 건으로 보인다. */
export function cronRequestId(date: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `cron-${date.getUTCFullYear()}${p(date.getUTCMonth() + 1)}${p(date.getUTCDate())}` +
    `${p(date.getUTCHours())}${p(date.getUTCMinutes())}`;
}
