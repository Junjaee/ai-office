// Worker 상수. 비밀값(GITHUB_TOKEN)은 여기 두지 않는다 — Cloudflare Secret / .dev.vars 에만.
export const OWNER = "Junjaee";
export const REPO = "ai-office";
export const REF = "main";

/** 사무실(ws)당 하루 실행 요청 상한 (accepted 된 dispatch 만 셈, KST 자정 초기화) */
export const DAILY_RUN_LIMIT = 50;
/** /api/status 응답의 메모리 캐시 시간 */
export const STATUS_CACHE_MS = 15_000;
/** 같은 자동화를 이 시간 안에 다시 dispatch 하면 skipped: "too_soon" */
export const TOO_SOON_MS = 60_000;
/** runs API 한 번에 받는 run 개수 */
export const RUNS_PER_PAGE = 30;

/** 실행 이력: 시작일(화면과 같은 값) · 캐시 · 날짜별 runs 조회 크기 */
export { HISTORY_START } from "../app/history-rules.ts";
export const HISTORY_TODAY_CACHE_MS = 30_000;
export const HISTORY_PAST_CACHE_MS = 600_000;
export const HISTORY_CACHE_MAX = 100;
export const HISTORY_RUNS_PER_PAGE = 100;
export const HISTORY_MAX_PAGES = 3;
