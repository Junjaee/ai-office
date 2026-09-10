"use client";
// 단일 페이지: 헤더(사무실 탭·전체 시작) → 배너 → 요약 4칸 → 픽셀 사무실 → 자동화 카드 → 토스트

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WORKSPACE } from "../../company.config";
import { WORKSPACE_LIST } from "../workspaces";
import { LABELS, STATE_CLASS, TRIGGER_LABEL, durationText, historyLabel, relativeTime, type AutomationView, type TaskState } from "../status-rules";
import { useLiveStatus } from "../status";
import OfficeWorld from "../game/OfficeWorld";
import { OfficeEngine, type Agent } from "../game/engine";
import { createWorld } from "../game/world";
import { buildStaff } from "../game/staff";
import { toOfficeInput } from "../game/office-model";

const ws = WORKSPACE;
const COMPANY = ws.company;

type RunResult = { id: string; accepted?: boolean; requestedAt?: string; skipped?: "already_running" | "too_soon" };

/** req-YYYYMMDDHHmmss-xxxx (Worker 의 parseRequestId 규칙과 맞춤) */
function newRequestId() {
  const t = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const stamp = `${t.getFullYear()}${p(t.getMonth() + 1)}${p(t.getDate())}${p(t.getHours())}${p(t.getMinutes())}${p(t.getSeconds())}`;
  return `req-${stamp}-${Math.random().toString(36).slice(2, 6)}`;
}

const SUMMARY_KEYS = ["running", "done", "idle", "error"] as const;

export default function OfficeApp() {
  const live = useLiveStatus(ws);
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [open, setOpen] = useState<Set<string>>(() => new Set());

  // 그리는 부서 = 숨기지 않았고 워크플로 있는 자동화가 하나라도 있는 부서 (showPlanned 면 자동화만 있어도)
  const visibleDepts = useMemo(
    () =>
      ws.departments.filter((d) => {
        if (ws.hidden.includes(d.id)) return false;
        const autos = ws.automations.filter((a) => a.dept === d.id);
        if (!autos.length) return false;
        return ws.showPlanned ? true : autos.some((a) => a.workflow);
      }),
    [],
  );
  const visibleAutomations = useMemo(() => ws.automations.filter((a) => visibleDepts.some((d) => d.id === a.dept)), [visibleDepts]);
  const world = useMemo(() => createWorld(visibleDepts.map((d) => ({ id: d.id, name: d.name, short: d.short, icon: d.icon }))), [visibleDepts]);
  const engine = useMemo(() => new OfficeEngine(buildStaff(visibleAutomations), world), [visibleAutomations, world]);
  const placed = useRef(false);

  // 판정 결과 → 엔진 (첫 결과는 즉시 배치, 이후에는 상태 변화만 걷기)
  useEffect(() => {
    if (!live.loaded) return;
    const input = toOfficeInput(live.views, visibleAutomations);
    if (!placed.current) {
      engine.place(input);
      placed.current = true;
    } else {
      engine.apply(input);
    }
  }, [live.views, live.loaded, engine, visibleAutomations]);

  const toastTimer = useRef(0);
  const showToast = useCallback((message: string) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 3000);
  }, []);

  const viewById = useMemo(() => new Map(live.views.map((v) => [v.id, v] as const)), [live.views]);
  const cardViews = useMemo(
    () => visibleAutomations.map((a) => viewById.get(a.id)).filter((v): v is AutomationView => Boolean(v)),
    [visibleAutomations, viewById],
  );
  const runnable = useMemo(() => visibleAutomations.filter((a) => a.workflow), [visibleAutomations]);
  const allRunning = runnable.length > 0 && runnable.every((a) => viewById.get(a.id)?.state === "running");
  const nameOf = (id: string) => ws.automations.find((a) => a.id === id)?.name ?? id;

  const run = useCallback(
    async (target: string) => {
      const requestId = newRequestId();
      setBusy((s) => new Set(s).add(target));
      try {
        const r = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ws: ws.id, automation: target, requestId }),
        });
        if (r.status === 429) {
          showToast("오늘 실행 한도를 넘었어요");
          return;
        }
        if (r.status === 502) {
          const data = (await r.json().catch(() => ({}))) as { error?: string };
          showToast(data.error === "github_auth" ? "실행 연결이 끊겼어요 · 설정을 다시 해야 해요" : "GitHub 응답이 없어요. 잠시 뒤 다시 눌러 주세요");
          return;
        }
        if (!r.ok) {
          showToast(`실행 요청 실패 (HTTP ${r.status})`);
          return;
        }
        const data = (await r.json()) as { results: RunResult[] };
        const accepted = data.results.filter((x) => x.accepted);
        const skipped = data.results.filter((x) => x.skipped);
        for (const a of accepted) live.markRequested(a.id, requestId);
        if (target === "all") {
          if (!accepted.length) showToast("이미 모두 실행 중이에요");
          else showToast(`${accepted.length}개 시작 요청${skipped.length ? `, ${skipped.length}개는 이미 실행 중` : ""}`);
        } else if (accepted.length) {
          showToast(`${nameOf(target)} 시작 요청했어요`);
        } else if (skipped[0]?.skipped === "too_soon") {
          showToast("방금 요청했어요. 잠시 뒤 다시 눌러 주세요");
        } else {
          showToast("이미 실행 중이에요");
        }
        live.refresh();
      } catch {
        showToast("GitHub 응답이 없어요. 잠시 뒤 다시 눌러 주세요");
      } finally {
        setBusy((s) => {
          const n = new Set(s);
          n.delete(target);
          return n;
        });
      }
    },
    [live, showToast],
  );

  // 직원을 누르면 카드의 해당 업무 줄로 이동
  const onSelect = useCallback((agent: Agent) => {
    setSelected(agent.id);
    document.getElementById(`task-${agent.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => setSelected(null), 3000);
  }, []);

  const toggleOpen = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const now = new Date();
  const canRun = live.canRun !== false;

  return (
    <main className="page-shell">
      <div className="wrap">
        <nav className="app-nav hub-header" aria-label="사무실">
          <div className="brand-chip">
            {COMPANY.logoImage ? <img className="brand-logo" src={COMPANY.logoImage} alt="" /> : <span>{COMPANY.logoLetter}</span>}
            <b>{COMPANY.name}</b>
          </div>
          <div className="ws-switch" aria-label="사무실 선택">
            {WORKSPACE_LIST.map((w) => (
              <a key={w.id} href={`/${w.id}`} className={w.id === ws.id ? "on" : ""}>
                {w.icon} {w.label}
              </a>
            ))}
          </div>
          <span className="checked">{live.checkedAt ? `마지막 확인 ${live.checkedAt.toLocaleTimeString("ko-KR")}` : "상태 확인 중…"}</span>
          {runnable.length > 0 && !canRun ? <span className="status-pill error">실행 연결이 안 돼 있어요</span> : null}
        </nav>

        {live.banners.map((b) => (
          <div key={b.key} className={`banner ${b.level === "error" ? "red" : b.level === "warn" ? "yellow" : "gray"}`}>
            <span aria-hidden="true">{b.level === "error" ? "🔴" : b.level === "warn" ? "🟡" : "⚪"}</span>
            {b.href ? (
              <a href={b.href} target="_blank" rel="noreferrer">
                {b.text}
              </a>
            ) : (
              <span>{b.text}</span>
            )}
          </div>
        ))}

        <section className="summary-grid" aria-label="요약">
          {SUMMARY_KEYS.map((k) => (
            <div key={k} className={`metric ${STATE_CLASS[k]}`}>
              <span>{LABELS[k]}</span>
              <strong>{live.loaded ? live.summary.counts[k] : "–"}</strong>
            </div>
          ))}
        </section>
        {/* 전체 시작은 따라다니는 머리글(sticky)에 두지 않는다 — 스크롤하면 카드의 ▶ 시작 위에 겹쳐 개별 시작 대신 눌렸다 */}
        <div className="summary-row">
          <p className="summary-sub">{live.loaded ? live.summary.brief : "자동화 상태를 불러오는 중…"}</p>
          {runnable.length > 0 && canRun ? (
            <button className="btn btn-ghost btn-run-all" onClick={() => run("all")} disabled={busy.has("all") || allRunning || !live.loaded}>
              {busy.has("all") ? "요청 중…" : `▶ 전체 시작 · ${runnable.length}개`}
            </button>
          ) : null}
        </div>

        <section className="office-block">
          {visibleDepts.length === 0 ? (
            <div className="empty-state">
              아직 연결된 자동화가 없어요.
              <br />
              <small>자동화가 생기면 이 자리에 사무실이 그려집니다.</small>
            </div>
          ) : (
            <>
              <OfficeWorld
                engine={engine}
                world={world}
                deptViews={live.deptViews}
                hotRoom={live.hotRoom}
                selectedId={selected}
                follow={follow}
                onSelect={onSelect}
              />
              <div className="auto-actions">
                <button className={`btn btn-ghost ${follow ? "on" : ""}`} onClick={() => setFollow(!follow)}>
                  🎥 일하는 방 따라가기 {follow ? "ON" : "OFF"}
                </button>
              </div>
            </>
          )}
        </section>

        <section className="auto-cards" aria-label="자동화">
          {cardViews.map((v) => {
            const def = visibleAutomations.find((a) => a.id === v.id)!;
            const dept = ws.departments.find((d) => d.id === v.dept);
            const isOpen = open.has(v.id) || v.state === "error";
            const cardSelected = selected?.startsWith(`${v.id}.`) ?? false;
            return (
              <article key={v.id} className={`auto-card ${cardSelected ? "highlight" : ""}`} id={`auto-${v.id}`}>
                <div className="auto-head">
                  <h3>
                    {dept?.icon} {v.name}
                  </h3>
                  <span className={`status-pill ${STATE_CLASS[v.state]}`}>{LABELS[v.state]}</span>
                  {def.workflow ? (
                    canRun ? (
                      <button className="btn btn-primary btn-run" onClick={() => run(v.id)} disabled={busy.has(v.id) || v.state === "running" || !live.loaded}>
                        {busy.has(v.id) ? "요청 중…" : "▶ 시작"}
                      </button>
                    ) : null
                  ) : null}
                </div>
                <p className="auto-sub">
                  {v.sub}
                  {v.state === "error" && v.runUrl ? (
                    <>
                      {" · "}
                      <a href={v.runUrl} target="_blank" rel="noreferrer">
                        자세한 기록 보기 ↗
                      </a>
                    </>
                  ) : null}
                </p>
                <ul className="task-list">
                  {def.tasks.map((t) => {
                    const ts = v.tasks[t.id];
                    const state: TaskState = ts?.state ?? "idle";
                    const rowId = `${v.id}.${t.id}`;
                    return (
                      <li key={t.id} id={`task-${rowId}`} className={`task-row ${selected === rowId ? "highlight" : ""}`} title={t.role}>
                        <span className={`status-dot ${state}`} />
                        <b>{t.name}</b>
                        <span className={`status-pill ${STATE_CLASS[state]}`}>{LABELS[state]}</span>
                        {ts?.note && (state === "done" || state === "error") ? <small>{ts.note}</small> : null}
                      </li>
                    );
                  })}
                </ul>
                <p className="auto-meta">
                  {v.lastRunAt ? `마지막 실행 ${relativeTime(v.lastRunAt, now)}` : "아직 실행한 적 없어요"}
                  {v.nextRun ? ` · 다음 실행 ${v.nextRun}` : ""}
                  {v.counts?.total != null ? ` · 누적 ${v.counts.total.toLocaleString("ko-KR")}건` : ""}
                </p>
                <div className="auto-actions">
                  {v.link ? (
                    <a className="btn btn-ghost" href={v.link} target="_blank" rel="noreferrer">
                      결과 폴더 열기 ↗
                    </a>
                  ) : null}
                  {v.log?.length || v.runUrl ? (
                    <button className="btn btn-ghost" onClick={() => toggleOpen(v.id)}>
                      {isOpen ? "접기 ▴" : "자세히 ▾"}
                    </button>
                  ) : null}
                </div>
                {isOpen ? (
                  <>
                    {v.log?.length ? (
                      <ul className="auto-log">
                        {v.log.slice(0, 5).map((line, i) => (
                          <li key={i}>{line}</li>
                        ))}
                      </ul>
                    ) : null}
                    {v.runUrl ? (
                      <p className="auto-meta">
                        <a href={v.runUrl} target="_blank" rel="noreferrer">
                          자세한 기록 보기 (GitHub 실행 페이지) ↗
                        </a>
                      </p>
                    ) : null}
                  </>
                ) : null}
              </article>
            );
          })}
        </section>

        {runnable.length > 0 ? (
          <section className="history" aria-label="오늘 실행 이력">
            <h3>오늘 실행 이력</h3>
            {!live.loaded ? (
              <p className="auto-meta">불러오는 중…</p>
            ) : live.source !== "github" ? (
              <p className="auto-meta">실행 이력은 GitHub 연결이 있을 때만 보여요.</p>
            ) : live.history.length === 0 ? (
              <p className="auto-meta">오늘은 아직 실행한 게 없어요.</p>
            ) : (
              <div className="history-scroll">
                <table className="history-table">
                  <thead>
                    <tr>
                      <th>시각</th>
                      <th>자동화</th>
                      <th>방식</th>
                      <th>상태</th>
                      <th>소요</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {live.history.map((h) => {
                      const label = historyLabel(h.status, h.conclusion);
                      const started = h.startedAt ? new Date(h.startedAt) : null;
                      return (
                        <tr key={h.id}>
                          <td>{started ? started.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "–"}</td>
                          <td>{nameOf(h.automationId)}</td>
                          <td>{TRIGGER_LABEL[h.trigger]}</td>
                          <td>
                            <span className={`status-pill ${label.cls}`}>{label.text}</span>
                          </td>
                          <td>{durationText(h.startedAt, h.completedAt)}</td>
                          <td>
                            <a href={h.url} target="_blank" rel="noreferrer">
                              기록 ↗
                            </a>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : null}

        <footer className="auto-meta">{COMPANY.description}</footer>
      </div>
      {toast ? (
        <div className="toast" role="status">
          {toast}
        </div>
      ) : null}
    </main>
  );
}
