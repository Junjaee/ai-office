// 화면(app/office/OfficeApp.tsx)이 읽는 "현재 사무실" 설정.
// 실제 내용은 app/workspaces/<id>.ts 에 있고, 사무실 선택은 WorkspaceLoader 가 이 모듈을 읽기 전에 정한다.
import { currentWorkspace } from "./app/workspaces";

export const WORKSPACE = currentWorkspace();
