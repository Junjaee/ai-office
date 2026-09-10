// 직원 = 자동화의 하위 작업. 사무실 설정(automations[].tasks[])에서 파생한다.
import type { AutomationDef } from "../workspaces/types";
import { agentId } from "./office-model.ts";

export type StaffSeed = {
  /** `${automationId}.${taskId}` */
  id: string;
  automationId: string;
  taskId: string;
  deptId: string;
  /** 직원 이름 = 업무명 */
  name: string;
  role: string;
  planned: boolean;
  hair: string;
  shirt: string;
  accent: string;
  skin: string;
};

const PALETTE: [string, string, string][] = [
  ["#6b3d34", "#dbeafe", "#3b82f6"],
  ["#2f2a3d", "#cbd5e1", "#bfdbfe"],
  ["#8a4a3c", "#bfdbfe", "#3b82f6"],
  ["#372b4a", "#f1f5f9", "#cbd5e1"],
  ["#c26e4b", "#3b82f6", "#e0f2fe"],
  ["#2d4b46", "#bfdbfe", "#bfdbfe"],
];
const SKIN = ["#ffdcc4", "#f7cdae", "#ffe3cf", "#eec39f"];

/** 자동화 목록 → 직원 목록 (설정 순서 유지) */
export function buildStaff(automations: AutomationDef[]): StaffSeed[] {
  const out: StaffSeed[] = [];
  let i = 0;
  for (const a of automations) {
    for (const t of a.tasks) {
      const colors = t.colors ?? PALETTE[i % PALETTE.length];
      out.push({
        id: agentId(a.id, t.id),
        automationId: a.id,
        taskId: t.id,
        deptId: a.dept,
        name: t.name,
        role: t.role,
        planned: Boolean(t.planned),
        hair: colors[0],
        shirt: colors[1],
        accent: colors[2],
        skin: SKIN[i % SKIN.length],
      });
      i += 1;
    }
  }
  return out;
}
