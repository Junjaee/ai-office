"use client";
// 사무실 본문(2026-11-24, 사용자 결정): 위에는 조직도(팀 → 직원), 아래에는 업무 목록 + 고른 업무의 작업 기록.
// 직원이 주인공이다 — 직원 이름은 직업 이름(TaskDef.title), 업무명은 그 아래 설명으로 쓴다.
// 조직도는 팀 → 업무(자동화) → 직원 세 층이다. 팀을 누르면 목록이 그 팀 업무만, 업무 이름이나 직원을 누르면 그 업무가 펼쳐진다.
// 묶음 순서·기본 선택은 app/board-rules.ts, 깨어나는 때 문구는 app/flow-rules.ts.
import { useMemo, useState } from "react";
import { boardGroups, pickOnBoard, staffName } from "../board-rules";
import { wakeNote } from "../flow-rules";
import { LABELS, STATE_CLASS, TRIGGER_LABEL, relativeTime, secondsText, type AutomationView, type TaskState } from "../status-rules";
import type { AutomationDef, Department, TaskDef, WorkspaceConfig } from "../workspaces/types";
import { Icon, Pill } from "./Pill";
import ReviewPanel from "./ReviewPanel";

/** 팀마다 다른 얼굴 바탕색 (글자는 늘 짙은 색이라 어느 바탕에서도 읽힌다) */
const TONES = ["#dbe7ff", "#d9f2ee", "#fde9d2", "#e9e1fb", "#fbe0ea", "#e3efd3"];

type Props = {
  ws: WorkspaceConfig;
  /** 보이는 팀·업무 — OfficeApp 이 숨긴 부서와 준비 중인 부서를 걸러서 준다 */
  depts: Department[];
  automations: AutomationDef[];
  views: AutomationView[];
  loaded: boolean;
  canRun: boolean;
  busy: Set<string>;
  now: Date;
  run: (target: string, inputs?: Record<string, string>) => Promise<boolean>;
};

function Face({ task, tone, stacked = false }: { task: TaskDef; tone: string; stacked?: boolean }) {
  return (
    <span className={`st-av ${stacked ? "stacked" : ""}`} style={{ background: task.planned ? "var(--s-idle-bg)" : tone }} aria-hidden="true">
      {staffName(task).slice(0, 1)}
    </span>
  );
}

export default function StaffBoard({ ws, depts, automations, views, loaded, canRun, busy, now, run }: Props) {
  const [team, setTeam] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  const viewById = useMemo(() => new Map(views.map((v) => [v.id, v] as const)), [views]);
  const defById = useMemo(() => new Map(automations.map((a) => [a.id, a] as const)), [automations]);
  const toneOf = (deptId: string) => TONES[Math.max(0, depts.findIndex((d) => d.id === deptId)) % TONES.length];
  const stateOf = (a: AutomationDef, t: TaskDef): TaskState => viewById.get(a.id)?.tasks[t.id]?.state ?? (t.planned ? "planned" : "idle");

  const groups = useMemo(() => boardGroups(team ? views.filter((v) => v.dept === team) : views), [views, team]);
  const selId = pickOnBoard(groups, picked);
  const sel = selId ? viewById.get(selId) : undefined;
  const selDef = selId ? defById.get(selId) : undefined;

  if (depts.length === 0) {
    return (
      <div className="empty-state">
        아직 연결된 자동화가 없어요.
        <br />
        <small>자동화가 생기면 이 자리에 직원이 생깁니다.</small>
      </div>
    );
  }

  return (
    <>
      <section className="panel org" aria-label="조직도">
        <div className="org-root">
          <b>{ws.company.name}</b>
          <span>사람이 맡기고 결과를 확인해요</span>
        </div>
        <i className="org-stem" aria-hidden="true" />
        <i className="org-bar" aria-hidden="true" />
        <div className="org-teams">
          {depts.map((d) => {
            const autos = automations.filter((a) => a.dept === d.id);
            const count = autos.reduce((n, a) => n + a.tasks.length, 0);
            const on = team === d.id || (!team && sel?.dept === d.id);
            return (
              <div key={d.id} className={`org-team ${on ? "on" : ""}`}>
                <i className="org-stem" aria-hidden="true" />
                <button className="org-lead" onClick={() => setTeam(team === d.id ? null : d.id)} aria-pressed={team === d.id} title={team === d.id ? "모든 팀 업무 보기" : "이 팀 업무만 보기"}>
                  <b>{d.name}</b>
                  <small>{count}명</small>
                </button>
                {/* 팀 안에서도 업무(자동화)별로 나눈다 — 한 팀이 서로 다른 일 둘을 맡기도 한다(자료실 정리팀 = 수신함 정리 + 화성시 공고) */}
                {autos.map((a) => (
                  <div key={a.id} className={`org-crew ${a.id === selId ? "on" : ""}`}>
                    <button className="org-part" onClick={() => setPicked(a.id)} title="이 업무 펼쳐 보기">
                      {a.name}
                    </button>
                    {a.tasks.map((t) => {
                      const state = stateOf(a, t);
                      return (
                        <button key={t.id} className="org-m" onClick={() => setPicked(a.id)} title={`${t.name} — ${t.role}`}>
                          <Face task={t} tone={toneOf(d.id)} />
                          <b>{staffName(t)}</b>
                          <Pill cls={STATE_CLASS[state]} text={LABELS[state]} />
                        </button>
                      );
                    })}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </section>

      <div className="work">
        <section className="work-list" aria-label="업무 목록">
          <div className="work-head">
            <h2>업무 {groups.reduce((n, g) => n + g.items.length, 0)}개</h2>
            {team ? (
              <button className="btn btn-ghost" onClick={() => setTeam(null)}>
                모든 팀 보기
              </button>
            ) : (
              <span>{loaded ? "조직도에서 팀을 누르면 그 팀 업무만" : "상태를 불러오는 중…"}</span>
            )}
          </div>
          {groups.map((g) => (
            <div key={g.state}>
              <div className="work-grp">
                <Pill cls={STATE_CLASS[g.state]} text={LABELS[g.state]} />
                {g.items.length}
              </div>
              {g.items.map((v) => {
                const def = defById.get(v.id)!;
                const when = v.state === "running" ? "지금" : v.lastRunAt ? relativeTime(v.lastRunAt, now) : "";
                return (
                  <button key={v.id} className={`work-row ${v.id === selId ? "on" : ""}`} onClick={() => setPicked(v.id)} aria-current={v.id === selId ? "true" : undefined}>
                    <b>{v.name}</b>
                    <small>{[wakeNote(def), when].filter(Boolean).join(" · ")}</small>
                    <span className="work-faces">
                      {def.tasks.map((t) => (
                        <Face key={t.id} task={t} tone={toneOf(v.dept)} stacked />
                      ))}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </section>

        {sel && selDef ? (
          <section className="work-detail" aria-label="고른 업무" id={`auto-${sel.id}`}>
            <div className="work-title">
              <div>
                <span className="auto-team">{depts.find((d) => d.id === sel.dept)?.name}</span>
                <h2>{sel.name}</h2>
              </div>
              <div className="work-title-side">
                <Pill cls={STATE_CLASS[sel.state]} text={LABELS[sel.state]} />
                {selDef.workflow && canRun ? (
                  <button className="btn btn-primary btn-run" onClick={() => run(sel.id)} disabled={busy.has(sel.id) || sel.state === "running" || !loaded}>
                    <Icon name="play" size={13} fill />
                    {busy.has(sel.id) ? "요청 중…" : selDef.review ? "주제 뽑기" : "시작"}
                  </button>
                ) : null}
              </div>
            </div>
            {sel.sub ? <p className="auto-sub">{sel.sub}</p> : null}

            {selDef.workflow || selDef.local ? (
              <dl className="auto-facts work-facts">
                <div>
                  <dt>일하는 때</dt>
                  <dd>{wakeNote(selDef) || "이 PC 에서 늘"}</dd>
                </div>
                <div>
                  <dt>마지막 실행</dt>
                  <dd>{sel.lastRunAt ? relativeTime(sel.lastRunAt, now) : "아직 실행한 적 없어요"}</dd>
                </div>
                {sel.durationSec != null ? (
                  <div>
                    <dt>걸린 시간</dt>
                    <dd>{secondsText(sel.durationSec)}</dd>
                  </div>
                ) : null}
                {sel.trigger ? (
                  <div>
                    <dt>방식</dt>
                    <dd>{TRIGGER_LABEL[sel.trigger]}</dd>
                  </div>
                ) : null}
                {sel.nextRun ? (
                  <div>
                    <dt>다음 실행</dt>
                    <dd>{sel.nextRun}</dd>
                  </div>
                ) : null}
                {sel.counts?.total != null ? (
                  <div>
                    <dt>누적</dt>
                    <dd>{sel.counts.total.toLocaleString("ko-KR")}건</dd>
                  </div>
                ) : null}
              </dl>
            ) : null}

            {selDef.review && selDef.workflow ? (
              <ReviewPanel
                ws={ws.id}
                automationId={sel.id}
                title={selDef.review.title ?? "검토"}
                canRun={canRun}
                busy={busy.has(sel.id) || sel.state === "running"}
                onRun={(inputs) => run(sel.id, inputs)}
              />
            ) : null}

            <div>
              <h3 className="work-h3">작업 기록</h3>
              <ol className="steps">
                {selDef.tasks.map((t) => {
                  const ts = sel.tasks[t.id];
                  const state = stateOf(selDef, t);
                  return (
                    <li key={t.id} className={`step ${STATE_CLASS[state]}`} id={`task-${sel.id}.${t.id}`}>
                      <div className="step-who">
                        <Face task={t} tone={toneOf(sel.dept)} />
                        <b>{staffName(t)}</b>
                        <Pill cls={STATE_CLASS[state]} text={LABELS[state]} />
                      </div>
                      {ts?.note && (state === "done" || state === "error") ? <p className="step-note">{ts.note}</p> : null}
                      <p className="step-role">
                        {t.title ? `${t.name} — ` : ""}
                        {t.role}
                      </p>
                    </li>
                  );
                })}
                <li className="step end">
                  <b>
                    {sel.state === "running"
                      ? "지금 일하는 중이에요"
                      : sel.state === "error"
                        ? "오류로 멈췄어요"
                        : sel.state === "planned"
                          ? "아직 자동화하지 않은 업무예요"
                          : sel.lastRunAt
                            ? `일을 마쳤어요${sel.durationSec != null ? ` — ${secondsText(sel.durationSec)} 걸림` : ""}`
                            : "아직 일한 적이 없어요"}
                  </b>
                  {sel.lastRunAt && sel.state !== "running" ? <p className="step-role">{relativeTime(sel.lastRunAt, now)}</p> : null}
                </li>
              </ol>
            </div>

            {sel.log?.length ? (
              <div className="auto-log">
                <ul>
                  {sel.log.slice(0, 5).map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="auto-actions">
              {selDef.live ? (
                <a className="btn btn-dark" href={`/${ws.id}/live/${sel.id}`}>
                  <Icon name="pulse" size={15} />
                  실시간 보기
                </a>
              ) : null}
              {selDef.page ? (
                <a className="btn btn-dark" href={selDef.page.href}>
                  <Icon name="runs" size={15} />
                  {selDef.page.label}
                </a>
              ) : null}
              {sel.link ? (
                <a className="btn btn-ghost" href={sel.link} target="_blank" rel="noreferrer">
                  결과 폴더 열기 ↗
                </a>
              ) : null}
              {sel.runUrl ? (
                <a className="btn btn-ghost" href={sel.runUrl} target="_blank" rel="noreferrer">
                  자세한 기록 보기 ↗
                </a>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>
    </>
  );
}
