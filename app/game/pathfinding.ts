// A* 경로 탐색 (4방향) — 오피스 타일 그리드 전용
import type { Pt } from "./world";

export type Walkable = { cols: number; rows: number; walkable(x: number, y: number): boolean };

const DIRS = [
  [0, -1],
  [1, 0],
  [0, 1],
  [-1, 0],
] as const;

/** 이진 힙 대신 작은 맵에서 충분히 빠른 정렬 삽입 큐 */
class Queue {
  private items: { idx: number; f: number }[] = [];

  push(idx: number, f: number) {
    let lo = 0;
    let hi = this.items.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.items[mid].f > f) lo = mid + 1;
      else hi = mid;
    }
    this.items.splice(lo, 0, { idx, f });
  }

  pop(): number | undefined {
    return this.items.pop()?.idx;
  }

  get size() {
    return this.items.length;
  }
}

/** 목적지가 막혀 있으면 가장 가까운 걸을 수 있는 타일로 바꾼다 */
export function nearestWalkable(world: Walkable, p: Pt): Pt {
  if (world.walkable(p.x, p.y)) return p;
  for (let r = 1; r <= 4; r += 1) {
    for (let dy = -r; dy <= r; dy += 1) {
      for (let dx = -r; dx <= r; dx += 1) {
        const q = { x: p.x + dx, y: p.y + dy };
        if (world.walkable(q.x, q.y)) return q;
      }
    }
  }
  return p;
}

/** from → to 경로(from 제외, to 포함). 경로가 없으면 빈 배열. */
export function findPath(from: Pt, to: Pt, world: Walkable, blocked?: Set<number>): Pt[] {
  const { cols, rows } = world;
  const start = from.y * cols + from.x;
  const goal = to.y * cols + to.x;
  if (start === goal) return [];
  if (!world.walkable(to.x, to.y)) return [];

  const gScore = new Float32Array(cols * rows).fill(Infinity);
  const cameFrom = new Int32Array(cols * rows).fill(-1);
  const closed = new Uint8Array(cols * rows);
  const h = (idx: number) => Math.abs((idx % cols) - to.x) + Math.abs(Math.floor(idx / cols) - to.y);

  const open = new Queue();
  gScore[start] = 0;
  open.push(start, h(start));

  while (open.size) {
    const current = open.pop();
    if (current === undefined) break;
    if (current === goal) {
      const path: Pt[] = [];
      let idx = goal;
      while (idx !== start) {
        path.push({ x: idx % cols, y: Math.floor(idx / cols) });
        idx = cameFrom[idx];
      }
      return path.reverse();
    }
    if (closed[current]) continue;
    closed[current] = 1;
    const cx = current % cols;
    const cy = Math.floor(current / cols);
    for (const [dx, dy] of DIRS) {
      const nx = cx + dx;
      const ny = cy + dy;
      if (!world.walkable(nx, ny)) continue;
      const next = ny * cols + nx;
      if (closed[next]) continue;
      if (blocked && next !== goal && blocked.has(next)) continue;
      const tentative = gScore[current] + 1;
      if (tentative < gScore[next]) {
        gScore[next] = tentative;
        cameFrom[next] = current;
        open.push(next, tentative + h(next));
      }
    }
  }
  return [];
}
