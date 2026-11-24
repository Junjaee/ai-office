// 사무실 화면(조직도 + 업무 목록)의 순수 규칙. import type 만 쓴다 — status-rules.ts 와 같은 제약.
// 화면은 app/office/StaffBoard.tsx, 시험은 tests/board-rules.test.mjs (node --test 가 직접 실행).
import type { AutomationView, TaskState } from "./status-rules";
import type { TaskDef } from "./workspaces/types";

/** 직원 이름 — 직업 이름(title)을 쓰고, 아직 안 지은 직원은 업무명으로 보인다 */
export function staffName(t: Pick<TaskDef, "name" | "title">): string {
  return t.title ?? t.name;
}

/** 업무 목록의 묶음 순서 — 지금 봐야 할 것(일하는 중·오류)이 위로 */
export const BOARD_ORDER: readonly TaskState[] = ["running", "error", "done", "idle", "planned"];

export type BoardGroup = { state: TaskState; items: AutomationView[] };

/** 업무(자동화)를 상태별로 묶는다. 빈 묶음은 빼고, 묶음 안 순서는 받은 순서(사무실 설정 순서) 그대로 */
export function boardGroups(views: readonly AutomationView[]): BoardGroup[] {
  return BOARD_ORDER.map((state) => ({ state, items: views.filter((v) => v.state === state) })).filter((g) => g.items.length > 0);
}

/**
 * 오른쪽에 펼쳐 보일 업무. 고른 것이 목록에 있으면 그것, 없으면(처음 열었거나 팀을 바꿔 사라졌으면) 맨 위 것.
 * 맨 위는 BOARD_ORDER 덕에 일하는 중 → 오류 순이라, 처음 열면 지금 봐야 할 업무가 펼쳐진다.
 */
export function pickOnBoard(groups: readonly BoardGroup[], picked: string | null): string | null {
  const all = groups.flatMap((g) => g.items);
  if (picked && all.some((v) => v.id === picked)) return picked;
  return all[0]?.id ?? null;
}
