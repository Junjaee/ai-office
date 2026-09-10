"use client";
// 픽셀 사무실 렌더러. 방 색·직원 위치·자세는 엔진(engine.ts)과 판정 결과(deptViews)만 따른다.

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { LABELS, STATE_CLASS, type DeptView, type TaskState } from "../status-rules";
import type { Agent, OfficeEngine } from "./engine";
import { TILE, type World } from "./world";

const BADGE: Record<TaskState, string> = { idle: "·", running: "●", done: "✓", error: "!", planned: "…" };

type Props = {
  engine: OfficeEngine;
  world: World;
  deptViews: Record<string, DeptView>;
  hotRoom: string | null;
  selectedId: string | null;
  follow: boolean;
  onSelect: (agent: Agent) => void;
};

type Cam = { x: number; y: number; scale: number };

/** 직원 레이어는 한 번만 렌더하고 이후에는 rAF에서 DOM을 직접 갱신한다 */
const AgentLayer = memo(function AgentLayer({
  agents,
  register,
  onPick,
}: {
  agents: Agent[];
  register: (id: string, el: HTMLDivElement | null) => void;
  onPick: (agent: Agent) => void;
}) {
  return (
    <>
      {agents.map((agent) => (
        <div
          key={agent.id}
          ref={(el) => register(agent.id, el)}
          onPointerUp={() => onPick(agent)}
          title={`${agent.name} · ${LABELS[agent.state]}`}
          style={
            {
              "--hair": agent.hair,
              "--shirt": agent.shirt,
              "--accent": agent.accent,
              "--skin": agent.skin,
            } as React.CSSProperties
          }
        >
          <span className="ag-body">
            <i className="p-shadow" />
            <i className="p-leg l" />
            <i className="p-leg r" />
            <i className="p-torso" />
            <i className="p-arm l" />
            <i className="p-arm r" />
            <i className="p-head">
              <b className="p-eye l" />
              <b className="p-eye r" />
            </i>
            <i className="p-hair" />
          </span>
          <span className="ag-tag">
            {agent.name}
            <em className={`s-${agent.state}`}>{BADGE[agent.state]}</em>
          </span>
        </div>
      ))}
    </>
  );
});

const PropLayer = memo(function PropLayer({ world }: { world: World }) {
  return (
    <>
      {world.props.map((prop, i) => (
        <div
          key={i}
          className={`pr pr-${prop.kind}`}
          style={{ left: prop.x * TILE, top: prop.y * TILE, width: prop.w * TILE, height: prop.h * TILE }}
        >
          {prop.kind === "desk" ? <i className="pr-monitor" /> : null}
          {prop.label ? <span>{prop.label}</span> : null}
        </div>
      ))}
    </>
  );
});

export default function OfficeWorld({ engine, world, deptViews, hotRoom, selectedId, follow, onSelect }: Props) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const agentRefs = useRef(new Map<string, HTMLDivElement>());
  const camRef = useRef<Cam>({ x: world.worldW / 2, y: world.worldH / 2, scale: 0.5 });
  const targetRef = useRef<Cam>({ x: world.worldW / 2, y: world.worldH / 2, scale: 0.5 });
  const selectedRef = useRef<string | null>(selectedId);
  const dragRef = useRef({ on: false, px: 0, py: 0, moved: false });
  const [zoom, setZoom] = useState<"fit" | "close">("fit");

  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);

  const register = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) agentRefs.current.set(id, el);
    else agentRefs.current.delete(id);
  }, []);

  const onPick = useCallback(
    (agent: Agent) => {
      if (!dragRef.current.moved) onSelect(agent);
    },
    [onSelect],
  );

  // 카메라 목표: 전체 보기 또는 (자동 추적 시) 일하는 중인 방
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const compute = () => {
      const rect = viewport.getBoundingClientRect();
      const fit = Math.min(rect.width / world.worldW, rect.height / world.worldH);
      if (zoom === "fit") {
        targetRef.current = { x: world.worldW / 2, y: world.worldH / 2, scale: fit };
        return;
      }
      const scale = Math.max(fit * 1.9, 0.95);
      const room = hotRoom ? world.rooms.find((r) => r.id === hotRoom) : null;
      targetRef.current =
        follow && room
          ? { x: (room.x + room.w / 2) * TILE, y: (room.y + room.h / 2) * TILE, scale }
          : { ...targetRef.current, scale };
    };
    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [zoom, follow, hotRoom, world]);

  // 페인트 루프: 카메라 보간 + 걷는 직원 위치·자세
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const paint = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      engine.tick(dt);
      const viewport = viewportRef.current;
      const stage = stageRef.current;
      if (viewport && stage) {
        const cam = camRef.current;
        const target = targetRef.current;
        cam.x += (target.x - cam.x) * 0.07;
        cam.y += (target.y - cam.y) * 0.07;
        cam.scale += (target.scale - cam.scale) * 0.08;
        const rect = viewport.getBoundingClientRect();
        const ox = rect.width / 2 - cam.x * cam.scale;
        const oy = rect.height / 2 - cam.y * cam.scale;
        stage.style.transform = `translate3d(${ox}px, ${oy}px, 0) scale(${cam.scale})`;
        if (stage.classList.contains("compact") !== cam.scale < 0.62) {
          stage.classList.toggle("compact", cam.scale < 0.62);
        }
        const picked = selectedRef.current;
        for (const agent of engine.agents) {
          const el = agentRefs.current.get(agent.id);
          if (!el) continue;
          el.style.transform = `translate3d(${(agent.x + 0.5) * TILE}px, ${(agent.y + 0.9) * TILE}px, 0)`;
          el.style.zIndex = String(200 + Math.round(agent.y));
          const cls = `ag f-${agent.facing} a-${agent.anim} s-${agent.state}` + (agent.id === picked ? " selected" : "");
          if (el.className !== cls) el.className = cls;
          const tag = el.lastElementChild as HTMLElement | null;
          const badge = tag?.lastElementChild as HTMLElement | null;
          if (badge && badge.textContent !== BADGE[agent.state]) {
            badge.textContent = BADGE[agent.state];
            badge.className = `s-${agent.state}`;
          }
        }
      }
      raf = requestAnimationFrame(paint);
    };
    raf = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(raf);
  }, [engine]);

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest(".world-hud")) return;
    dragRef.current = { on: true, px: e.clientX, py: e.clientY, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag.on) return;
    const dx = e.clientX - drag.px;
    const dy = e.clientY - drag.py;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    drag.px = e.clientX;
    drag.py = e.clientY;
    const scale = camRef.current.scale || 1;
    targetRef.current = {
      ...targetRef.current,
      x: clamp(targetRef.current.x - dx / scale, 0, world.worldW),
      y: clamp(targetRef.current.y - dy / scale, 0, world.worldH),
    };
  };
  const onPointerUp = () => {
    dragRef.current.on = false;
    window.setTimeout(() => {
      dragRef.current.moved = false;
    }, 0);
  };

  return (
    <div className="world-frame">
      <div
        className="world-viewport"
        ref={viewportRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div className="world-stage" ref={stageRef} style={{ width: world.worldW, height: world.worldH }}>
          <div className="world-floor" />

          {world.rooms.map((room) => {
            const view = room.kind === "dept" ? deptViews[room.id] : undefined;
            const state = view && view.state !== "none" ? view.state : null;
            return (
              <div
                key={room.id}
                className={`rm rm-${room.kind} ${state ? STATE_CLASS[state] : ""} ${hotRoom === room.id ? "hot" : ""}`}
                style={{ left: room.x * TILE, top: room.y * TILE, width: room.w * TILE, height: room.h * TILE }}
              >
                <span className="rm-head">
                  <b>
                    {room.icon} {room.name}
                  </b>
                  {state ? (
                    <i className={`rm-dot ${STATE_CLASS[state]}`} title={LABELS[state]}>
                      {view && view.runningCount > 0 ? ` ${LABELS.running} ${view.runningCount}` : ""}
                    </i>
                  ) : null}
                </span>
                <span className="rm-code">{room.short}</span>
                {room.doors.map((door) => (
                  <span
                    key={`${door.x}-${door.y}`}
                    className="rm-door"
                    style={{ left: (door.x - room.x) * TILE, top: (door.y - room.y) * TILE }}
                  />
                ))}
              </div>
            );
          })}

          <PropLayer world={world} />
          <AgentLayer agents={engine.agents} register={register} onPick={onPick} />
        </div>

        <div className="world-hud">
          <button className={zoom === "fit" ? "on" : ""} onClick={() => setZoom("fit")}>
            🗺️ 전체 보기
          </button>
          <button className={zoom === "close" ? "on" : ""} onClick={() => setZoom("close")}>
            🔍 가까이
          </button>
        </div>
        <div className="world-hint">드래그로 둘러보기 · 직원을 누르면 아래 카드로 이동</div>
      </div>
    </div>
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
