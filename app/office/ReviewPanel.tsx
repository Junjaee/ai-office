"use client";
// 주제 검토 칸 — 자동화가 올린 후보를 체크해 "만들기"를 누르면 24÷N 시간 간격으로 예약·게시된다.
import { useMemo, useState } from "react";
import { QUEUE_LABEL, busyIds, dueText, intervalText, useReview, type ReviewCandidate } from "../review";

type Props = {
  ws: string;
  automationId: string;
  title: string;
  /** 시작 버튼을 쓸 수 있는 상태(토큰 정상)인가 */
  canRun: boolean;
  /** 실행 요청 중인가 (카드의 busy 와 공유) */
  busy: boolean;
  /** 실행 요청: inputs 는 Worker 허용 목록(mode·picks) 안에서만 */
  onRun: (inputs: Record<string, string>) => Promise<boolean>;
};

export default function ReviewPanel({ ws, automationId, title, canRun, busy, onRun }: Props) {
  const review = useReview(ws, automationId, true);
  const [checked, setChecked] = useState<Set<string>>(() => new Set());
  const [showAll, setShowAll] = useState(false);
  const file = review.data;
  const taken = useMemo(() => busyIds(file), [file]);
  const candidates: ReviewCandidate[] = file?.candidates ?? [];
  const picked = candidates.filter((c) => checked.has(c.id) && !taken.has(c.id));
  const queue = (file?.queue ?? []).slice().sort((a, b) => Date.parse(a.due) - Date.parse(b.due));
  const activeQueue = queue.filter((q) => q.status === "queued" || q.status === "making");
  const doneQueue = queue.filter((q) => q.status === "done" || q.status === "failed" || q.status === "cancelled");

  const toggle = (id: string) =>
    setChecked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const make = async () => {
    if (!picked.length) return;
    const ok = await onRun({ mode: "queue", picks: picked.map((c) => c.id).join(",") });
    if (ok) {
      setChecked(new Set());
      window.setTimeout(() => review.refresh(), 4000);
    }
  };

  // 예약 항목별 취소·시각 변경 (워크플로 edit 방식 — 검토 파일만 고친다)
  const [times, setTimes] = useState<Record<string, string>>({});
  const edit = async (id: string, value: string) => {
    const ok = await onRun({ mode: "edit", edits: `${id}=${value}` });
    if (ok) window.setTimeout(() => review.refresh(), 25000);
  };

  return (
    <section className="review" aria-label={title}>
      <div className="review-head">
        <h4>
          📋 {title}
          {file?.date ? <small> · {file.date}</small> : null}
        </h4>
        {canRun ? (
          <button className="btn btn-ghost" onClick={() => void onRun({ mode: "topics" })} disabled={busy}>
            주제 다시 뽑기
          </button>
        ) : null}
      </div>

      {review.loading ? <p className="auto-meta">후보를 불러오는 중…</p> : null}
      {review.error ? <p className="auto-meta">후보를 못 불러왔어요. 잠시 뒤 새로 고쳐 주세요.</p> : null}
      {!review.loading && !review.error && !candidates.length ? (
        <p className="auto-meta">아직 뽑힌 후보가 없어요. 매일 06:30 에 후보가 올라오고, "주제 다시 뽑기"로 지금 뽑을 수도 있어요.</p>
      ) : null}

      {candidates.length ? (
        <ul className="review-list">
          {(showAll ? candidates : candidates.slice(0, 20)).map((c, i) => {
            const isTaken = taken.has(c.id);
            const q = queue.find((x) => x.id === c.id);
            return (
              <li key={c.id} className={`review-item ${isTaken ? "taken" : ""} ${checked.has(c.id) && !isTaken ? "on" : ""}`}>
                <label>
                  <input type="checkbox" checked={checked.has(c.id) && !isTaken} disabled={isTaken || !canRun} onChange={() => toggle(c.id)} />
                  <span className="review-no">{i + 1}</span>
                  <span className="review-body">
                    <b>
                      {c.title_ko || c.title}
                      {c.gap ? <span className="review-gap">🇺🇸 빈자리</span> : null}
                      {c.video ? <span className="review-gap review-video">🎬 영상</span> : null}
                    </b>
                    <small>
                      {c.title_ko ? `${c.title.slice(0, 60)}${c.title.length > 60 ? "…" : ""} · ` : ""}
                      {c.source}
                      {c.published ? ` · ${c.published.slice(5, 10).replace("-", "/")}` : ""}
                      {" · "}
                      <a href={c.link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                        원문 ↗
                      </a>
                      {q ? (
                        <>
                          {" · "}
                          <span className={`status-pill ${QUEUE_LABEL[q.status].cls}`}>{QUEUE_LABEL[q.status].text}</span>
                        </>
                      ) : null}
                    </small>
                    {c.reason ? <em>{c.reason}</em> : null}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}
      {candidates.length > 20 ? (
        <button className="btn btn-ghost" onClick={() => setShowAll(!showAll)}>
          {showAll ? "접기" : `후보 ${candidates.length - 20}개 더 보기`}
        </button>
      ) : null}

      {candidates.length && canRun ? (
        <div className="review-actions">
          <button className="btn btn-primary" onClick={() => void make()} disabled={!picked.length || busy}>
            {busy ? "요청 중…" : picked.length ? `선택 ${picked.length}개 만들기 · ${intervalText(picked.length)}` : "만들 주제를 골라 주세요"}
          </button>
          <small className="auto-meta">고른 개수만큼 24시간을 나눠 간격을 두고 자동 게시돼요. 첫 개는 바로 만들어요. 아무것도 안 고르면 07:30 에 1번이 자동으로 나가요.</small>
        </div>
      ) : null}

      {activeQueue.length || doneQueue.length ? (
        <div className="review-queue">
          <h5>예약·게시</h5>
          <ul>
            {[...activeQueue, ...doneQueue].map((q) => (
              <li key={`q-${q.id}`}>
                <span className={`status-pill ${QUEUE_LABEL[q.status].cls}`}>{QUEUE_LABEL[q.status].text}</span>
                <span className="review-due">{dueText(q.due)}</span>
                <span className="review-qtitle">{q.title}</span>
                {q.permalink ? (
                  <a href={q.permalink} target="_blank" rel="noreferrer">
                    게시물 ↗
                  </a>
                ) : null}
                {q.status === "failed" && q.error ? <small title={q.error}>{q.error.slice(0, 60)}</small> : null}
                {q.status === "queued" && canRun ? (
                  <span className="review-edit">
                    <input
                      type="time"
                      aria-label="게시 시각"
                      value={times[q.id] ?? ""}
                      disabled={busy}
                      onChange={(e) => setTimes((t) => ({ ...t, [q.id]: e.target.value }))}
                    />
                    <button className="btn btn-ghost" disabled={busy || !/^\d{2}:\d{2}$/.test(times[q.id] ?? "")} onClick={() => void edit(q.id, times[q.id])}>
                      시각 변경
                    </button>
                    <button className="btn btn-ghost" disabled={busy} onClick={() => void edit(q.id, "cancel")}>
                      취소
                    </button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
