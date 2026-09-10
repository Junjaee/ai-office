// 오피스 월드 맵 — 보이는 부서만 4열로 배치(행 수 가변), 라운지는 마지막 행 아래 고정.
// 타일 그리드 기반. 0 = 걸을 수 있음, 1 = 막힘(벽·가구)

export const TILE = 18;
export const COLS = 74;

export type Pt = { x: number; y: number };
export type RoomKind = "dept" | "lounge";

export type Desk = {
  /** 책상 상판 좌측 타일 */
  deskX: number;
  deskY: number;
  /** 앉는 자리(경로 목적지) */
  seat: Pt;
  /** 오류일 때 서 있는 자리(책상 옆) */
  side: Pt;
};

export type Room = {
  id: string;
  name: string;
  short: string;
  icon: string;
  kind: RoomKind;
  x: number;
  y: number;
  w: number;
  h: number;
  doors: Pt[];
  desks: Desk[];
  /** 라운지 소파 좌석 */
  seats: Pt[];
};

export type Prop = {
  kind: "desk" | "monitor" | "table" | "sofa" | "coffee" | "plant" | "shelf" | "screen" | "rug" | "cabinet" | "whiteboard";
  x: number;
  y: number;
  w: number;
  h: number;
  label?: string;
};

export type DeptMeta = { id: string; name: string; short: string; icon: string };

export type World = {
  cols: number;
  rows: number;
  worldW: number;
  worldH: number;
  deptRooms: Room[];
  lounge: Room;
  rooms: Room[];
  props: Prop[];
  grid: Uint8Array;
  walkable(x: number, y: number): boolean;
  roomOf(id: string): Room;
  /** 방 안쪽 문 앞 타일 */
  doorApproach(room: Room): Pt;
};

/** 부서 방 배치 — 4열, 행 간격 14 (방 높이 11 + 복도 3) */
const COL_X = [2, 20, 38, 56];
const ROW0_Y = 2;
const ROW_GAP = 14;
const DEPT_W = 15;
const DEPT_H = 11;
const LOUNGE_W = 20;
const LOUNGE_H = 12;
/** 부서당 좌석 6석 (2줄 × 3) */
export const SEATS_PER_DEPT = 6;

function deptRoom(meta: DeptMeta, index: number): Room {
  const x = COL_X[index % 4];
  const y = ROW0_Y + Math.floor(index / 4) * ROW_GAP;
  const desks: Desk[] = [];
  for (const dy of [3, 6]) {
    for (const dx of [3, 7, 11]) {
      desks.push({
        deskX: x + dx - 1,
        deskY: y + dy,
        seat: { x: x + dx, y: y + dy + 1 },
        side: { x: x + dx + 1, y: y + dy + 1 },
      });
    }
  }
  return {
    ...meta,
    kind: "dept",
    x,
    y,
    w: DEPT_W,
    h: DEPT_H,
    doors: [
      { x: x + 7, y },
      { x: x + 8, y },
    ],
    desks,
    seats: [],
  };
}

function loungeRoom(rowCount: number): Room {
  const x = 2;
  const y = ROW0_Y + rowCount * ROW_GAP;
  const seats: Pt[] = [];
  for (const sx of [4, 5, 6, 7, 8, 11, 12, 13, 14, 15]) seats.push({ x: x + sx, y: y + 4 });
  return {
    id: "lounge",
    name: "라운지",
    short: "lounge",
    icon: "☕",
    kind: "lounge",
    x,
    y,
    w: LOUNGE_W,
    h: LOUNGE_H,
    doors: [
      { x: x + 9, y },
      { x: x + 10, y },
    ],
    desks: [],
    seats,
  };
}

/** 보이는 부서 목록으로 월드를 만든다. 부서가 0개여도 라운지만 있는 월드가 나온다. */
export function createWorld(depts: DeptMeta[]): World {
  const deptRooms = depts.map((meta, i) => deptRoom(meta, i));
  const rowCount = Math.ceil(deptRooms.length / 4);
  const lounge = loungeRoom(rowCount);
  const rooms = [...deptRooms, lounge];
  const rows = lounge.y + LOUNGE_H + 2;
  // 쓰는 열만큼만 넓힌다 (부서 1개면 라운지 폭 기준). 4열이면 COLS 그대로.
  const usedCols = Math.min(4, Math.max(deptRooms.length, 0));
  const deptRight = usedCols > 0 ? COL_X[usedCols - 1] + DEPT_W + 2 : 0;
  const cols = Math.min(COLS, Math.max(lounge.x + LOUNGE_W + 2, deptRight));

  const props: Prop[] = [];
  for (const room of deptRooms) {
    for (const desk of room.desks) props.push({ kind: "desk", x: desk.deskX, y: desk.deskY, w: 3, h: 1 });
    props.push({ kind: "shelf", x: room.x + 1, y: room.y + 1, w: 3, h: 1 });
    props.push({ kind: "plant", x: room.x + 13, y: room.y + 1, w: 1, h: 1 });
    props.push({ kind: "cabinet", x: room.x + 12, y: room.y + 9, w: 2, h: 1 });
  }
  props.push({ kind: "sofa", x: lounge.x + 4, y: lounge.y + 3, w: 5, h: 1 });
  props.push({ kind: "sofa", x: lounge.x + 11, y: lounge.y + 3, w: 5, h: 1 });
  props.push({ kind: "table", x: lounge.x + 7, y: lounge.y + 7, w: 4, h: 2 });
  props.push({ kind: "coffee", x: lounge.x + 15, y: lounge.y + 8, w: 3, h: 1, label: "☕" });
  props.push({ kind: "plant", x: lounge.x + 1, y: lounge.y + 10, w: 1, h: 1 });
  props.push({ kind: "plant", x: lounge.x + 18, y: lounge.y + 1, w: 1, h: 1 });

  const grid = new Uint8Array(cols * rows);
  const block = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= cols || y >= rows) return;
    grid[y * cols + x] = 1;
  };
  for (let x = 0; x < cols; x += 1) {
    block(x, 0);
    block(x, rows - 1);
  }
  for (let y = 0; y < rows; y += 1) {
    block(0, y);
    block(cols - 1, y);
  }
  for (const room of rooms) {
    for (let x = room.x; x < room.x + room.w; x += 1) {
      block(x, room.y);
      block(x, room.y + room.h - 1);
    }
    for (let y = room.y; y < room.y + room.h; y += 1) {
      block(room.x, y);
      block(room.x + room.w - 1, y);
    }
  }
  for (const prop of props) {
    if (prop.kind === "rug") continue;
    for (let y = prop.y; y < prop.y + prop.h; y += 1) {
      for (let x = prop.x; x < prop.x + prop.w; x += 1) block(x, y);
    }
  }
  for (const room of rooms) {
    for (const door of room.doors) grid[door.y * cols + door.x] = 0;
  }

  const walkable = (x: number, y: number) => {
    if (x < 0 || y < 0 || x >= cols || y >= rows) return false;
    return grid[y * cols + x] === 0;
  };
  const roomOf = (id: string) => {
    const room = rooms.find((r) => r.id === id);
    if (!room) throw new Error(`unknown room: ${id}`);
    return room;
  };
  const doorApproach = (room: Room): Pt => {
    const door = room.doors[0];
    return door.y === room.y ? { x: door.x, y: door.y - 1 } : { x: door.x, y: door.y + 1 };
  };

  return { cols, rows, worldW: cols * TILE, worldH: rows * TILE, deptRooms, lounge, rooms, props, grid, walkable, roomOf, doorApproach };
}
