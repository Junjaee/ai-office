// 상태 → 위치·자세 번역 엔진. 각본·타이머·랜덤 행동 없음.
// 직원은 상태가 바뀔 때만 움직인다: 쉬는 중(라운지 소파) ↔ 책상. 오류는 책상 옆에 서 있다.
import type { TaskState } from "../status-rules";
import { needsWalk, placeFor, poseFor, type Anim, type Facing, type OfficeInput, type Place } from "./office-model";
import { findPath, nearestWalkable } from "./pathfinding";
import type { Pt, Room, World } from "./world";
import type { StaffSeed } from "./staff";

const WALK_SPEED = 3.6; // tiles / sec

export type Agent = {
  id: string;
  automationId: string;
  taskId: string;
  deptId: string;
  name: string;
  role: string;
  hair: string;
  shirt: string;
  accent: string;
  skin: string;
  x: number;
  y: number;
  facing: Facing;
  anim: Anim;
  state: TaskState;
  place: Place;
  /** 책상 좌석 / 책상 옆 (부서 방이 없으면 null → 항상 라운지) */
  seat: Pt | null;
  side: Pt | null;
  loungeSeat: Pt | null;
  path: Pt[];
  pathIdx: number;
};

export class OfficeEngine {
  readonly agents: Agent[] = [];
  readonly world: World;
  private hot: string | null = null;
  private loungeTaken = new Map<string, string>(); // "x,y" → agent id

  constructor(seeds: StaffSeed[], world: World) {
    this.world = world;
    const seatCursor = new Map<string, number>();
    for (const seed of seeds) {
      const room = world.deptRooms.find((r) => r.id === seed.deptId) ?? null;
      const n = seatCursor.get(seed.deptId) ?? 0;
      seatCursor.set(seed.deptId, n + 1);
      const desk = room?.desks[n] ?? null;
      this.agents.push({
        id: seed.id,
        automationId: seed.automationId,
        taskId: seed.taskId,
        deptId: seed.deptId,
        name: seed.name,
        role: seed.role,
        hair: seed.hair,
        shirt: seed.shirt,
        accent: seed.accent,
        skin: seed.skin,
        x: desk ? desk.seat.x : world.lounge.x + 2,
        y: desk ? desk.seat.y : world.lounge.y + 2,
        facing: "down",
        anim: "sit",
        state: seed.planned ? "planned" : "idle",
        place: "desk",
        seat: desk?.seat ?? null,
        side: desk?.side ?? null,
        loungeSeat: null,
        path: [],
        pathIdx: 0,
      });
    }
  }

  hotRoom(): string | null {
    return this.hot;
  }

  /** 첫 로드: 걷기 없이 상태에 맞는 자리에 즉시 놓는다 */
  place(input: OfficeInput): void {
    this.hot = input.hotRoom;
    for (const agent of this.agents) {
      const state = input.agents[agent.id] ?? agent.state;
      agent.state = state;
      agent.path = [];
      agent.pathIdx = 0;
      this.settle(agent, placeFor(state));
    }
  }

  /** 상태 변화 반영. 자리가 라운지↔책상으로 바뀌면 걷기 시작. 바뀐 게 있으면 true */
  apply(input: OfficeInput): boolean {
    let changed = this.hot !== input.hotRoom;
    this.hot = input.hotRoom;
    for (const agent of this.agents) {
      const next = input.agents[agent.id];
      if (!next || next === agent.state) continue;
      const prev = agent.state;
      agent.state = next;
      changed = true;
      const target = placeFor(next);
      if (needsWalk(prev, next) && agent.seat) {
        this.startWalk(agent, target);
      } else {
        this.settle(agent, target);
      }
    }
    return changed;
  }

  /** 걷는 직원만 전진. 아무도 안 걸으면 false */
  tick(dt: number): boolean {
    let moving = false;
    for (const agent of this.agents) {
      if (agent.pathIdx >= agent.path.length) continue;
      moving = true;
      this.stepWalk(agent, Math.min(dt, 0.05));
      if (agent.pathIdx >= agent.path.length) {
        agent.path = [];
        agent.pathIdx = 0;
        this.settle(agent, agent.place);
      }
    }
    return moving;
  }

  // ── 내부 ────────────────────────────────────────────────
  private destination(agent: Agent, place: Place): Pt {
    if (place === "lounge" || !agent.seat) return this.takeLoungeSeat(agent);
    this.releaseLoungeSeat(agent);
    if (place === "deskSide" && agent.side) return agent.side;
    return agent.seat;
  }

  private settle(agent: Agent, place: Place) {
    const dest = this.destination(agent, place);
    agent.place = place;
    agent.x = dest.x;
    agent.y = dest.y;
    agent.path = [];
    agent.pathIdx = 0;
    const pose = poseFor(agent.state);
    // 라운지 좌석이 모자라 서 있는 경우
    if (place === "lounge" && !agent.loungeSeat) {
      agent.anim = "idle";
      agent.facing = "down";
      return;
    }
    agent.anim = pose.anim;
    agent.facing = pose.facing;
  }

  private startWalk(agent: Agent, place: Place) {
    const dest = this.destination(agent, place);
    agent.place = place;
    const from = { x: Math.round(agent.x), y: Math.round(agent.y) };
    const path = findPath(from, nearestWalkable(this.world, dest), this.world);
    if (!path.length) {
      this.settle(agent, place);
      return;
    }
    // 마지막 칸은 좌석(가구 위일 수 있음) → 경로 끝에 목적지를 붙인다
    if (path[path.length - 1].x !== dest.x || path[path.length - 1].y !== dest.y) path.push(dest);
    agent.path = path;
    agent.pathIdx = 0;
    agent.anim = "walk";
  }

  private stepWalk(agent: Agent, dt: number) {
    const node = agent.path[agent.pathIdx];
    const dx = node.x - agent.x;
    const dy = node.y - agent.y;
    const dist = Math.hypot(dx, dy);
    if (Math.abs(dx) > Math.abs(dy)) agent.facing = dx > 0 ? "right" : "left";
    else agent.facing = dy > 0 ? "down" : "up";
    const step = WALK_SPEED * dt;
    agent.anim = "walk";
    if (dist <= step) {
      agent.x = node.x;
      agent.y = node.y;
      agent.pathIdx += 1;
    } else {
      agent.x += (dx / dist) * step;
      agent.y += (dy / dist) * step;
    }
  }

  private takeLoungeSeat(agent: Agent): Pt {
    if (agent.loungeSeat) return agent.loungeSeat;
    const lounge: Room = this.world.lounge;
    for (const seat of lounge.seats) {
      const key = `${seat.x},${seat.y}`;
      if (!this.loungeTaken.has(key)) {
        this.loungeTaken.set(key, agent.id);
        agent.loungeSeat = seat;
        return seat;
      }
    }
    // 좌석 부족: 라운지 안 빈 타일에 서서 대기
    const idx = this.agents.indexOf(agent);
    return { x: lounge.x + 2 + (idx % (lounge.w - 4)), y: lounge.y + lounge.h - 3 };
  }

  private releaseLoungeSeat(agent: Agent) {
    if (!agent.loungeSeat) return;
    this.loungeTaken.delete(`${agent.loungeSeat.x},${agent.loungeSeat.y}`);
    agent.loungeSeat = null;
  }
}
