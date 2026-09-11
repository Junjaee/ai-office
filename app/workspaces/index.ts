// 사무실(워크스페이스) 목록과 현재 선택. 새 사무실을 추가하려면 파일을 만들고 WORKSPACES 에 넣는다.
import type { WorkspaceConfig } from "./types";
import { workspace as assembly } from "./assembly";
import { workspace as home } from "./home";
import { workspace as side } from "./side";

export const WORKSPACES: Record<string, WorkspaceConfig> = { assembly, home, side };
export const WORKSPACE_LIST: WorkspaceConfig[] = [assembly, home, side];
export const DEFAULT_WORKSPACE = "assembly";

export function isWorkspaceId(value: unknown): value is string {
  return typeof value === "string" && value in WORKSPACES;
}

/**
 * 현재 워크스페이스 id. 브라우저에서 WorkspaceLoader 가 엔진을 불러오기 전에
 * globalThis.__WORKSPACE__ 에 넣어 둔다. 서버나 값이 없으면 기본 사무실.
 */
export function currentWorkspaceId(): string {
  const value = (globalThis as { __WORKSPACE__?: unknown }).__WORKSPACE__;
  return isWorkspaceId(value) ? value : DEFAULT_WORKSPACE;
}

export function currentWorkspace(): WorkspaceConfig {
  return WORKSPACES[currentWorkspaceId()];
}
