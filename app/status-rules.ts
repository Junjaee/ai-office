// 자동화가 커밋한 상태 JSON을 화면 상태로 바꾸는 순수 규칙. React·fetch 없음.
export type RealStatus = {
  id: string;
  name: string;
  dept: string;
  ok: boolean;
  running?: boolean;
  updated_at: string;
  summary: string;
  counts?: Record<string, number>;
  next_run?: string;
  log?: string[];
  link?: string;
};

export type RealDeptStatus = "완료" | "진행 중" | "오류" | "대기";

/** 이 시간(시간 단위) 넘게 갱신이 없으면 "대기"로 본다 */
export const STALE_HOURS = 36;

export function deriveDeptStatus(s: RealStatus, now: Date = new Date()): RealDeptStatus {
  if (s.running) return "진행 중";
  if (!s.ok) return "오류";
  const updated = Date.parse(s.updated_at);
  if (Number.isNaN(updated) || now.getTime() - updated > STALE_HOURS * 3600 * 1000) return "대기";
  return "완료";
}

export type Summary = {
  total: number;
  ok: number;
  error: number;
  running: number;
  stale: number;
  opsStatus: RealDeptStatus;
  brief: string;
};

export function summarize(all: RealStatus[], now: Date = new Date()): Summary {
  const statuses = all.map((s) => deriveDeptStatus(s, now));
  const count = (k: RealDeptStatus) => statuses.filter((x) => x === k).length;
  const total = all.length;
  const error = count("오류");
  const running = count("진행 중");
  const ok = count("완료");
  const stale = count("대기");
  let opsStatus: RealDeptStatus = "대기";
  if (total > 0) opsStatus = error ? "오류" : running ? "진행 중" : ok ? "완료" : "대기";
  const brief =
    total === 0
      ? "연결된 자동화 없음 — 상태 파일이 올라오면 여기에 표시됩니다."
      : `실제 ${total}개 팀 중 ${ok}개 정상, ${error}개 오류, ${running}개 실행 중, ${stale}개 오래됨`;
  return { total, ok, error, running, stale, opsStatus, brief };
}
