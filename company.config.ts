// 엔진(app/game/*)과 화면이 읽는 "현재 사무실" 설정.
// 실제 내용은 app/workspaces/<id>.ts 에 있고, 여기서는 현재 선택된 사무실 값을 그대로 내보낸다.
// 사무실 선택은 app/office/WorkspaceLoader.tsx 가 엔진을 불러오기 전에 정한다.
import { currentWorkspace } from "./app/workspaces";

const ws = currentWorkspace();

export type { StaffEntry } from "./app/workspaces/types";
export const COMPANY = ws.company;
export const CEO_PROFILE = ws.ceo;
export const DEPARTMENTS = ws.departments;
export const STAFF_LIST = ws.staff;
export const PENDING_INTEGRATIONS = ws.pending;
export const STORAGE_LINK = ws.storageLink;
export const HIDDEN_DEPARTMENTS = ws.hidden;
export const WORKSPACE = ws;
