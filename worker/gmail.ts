/** 지메일 새 메일 감시 (Worker 용, 가볍게 개수만 본다).
 *
 * 왜 Worker 가 보나: 상임위 메일을 "5분마다 무조건 실행"하면 빈 실행이 하루 288번 쌓이고,
 * 1분마다로 줄이면 1,440번이라 실행 이력이 도배된다. 그래서 **Worker 가 1분마다 지메일만 확인하고
 * 새 메일이 있을 때만** 워크플로를 깨운다 (사용자 결정 2026-09-17).
 *
 * 여기서는 넓은 검색어로 "국회에서 온, 아직 정리 안 된 메일"만 센다. 어느 위원회인지 가리는 것은
 * 파이썬(automations/mail/config.actions.yaml 의 committees)이 한다 — 규칙이 두 곳에서 갈라지지 않게.
 */

/** 라벨이 아직 안 붙은 국회 메일. 파이썬이 처리하면 라벨이 붙어 다음부터는 안 잡힌다. */
export const MAIL_WATCH_QUERY = 'from:assembly.go.kr -label:"재경위" -label:"예결위" newer_than:2d';

/** 실행이 이미 돌고 있는데 또 깨우지 않도록 쉬는 시간 */
export const MAIL_COOLDOWN_MS = 3 * 60 * 1000;

/** 카드 승인 문자(앱이 넣은 [카드SMS] 메일) 중 가계부가 아직 라벨을 안 붙인 것. 파이썬은 파싱 못 한 것에도 라벨을 붙인다. */
export const LEDGER_WATCH_QUERY = 'subject:"[카드SMS]" -label:카드동기화완료 newer_than:2d';

/** 카드 문자는 쇼핑 한 번에 여러 통 오므로 10분 안의 것은 한 번에 처리한다(실행 분 절약, 실패 반복도 하루 144회로 제한) */
export const LEDGER_COOLDOWN_MS = 10 * 60 * 1000;

/** 새 메일이 있고 쉬는 시간도 지났을 때만 깨운다 */
export function shouldWake(count: number, lastDispatchMs: number | null, nowMs: number,
                           cooldownMs: number): boolean {
  return count > 0 && coolEnough(lastDispatchMs, nowMs, cooldownMs);
}

export type GoogleCreds = { clientId: string; clientSecret: string; refreshToken: string };
export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** 구글 토큰 3개가 다 있으면 반환, 하나라도 없으면 null */
export function googleCreds(env: Record<string, unknown>): GoogleCreds | null {
  const clientId = String(env.GOOGLE_CLIENT_ID ?? "").trim();
  const clientSecret = String(env.GOOGLE_CLIENT_SECRET ?? "").trim();
  const refreshToken = String(env.GOOGLE_REFRESH_TOKEN ?? "").trim();
  if (!clientId || !clientSecret || !refreshToken) return null;
  return { clientId, clientSecret, refreshToken };
}

/** 새로 깨워도 되는 때인지 — 마지막으로 깨운 지 쉬는 시간이 지났나 */
export function coolEnough(lastDispatchMs: number | null, nowMs: number,
                           cooldownMs: number = MAIL_COOLDOWN_MS): boolean {
  return lastDispatchMs === null || nowMs - lastDispatchMs >= cooldownMs;
}

/** 지메일 응답에서 건수. 목록이 있으면 그 길이, 없으면 추정치(0 이면 없음) */
export function countMessages(body: unknown): number {
  const data = (body ?? {}) as { messages?: unknown[]; resultSizeEstimate?: number };
  if (Array.isArray(data.messages)) return data.messages.length;
  return Number(data.resultSizeEstimate ?? 0) || 0;
}

/** 액세스 토큰 캐시 — 같은 isolate 가 살아 있는 동안 다시 받지 않는다(만료 1분 전까지) */
let cached: { token: string; expiresAtMs: number } | null = null;

export function resetTokenCache(): void {
  cached = null;
}

/** 리프레시 토큰으로 액세스 토큰 받기. 값은 로그에 남기지 않는다. */
export async function accessToken(creds: GoogleCreds, fetchImpl: FetchLike, nowMs: number): Promise<string> {
  if (cached && cached.expiresAtMs > nowMs) return cached.token;
  const res = await fetchImpl("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: creds.clientId,
      client_secret: creds.clientSecret,
      refresh_token: creds.refreshToken,
      grant_type: "refresh_token",
    }).toString(),
  });
  if (!res.ok) throw new Error(`구글 토큰 갱신 실패 (HTTP ${res.status})`);
  const data = (await res.json()) as { access_token?: string; expires_in?: number };
  if (!data.access_token) throw new Error("구글 토큰 갱신 실패 (액세스 토큰 없음)");
  const ttl = Number(data.expires_in ?? 3600);
  cached = { token: data.access_token, expiresAtMs: nowMs + Math.max(60, ttl - 60) * 1000 };
  return cached.token;
}

/** 아직 정리되지 않은 국회 메일 수. 실패하면 예외를 던진다(부르는 쪽에서 로그만 남기고 넘어간다). */
export async function newMailCount(token: string, fetchImpl: FetchLike,
                                   query: string = MAIL_WATCH_QUERY): Promise<number> {
  const url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    + `?q=${encodeURIComponent(query)}&maxResults=5`;
  const res = await fetchImpl(url, { headers: { authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`지메일 확인 실패 (HTTP ${res.status})`);
  return countMessages(await res.json());
}
