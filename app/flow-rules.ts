// 자동화가 "언제 어떻게 깨어나는지" 묶는 규칙(순수 함수만, import type 만 쓴다 — status-rules.ts 와 같은 제약).
// 흐름 화면(app/office/FlowBoard.tsx)이 쓰고, tests/flow-rules.test.mjs 가 node --test 로 직접 돌린다.
// 자료는 전부 사무실 설정(app/workspaces/<사무실>.ts)에서 나오므로 자동화를 더하면 그림도 저절로 늘어난다.
import type { AutomationDef } from "./workspaces/types";

export type WakeKind = "event" | "schedule" | "manual" | "local";

/** 화면에 보이는 순서 — 특이한 것(사건)부터 */
export const WAKE_ORDER: readonly WakeKind[] = ["event", "schedule", "manual", "local"];

export const WAKE_LABEL: Record<WakeKind, string> = {
  event: "일이 생기면",
  schedule: "정해진 시각에",
  manual: "사람이 시작할 때만",
  local: "이 PC 에서",
};

export const WAKE_NOTE: Record<WakeKind, string> = {
  event: "시계와 상관없이, 새 메일·일정 같은 일이 생겼을 때만 돈다",
  schedule: "Cloudflare 가 1분마다 확인해 그 시각이 되면 깨운다",
  manual: "사이트의 시작 단추를 누를 때만 돈다",
  local: "이 PC 프로그램이 스스로 돌면서 상태만 보내 온다",
};

/**
 * 깨우는 방식 하나로 정한다. 둘에 걸치면(가계부 = 6시간 예약 + 새 카드 문자) 사건이 이긴다 —
 * 예약은 어느 자동화에나 있지만 사건은 그 자동화만의 사정이라 설명할 거리가 더 많다.
 */
export function wakeOf(a: AutomationDef): WakeKind {
  if (a.local) return "local";
  if (a.wake) return "event";
  if (a.schedule) return "schedule";
  return "manual";
}

/** 자동화 이름 옆 한 줄: "새 카드 문자가 오면 · 6시간마다에도" */
export function wakeNote(a: AutomationDef): string {
  switch (wakeOf(a)) {
    case "event":
      return a.schedule ? `${a.wake} · ${a.schedule}에도` : (a.wake ?? "");
    case "manual":
      return "사이트에서 시작";
    default:
      return a.schedule ?? "";
  }
}

export type WakeGroup = { kind: WakeKind; items: AutomationDef[] };

/**
 * 깨우는 방식별로 묶는다. 빈 묶음은 빼므로 사무실마다 길이가 다르다.
 * 보여 줄 자동화만 넘기는 것은 부르는 쪽 몫 — 화면은 status-rules 의 isRealAutomation 으로 걸러서 준다.
 */
export function wakeGroups(automations: readonly AutomationDef[]): WakeGroup[] {
  return WAKE_ORDER.map((kind) => ({ kind, items: automations.filter((a) => wakeOf(a) === kind) })).filter((g) => g.items.length > 0);
}
