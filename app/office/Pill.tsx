"use client";
// 상태 pill 과 선 아이콘 — 대시보드(OfficeApp)와 흐름 화면(FlowBoard)이 같은 모양을 쓴다.
// 상태는 색만으로 구분하지 않는다. 아이콘 + 글자를 함께, 그림 문자 대신 선 아이콘으로.

// 24×24 선 아이콘의 path
export const ICONS = {
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
  flow: "M4 6h7M4 12h11M4 18h7M17 9l3 3-3 3",
} as const;

export type IconName = keyof typeof ICONS;

/** 상태 pill 의 CSS 이름(waiting·working·done·error·planned) → 아이콘 */
const CLASS_ICON: Record<string, IconName> = { working: "running", done: "done", waiting: "idle", error: "error", planned: "planned" };

export function Icon({ name, size = 14, fill = false }: { name: IconName; size?: number; fill?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

export function Pill({ cls, text }: { cls: string; text: string }) {
  const icon = CLASS_ICON[cls];
  return (
    <span className={`status-pill ${cls}`}>
      {icon ? <Icon name={icon} size={13} /> : null}
      {text}
    </span>
  );
}
