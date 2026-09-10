// GitHub REST 클라이언트 (dispatch · runs · Contents). fetchImpl 을 주입할 수 있어 가짜 fetch 로 테스트한다.
import { OWNER, REF, REPO } from "./config.ts";

export type FetchImpl = (input: string, init?: RequestInit) => Promise<Response>;

/** GitHub 이 401/403 을 돌려줌 — 토큰 만료·권한 부족 */
export class GitHubAuthError extends Error {
  status: number;
  constructor(status: number, message = `GitHub auth failed (${status})`) {
    super(message);
    this.name = "GitHubAuthError";
    this.status = status;
  }
}

/** GitHub 5xx · 네트워크 오류 · 예상 밖 응답 */
export class GitHubUnavailableError extends Error {
  status: number | null;
  constructor(status: number | null, message = `GitHub unavailable (${status ?? "network"})`) {
    super(message);
    this.name = "GitHubUnavailableError";
    this.status = status;
  }
}

export type RunSummary = {
  id: number;
  path: string;
  status: string;
  conclusion: string | null;
  display_title: string;
  run_started_at: string | null;
  updated_at: string;
  html_url: string;
};

/** handleRun / handleStatus 가 의존하는 최소 인터페이스 (테스트에서는 가짜 객체) */
export type GitHubLike = {
  tokenExpiresAt: string | null;
  dispatch(workflowFile: string, inputs: Record<string, string>): Promise<void>;
  listRuns(perPage: number): Promise<RunSummary[]>;
  readStatusFile(ws: string, id: string): Promise<unknown | null>;
};

const API = "https://api.github.com";
const TOKEN_EXPIRATION_HEADER = "github-authentication-token-expiration";

export class GitHubClient implements GitHubLike {
  /** 마지막 응답의 `github-authentication-token-expiration` 헤더 (없으면 null) */
  tokenExpiresAt: string | null = null;
  #token: string;
  #fetch: FetchImpl;

  constructor(token: string, fetchImpl?: FetchImpl) {
    this.#token = token;
    this.#fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  }

  #headers(accept = "application/vnd.github+json"): Record<string, string> {
    return {
      Authorization: `Bearer ${this.#token}`,
      Accept: accept,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ai-office-worker",
    };
  }

  async #request(path: string, init: RequestInit & { accept?: string } = {}): Promise<Response> {
    const { accept, ...rest } = init;
    let res: Response;
    try {
      res = await this.#fetch(`${API}${path}`, { ...rest, headers: { ...this.#headers(accept), ...(rest.headers as Record<string, string> | undefined) } });
    } catch (error) {
      throw new GitHubUnavailableError(null, `GitHub fetch failed: ${String(error)}`);
    }
    const expires = res.headers.get(TOKEN_EXPIRATION_HEADER);
    if (expires) this.tokenExpiresAt = normalizeExpiration(expires);
    if (res.status === 401 || res.status === 403) throw new GitHubAuthError(res.status);
    if (res.status >= 500) throw new GitHubUnavailableError(res.status);
    return res;
  }

  /** POST /repos/{o}/{r}/actions/workflows/{file}/dispatches → 204 면 성공 */
  async dispatch(workflowFile: string, inputs: Record<string, string>): Promise<void> {
    const res = await this.#request(`/repos/${OWNER}/${REPO}/actions/workflows/${encodeURIComponent(workflowFile)}/dispatches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: REF, inputs }),
    });
    if (res.status !== 204) throw new GitHubUnavailableError(res.status, `dispatch returned ${res.status}`);
  }

  /** GET /repos/{o}/{r}/actions/runs?per_page=N → 화면에 필요한 필드만 추린다 */
  async listRuns(perPage: number): Promise<RunSummary[]> {
    const res = await this.#request(`/repos/${OWNER}/${REPO}/actions/runs?per_page=${perPage}`);
    if (!res.ok) throw new GitHubUnavailableError(res.status, `runs returned ${res.status}`);
    const data = (await res.json()) as { workflow_runs?: Array<Record<string, unknown>> };
    return (data.workflow_runs ?? []).map((r) => ({
      id: Number(r.id),
      path: String(r.path ?? ""),
      status: String(r.status ?? ""),
      conclusion: r.conclusion == null ? null : String(r.conclusion),
      display_title: String(r.display_title ?? r.name ?? ""),
      run_started_at: r.run_started_at == null ? null : String(r.run_started_at),
      updated_at: String(r.updated_at ?? ""),
      html_url: String(r.html_url ?? ""),
    }));
  }

  /** GET /repos/{o}/{r}/contents/public/status/{ws}/{id}.json?ref=main (raw) → JSON, 404 면 null */
  async readStatusFile(ws: string, id: string): Promise<unknown | null> {
    const res = await this.#request(
      `/repos/${OWNER}/${REPO}/contents/public/status/${encodeURIComponent(ws)}/${encodeURIComponent(id)}.json?ref=${REF}`,
      { accept: "application/vnd.github.raw+json" },
    );
    if (res.status === 404) return null;
    if (!res.ok) throw new GitHubUnavailableError(res.status, `contents returned ${res.status}`);
    try {
      return await res.json();
    } catch (error) {
      throw new GitHubUnavailableError(res.status, `contents JSON parse failed: ${String(error)}`);
    }
  }
}

/** 헤더 값은 "2027-09-01 00:00:00 UTC" 꼴 — ISO 로 바꿔 내보낸다 (파싱 못 하면 원문) */
function normalizeExpiration(raw: string): string {
  const iso = raw.trim().replace(" UTC", "Z").replace(" ", "T");
  const t = Date.parse(iso);
  return Number.isNaN(t) ? raw : new Date(t).toISOString();
}
