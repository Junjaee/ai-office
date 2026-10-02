"use client";
// 단일 페이지 대시보드(2026-10-02 픽셀 사무실에서 전환):
// 머리글(사무실 탭) → 제목·전체 시작 → 배너 → 요약 5칸 → 자동화 카드 + 옆 패널(시간대별 실행·언제 실행되나) → 실행 이력(날짜별) → 토스트

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WORKSPACE } from "../../company.config";
import { WORKSPACE_LIST } from "../workspaces";
import { LABELS, STATE_CLASS, TRIGGER_LABEL, durationText, historyLabel, relativeTime, secondsText, type AutomationView, type TaskState } from "../status-rules";
import { useLiveStatus } from "../status";
import { useHistory } from "../history";
import { HISTORY_START, bucketsText, clampDate, dayStats, historyMessage, historyTitle, hourBuckets, runsTitle, shiftDate } from "../history-rules";
import ReviewPanel from "./ReviewPanel";

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
/** 이력 표에 처음 보이는 줄 수 (가계부처럼 하루 수백 번 도는 자동화가 있어 나머지는 "더 보기") */
const HISTORY_FIRST = 30;

// 상태는 색만으로 구분하지 않는다 — 아이콘 + 글자를 함께 쓴다 (24×24 선 아이콘의 path)
const ICONS = {
  running: "M8 5.5v13l10.5-6.5z",
  done: "M5 12.5l4.5 4.5L19 7.5",
  idle: "M9 6v12M15 6v12",
  error: "M12 4l9 16H3zM12 10v4M12 17.2v.3",
  planned: "M12 7v5l3 2M12 3a9 9 0 100 18 9 9 0 000-18",
  runs: "M4 19V9M10 19V5M16 19v-7M21 19H3",
  play: "M8 5.5v13l10.5-6.5z",
  pulse: "M3 12h4l3-7 4 14 3-7h4",
  prev: "M15 5l-7 7 7 7",
  next: "M9 5l7 7-7 7",
  info: "M12 11v6M12 7.5v.3M12 3a9 9 0 100 18 9 9 0 000-18",
} as const;
/** 상태 pill 의 CSS 이름(waiting·working·done·error·planned) → 아이콘 */
const CLASS_ICON: Record<string, keyof typeof ICONS> = { working: "running", done: "done", waiting: "idle", error: "error", planned: "planned" };

function Icon({ name, size = 14, fill = false }: { name: keyof typeof ICONS; size?: number; fill?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

function Pill({ cls, text }: { cls: string; text: string }) {
  const icon = CLASS_ICON[cls];
  return (
    <span className={`status-pill ${cls}`}>
      {icon ? <Icon name={icon} size={13} /> : null}
      {text}
    </span>
  );
}

export default function OfficeApp() {
  const live = useLiveStatus(ws);
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [histDate, setHistDate] = useState<string | null>(null); // null = 오늘
  const [histAll, setHistAll] = useState(false);
  const hist = useHistory(ws, histDate);
  const histItems = hist.data?.items ?? [];
  const isToday = hist.date === hist.today;
  const histMsg = historyMessage({
    loading: hist.loading,
    error: hist.error,
    source: hist.data?.source ?? null,
    partial: hist.data?.partial ?? false,
    count: histItems.length,
    isToday,
  });
  const hasHistory = !histMsg?.replacesTable;
  // 요약 칸의 실행 횟수: 이력을 실제로 받아 왔으면 0회도 숫자로 보인다(못 받아 왔을 때만 –)
  const statsReady = hist.data != null && hist.data.source !== "static" && !(hist.error && histItems.length === 0);
  const stats = useMemo(() => dayStats(histItems), [histItems]);
  const buckets = useMemo(() => hourBuckets(histItems), [histItems]);
  const bucketMax = Math.max(1, ...buckets);
  useEffect(() => setHistAll(false), [hist.date]);

  // 보이는 부서 = 숨기지 않았고 실제로 도는 자동화(워크플로 또는 이 PC)가 하나라도 있는 부서 (showPlanned 면 자동화만 있어도)
  const visibleDepts = useMemo(
    () =>
      ws.departments.filter((d) => {
        if (ws.hidden.includes(d.id)) return false;
        const autos = ws.automations.filter((a) => a.dept === d.id);
        if (!autos.length) return false;
        return ws.showPlanned ? true : autos.some((a) => a.workflow || a.local);
      }),
    [],
  );
  const visibleAutomations = useMemo(() => ws.automations.filter((a) => visibleDepts.some((d) => d.id === a.dept)), [visibleDepts]);

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

  /** 실행 요청. inputs(검토 칸의 mode·picks)는 Worker 허용 목록 안에서만 통과한다. 받아들여졌으면 true */
  const run = useCallback(
    async (target: string, inputs?: Record<string, string>): Promise<boolean> => {
      const requestId = newRequestId();
      setBusy((s) => new Set(s).add(target));
      const what = inputs?.mode === "queue" ? "만들기" : inputs?.mode === "topics" ? "주제 뽑기" : "시작";
      try {
        const r = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ws: ws.id, automation: target, requestId, ...(inputs ? { inputs } : {}) }),
        });
        if (r.status === 429) {
          showToast("오늘 실행 한도를 넘었어요");
          return false;
        }
        if (r.status === 502) {
          const data = (await r.json().catch(() => ({}))) as { error?: string };
          showToast(data.error === "github_auth" ? "실행 연결이 끊겼어요 · 설정을 다시 해야 해요" : "GitHub 응답이 없어요. 잠시 뒤 다시 눌러 주세요");
          return false;
        }
        if (!r.ok) {
          showToast(`실행 요청 실패 (HTTP ${r.status})`);
          return false;
        }
        const data = (await r.json()) as { results: RunResult[] };
        const accepted = data.results.filter((x) => x.accepted);
        const skipped = data.results.filter((x) => x.skipped);
        for (const a of accepted) live.markRequested(a.id, requestId);
        if (target === "all") {
          if (!accepted.length) showToast("이미 모두 실행 중이에요");
          else showToast(`${accepted.length}개 시작 요청${skipped.length ? `, ${skipped.length}개는 이미 실행 중` : ""}`);
        } else if (accepted.length) {
          showToast(`${nameOf(target)} ${what} 요청했어요`);
        } else if (skipped[0]?.skipped === "too_soon") {
          showToast("방금 요청했어요. 잠시 뒤 다시 눌러 주세요");
        } else {
          showToast("이미 실행 중이에요 · 끝나면 다시 눌러 주세요");
        }
        live.refresh();
        return accepted.length > 0;
      } catch {
        showToast("GitHub 응답이 없어요. 잠시 뒤 다시 눌러 주세요");
        return false;
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

  const toggleOpen = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const now = new Date();
  const canRun = live.canRun !== false;
  const scheduled = cardViews.filter((v) => v.nextRun);
  const chartNote = hasHistory ? bucketsText(buckets) : (histMsg?.text ?? "");
  const shownHist = histAll ? histItems : histItems.slice(0, HISTORY_FIRST);

  return (
    <main className="page-shell">
      <div className="wrap dash">
        <header className="dash-top">
          <div className="brand">
            {COMPANY.logoImage ? <img className="brand-logo" src={COMPANY.logoImage} alt="" /> : <span className="brand-mark">{COMPANY.logoLetter}</span>}
            <b>AI 오피스</b>
          </div>
          <nav className="ws-switch" aria-label="사무실 선택">
            {WORKSPACE_LIST.map((w) => (
              <a key={w.id} href={`/${w.id}`} className={w.id === ws.id ? "on" : ""} aria-current={w.id === ws.id ? "page" : undefined}>
                {w.label}
              </a>
            ))}
          </nav>
          <div className="checked">
            <i className={`check-dot ${live.checkedAt ? "on" : ""}`} aria-hidden="true" />
            {live.checkedAt ? `마지막 확인 ${live.checkedAt.toLocaleTimeString("ko-KR")}` : "상태 확인 중…"}
          </div>
        </header>

        {/* 전체 시작은 따라다니는 머리글(sticky)에 두지 않는다 — 스크롤하면 카드의 시작 단추 위에 겹쳐 개별 시작 대신 눌렸다(2026-09-10) */}
        <section className="dash-title">
          <div>
            <h1>{COMPANY.name}</h1>
            <p>{COMPANY.description}</p>
          </div>
          {runnable.length > 0 ? (
            canRun ? (
              <button className="btn btn-accent btn-run-all" onClick={() => run("all")} disabled={busy.has("all") || allRunning || !live.loaded}>
                <Icon name="play" size={15} fill />
                {busy.has("all") ? "요청 중…" : `전체 시작 · ${runnable.length}개`}
              </button>
            ) : (
              <Pill cls="error" text="실행 연결이 안 돼 있어요" />
            )
          ) : null}
        </section>

        {live.banners.length ? (
          <div className="banners">
            {live.banners.map((b) => (
              <div key={b.key} className={`banner ${b.level === "error" ? "red" : b.level === "warn" ? "yellow" : "gray"}`}>
                <Icon name={b.level === "info" ? "info" : "error"} size={16} />
                {b.href ? (
                  <a href={b.href} target="_blank" rel="noreferrer">
                    {b.text}
                  </a>
                ) : (
                  <span>{b.text}</span>
                )}
              </div>
            ))}
          </div>
        ) : null}

        <section className="kpi-grid" aria-label="요약">
          {SUMMARY_KEYS.map((k) => (
            <div key={k} className="kpi">
              <div className="kpi-label">
                <span className={`kpi-ico ${STATE_CLASS[k]}`}>
                  <Icon name={k} />
                </span>
                {LABELS[k]}
              </div>
              <div className="kpi-value">
                <strong>{live.loaded ? live.summary.counts[k] : "–"}</strong>
                <span>명</span>
              </div>
              <div className="kpi-sub" />
            </div>
          ))}
          {runnable.length > 0 ? (
            <div className="kpi">
              <div className="kpi-label">
                <span className="kpi-ico waiting">
                  <Icon name="runs" />
                </span>
                {runsTitle(hist.date, hist.today)}
              </div>
              <div className="kpi-value">
                <strong>{statsReady ? stats.runs.toLocaleString("ko-KR") : "–"}</strong>
                <span>회</span>
              </div>
              <div className="kpi-sub">
                {statsReady && stats.runs > 0
                  ? `성공 ${stats.ok.toLocaleString("ko-KR")} · 실패 ${stats.failed.toLocaleString("ko-KR")}${stats.avgSec != null ? ` · 평균 ${secondsText(stats.avgSec)}` : ""}`
                  : (histMsg?.text ?? "")}
              </div>
            </div>
          ) : null}
        </section>

        <div className="dash-main">
          <section className="dash-list" aria-label="자동화">
            <div className="section-head">
              <h2>자동화 {cardViews.length}개</h2>
              <span>{live.loaded ? live.summary.brief : "자동화 상태를 불러오는 중…"}</span>
            </div>
            {visibleDepts.length === 0 ? (
              <div className="empty-state">
                아직 연결된 자동화가 없어요.
                <br />
                <small>자동화가 생기면 이 자리에 카드가 생깁니다.</small>
              </div>
            ) : (
              <div className="auto-cards">
                {cardViews.map((v) => {
                  const def = visibleAutomations.find((a) => a.id === v.id)!;
                  const dept = ws.departments.find((d) => d.id === v.dept);
                  const isOpen = open.has(v.id) || v.state === "error";
                  const hasReview = Boolean(def.review && def.workflow);
                  const real = Boolean(def.workflow || def.local);
                  return (
                    <article key={v.id} className={`auto-card ${hasReview ? "wide" : ""}`} id={`auto-${v.id}`}>
                      <div className="auto-head">
                        <div className="auto-title">
                          <span className="auto-team">{dept?.name}</span>
                          <h3>{v.name}</h3>
                        </div>
                        <Pill cls={STATE_CLASS[v.state]} text={LABELS[v.state]} />
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
                          return (
                            <li key={t.id} id={`task-${v.id}.${t.id}`} className="task-row" title={t.role}>
                              <span className={`task-ico ${STATE_CLASS[state]}`}>
                                <Icon name={state} size={12} />
                              </span>
                              <b>{t.name}</b>
                              {ts?.note && (state === "done" || state === "error") ? <small>{ts.note}</small> : null}
                              <em className={STATE_CLASS[state]}>{LABELS[state]}</em>
                            </li>
                          );
                        })}
                      </ul>
                      {hasReview ? (
                        <ReviewPanel
                          ws={ws.id}
                          automationId={v.id}
                          title={def.review!.title ?? "검토"}
                          canRun={canRun}
                          busy={busy.has(v.id) || v.state === "running"}
                          onRun={(inputs) => run(v.id, inputs)}
                        />
                      ) : null}
                      {real ? (
                        <dl className="auto-facts">
                          <div>
                            <dt>마지막 실행</dt>
                            <dd>{v.lastRunAt ? relativeTime(v.lastRunAt, now) : "아직 실행한 적 없어요"}</dd>
                          </div>
                          {v.durationSec != null ? (
                            <div>
                              <dt>걸린 시간</dt>
                              <dd>{secondsText(v.durationSec)}</dd>
                            </div>
                          ) : null}
                          {v.trigger ? (
                            <div>
                              <dt>방식</dt>
                              <dd>{TRIGGER_LABEL[v.trigger]}</dd>
                            </div>
                          ) : null}
                          {v.nextRun ? (
                            <div>
                              <dt>다음 실행</dt>
                              <dd>{v.nextRun}</dd>
                            </div>
                          ) : null}
                          {v.counts?.total != null ? (
                            <div>
                              <dt>누적</dt>
                              <dd>{v.counts.total.toLocaleString("ko-KR")}건</dd>
                            </div>
                          ) : null}
                        </dl>
                      ) : null}
                      {isOpen ? (
                        <div className="auto-log">
                          {v.log?.length ? (
                            <ul>
                              {v.log.slice(0, 5).map((line, i) => (
                                <li key={i}>{line}</li>
                              ))}
                            </ul>
                          ) : null}
                          {v.runUrl ? (
                            <a href={v.runUrl} target="_blank" rel="noreferrer">
                              자세한 기록 보기 (GitHub 실행 페이지) ↗
                            </a>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="auto-actions">
                        {def.workflow && canRun ? (
                          <button className="btn btn-primary btn-run" onClick={() => run(v.id)} disabled={busy.has(v.id) || v.state === "running" || !live.loaded}>
                            <Icon name="play" size={13} fill />
                            {busy.has(v.id) ? "요청 중…" : def.review ? "주제 뽑기" : "시작"}
                          </button>
                        ) : null}
                        {def.live ? (
                          <a className="btn btn-dark" href={`/${ws.id}/live/${v.id}`}>
                            <Icon name="pulse" size={15} />
                            실시간 보기
                          </a>
                        ) : null}
                        {v.link ? (
                          <a className="btn btn-ghost" href={v.link} target="_blank" rel="noreferrer">
                            결과 폴더 열기 ↗
                          </a>
                        ) : null}
                        {v.log?.length || v.runUrl ? (
                          <button className="btn btn-ghost" onClick={() => toggleOpen(v.id)} aria-expanded={isOpen}>
                            {isOpen ? "접기" : "자세히"}
                          </button>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <aside className="dash-side">
            {runnable.length > 0 ? (
              <section className="panel">
                <div className="panel-head">
                  <h2>{isToday ? "오늘" : historyTitle(hist.date, hist.today).replace(" 실행 이력", "")} 시간대별 실행 횟수</h2>
                  <p>{chartNote || (isToday ? "오늘은 아직 실행한 게 없어요." : "이 날은 실행한 게 없어요.")}</p>
                </div>
                {hasHistory ? (
                  <>
                    <div className="hours" role="img" aria-label={`시간대별 실행 횟수. ${chartNote}`}>
                      {buckets.map((n, h) => (
                        <div key={h} className="hour" data-tip={`${String(h).padStart(2, "0")}시 · ${n.toLocaleString("ko-KR")}회`}>
                          {n > 0 && n === bucketMax && buckets.indexOf(n) === h ? <span>{n}</span> : null}
                          <i className={n ? "" : "zero"} style={{ height: n ? Math.max(4, Math.round((n / bucketMax) * 72)) : 2 }} />
                        </div>
                      ))}
                    </div>
                    <div className="hours-axis" aria-hidden="true">
                      <span>0시</span>
                      <span>6시</span>
                      <span>12시</span>
                      <span>18시</span>
                      <span>24시</span>
                    </div>
                  </>
                ) : null}
              </section>
            ) : null}
            {scheduled.length ? (
              <section className="panel">
                <div className="panel-head">
                  <h2>언제 실행되나</h2>
                </div>
                <ul className="sched">
                  {scheduled.map((v) => (
                    <li key={v.id}>
                      <b>{v.name}</b>
                      <span>{v.nextRun}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </aside>
        </div>

        {runnable.length > 0 ? (
          <section className="panel history" aria-label="실행 이력">
            <div className="history-head">
              <h2>{historyTitle(hist.date, hist.today)}</h2>
              <div className="history-nav">
                <button className="btn btn-ghost btn-icon" onClick={() => setHistDate(shiftDate(hist.date, -1))} disabled={hist.date <= HISTORY_START} aria-label="이전 날">
                  <Icon name="prev" size={16} />
                </button>
                <input
                  type="date"
                  value={hist.date}
                  min={HISTORY_START}
                  max={hist.today}
                  onChange={(e) => {
                    if (e.target.value) setHistDate(clampDate(e.target.value, HISTORY_START, hist.today));
                  }}
                  aria-label="날짜 고르기"
                />
                <button className="btn btn-ghost btn-icon" onClick={() => setHistDate(shiftDate(hist.date, 1))} disabled={hist.date >= hist.today} aria-label="다음 날">
                  <Icon name="next" size={16} />
                </button>
                <button className="btn btn-ghost" onClick={() => setHistDate(null)} disabled={isToday}>
                  오늘로
                </button>
              </div>
            </div>
            {histMsg ? <p className="auto-meta">{histMsg.text}</p> : null}
            {histMsg?.replacesTable ? null : (
              <>
                <div className="history-scroll">
                  <table className="history-table">
                    <thead>
                      <tr>
                        <th>시각</th>
                        <th>자동화</th>
                        <th>방식</th>
                        <th>상태</th>
                        <th>결과</th>
                        <th>소요</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {shownHist.map((h) => {
                        const label = historyLabel(h.status, h.conclusion);
                        const started = h.startedAt ? new Date(h.startedAt) : null;
                        return (
                          <tr key={h.id}>
                            <td className="num">{started ? started.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false }) : "–"}</td>
                            <td>
                              <b>{nameOf(h.automationId)}</b>
                            </td>
                            <td>{TRIGGER_LABEL[h.trigger]}</td>
                            <td>
                              <Pill cls={label.cls} text={label.text} />
                            </td>
                            <td className="history-summary" title={h.summary ?? undefined}>
                              {h.summary ?? "–"}
                            </td>
                            <td>{h.durationSec != null ? secondsText(h.durationSec) : durationText(h.startedAt, h.completedAt)}</td>
                            <td>
                              {h.url ? (
                                <a href={h.url} target="_blank" rel="noreferrer">
                                  기록 ↗
                                </a>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {histItems.length > HISTORY_FIRST ? (
                  <button className="btn btn-ghost history-more" onClick={() => setHistAll(!histAll)}>
                    {histAll ? "접기" : `${(histItems.length - HISTORY_FIRST).toLocaleString("ko-KR")}건 더 보기`}
                  </button>
                ) : null}
              </>
            )}
          </section>
        ) : null}

        <footer className="dash-foot">{COMPANY.name}</footer>
      </div>
      {toast ? (
        <div className="toast" role="status">
          {toast}
        </div>
      ) : null}
    </main>
  );
}
