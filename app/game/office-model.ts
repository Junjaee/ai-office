// 상태 → 사무실 표현(위치·자세) 번역표. 순수 모듈: 런타임 import 없음 (node --test 로 검증).
import type { AutomationView, TaskState } from "../status-rules";
import type { AutomationDef } from "../workspaces/types";

export type Anim = "idle" | "walk" | "type" | "sit";
export type Facing = "up" | "down" | "left" | "right";
/** 직원이 있어야 할 자리 */
export type Place = "lounge" | "desk" | "deskSide";

export type OfficeInput = {
  /** 직원 id(`${automationId}.${taskId}`) → 상태 */
  agents: Record<string, TaskState>;
  /** 카메라가 따라갈 방(첫 번째 일하는 중 부서) */
  hotRoom: string | null;
};

/** 상태별 자리: 쉬는 중은 라운지, 오류는 책상 옆, 나머지는 책상 */
export function placeFor(state: TaskState): Place {
  if (state === "idle") return "lounge";
  if (state === "error") return "deskSide";
  return "desk";
}

/** 상태별 자세 */
export function poseFor(state: TaskState): { anim: Anim; facing: Facing } {
  switch (state) {
    case "running":
      return { anim: "type", facing: "up" };
    case "done":
      return { anim: "sit", facing: "up" };
    case "error":
      return { anim: "idle", facing: "down" };
    case "planned":
      return { anim: "sit", facing: "up" };
    case "idle":
    default:
      return { anim: "sit", facing: "down" };
  }
}

/** 자리가 라운지↔책상 사이에서 바뀔 때만 걷는다. 책상↔책상 옆(오류)은 제자리 이동. */
export function needsWalk(prev: TaskState, next: TaskState): boolean {
  const a = placeFor(prev);
  const b = placeFor(next);
  if (a === b) return false;
  return a === "lounge" || b === "lounge";
}

export function agentId(automationId: string, taskId: string): string {
  return `${automationId}.${taskId}`;
}

/** 화면 판정 결과(AutomationView[])를 엔진 입력으로 바꾼다 */
export function toOfficeInput(views: AutomationView[], defs: AutomationDef[]): OfficeInput {
  const agents: Record<string, TaskState> = {};
  let hotRoom: string | null = null;
  for (const def of defs) {
    const view = views.find((v) => v.id === def.id);
    for (const task of def.tasks) {
      const fromView = view?.tasks?.[task.id]?.state;
      agents[agentId(def.id, task.id)] = task.planned ? "planned" : (fromView ?? view?.state ?? "idle");
    }
    if (!hotRoom && view && view.state === "running") hotRoom = def.dept;
  }
  return { agents, hotRoom };
}
