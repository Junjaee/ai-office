"use client";
// 자동화 흐름 한 장(/<사무실>/flow) — 무엇이 깨우는지로 묶고, 자동화마다 작업을 화살표로 이어 그린다.
// 그림은 사무실 설정(app/workspaces/<사무실>.ts)에서 그대로 읽는다. 자동화를 더하면 여기도 저절로 늘어난다.
// 작업 칸 색은 대시보드와 같은 상태(app/status.ts → status-rules.ts)라 지금 도는 것이 그대로 보인다.
import { useEffect, useMemo } from "react";
import { WAKE_LABEL, WAKE_NOTE, wakeGroups, wakeNote } from "../flow-rules";
import { LABELS, STATE_CLASS, isRealAutomation, type TaskState } from "../status-rules";
import { useLiveStatus } from "../status";
import { WORKSPACES } from "../workspaces";
import { Icon, Pill } from "./Pill";

export default function FlowBoard({ ws: wsId }: { ws: string }) {
  const ws = WORKSPACES[wsId];
  const COMPANY = ws.company;
  const live = useLiveStatus(ws);
  const groups = useMemo(() => wakeGroups(ws.automations.filter(isRealAutomation)), [ws]);
  useEffect(() => {
    document.documentElement.dataset.ws = wsId; // 사무실 대표 색(--accent)
  }, [wsId]);
  const viewById = useMemo(() => new Map(live.views.map((v) => [v.id, v] as const)), [live.views]);

  return (
    <main className="page-shell">
      <div className="wrap flow">
        <header className="dash-top">
          <div className="brand">
            <a className="brand-mark" href={`/${ws.id}`} aria-label="사무실로 돌아가기">
              <Icon name="flow" size={20} />
            </a>
            <b>AI 오피스 · 흐름</b>
          </div>
          <nav className="ws-switch" aria-label="화면">
            <a href={`/${ws.id}`}>대시보드</a>
            <a href={`/${ws.id}/flow`} className="on" aria-current="page">
              흐름
            </a>
          </nav>
          <div className="checked">
            <i className={`check-dot ${live.checkedAt ? "on" : ""}`} aria-hidden="true" />
            {live.checkedAt ? `마지막 확인 ${live.checkedAt.toLocaleTimeString("ko-KR")}` : "상태 확인 중…"}
          </div>
        </header>

        <section className="dash-title">
          <div>
            <h1>{COMPANY.name} 흐름</h1>
            <p>무엇이 자동화를 깨우고, 그 안에서 어떤 일이 차례로 일어나는지 보여 줍니다. 칸 색은 지금 상태입니다.</p>
          </div>
        </section>

        {groups.length === 0 ? (
          <div className="empty-state">
            아직 실제로 도는 자동화가 없어요.
            <br />
            <small>자동화가 생기면 이 자리에 흐름이 그려집니다.</small>
          </div>
        ) : (
          groups.map((g) => (
            <section className="panel flow-group" key={g.kind}>
              <div className="panel-head">
                <h2>{WAKE_LABEL[g.kind]}</h2>
                <p>{WAKE_NOTE[g.kind]}</p>
              </div>
              <div className="flow-rows">
                {g.items.map((a) => {
                  const v = viewById.get(a.id);
                  const note = wakeNote(a);
                  return (
                    <article className="flow-row" key={a.id}>
                      <div className="flow-head">
                        <b>{a.name}</b>
                        {note ? <span className="flow-when">{note}</span> : null}
                        {v ? <Pill cls={STATE_CLASS[v.state]} text={LABELS[v.state]} /> : null}
                      </div>
                      <ol className="flow-steps">
                        {a.tasks.map((t) => {
                          const state: TaskState = v?.tasks[t.id]?.state ?? (t.planned ? "planned" : "idle");
                          return (
                            <li className={`flow-step ${STATE_CLASS[state]}`} key={t.id} title={t.role}>
                              <b>{t.name}</b>
                              <span>{LABELS[state]}</span>
                            </li>
                          );
                        })}
                      </ol>
                    </article>
                  );
                })}
              </div>
            </section>
          ))
        )}

        <footer className="dash-foot">{COMPANY.name}</footer>
      </div>
    </main>
  );
}
