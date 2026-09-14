// 부업 사무실 설정. 부서 id 12개는 엔진이 참조하므로 바꾸지 말 것 (이름·아이콘·업무는 자유).
// 팀 = 플랫폼, 자동화 = 계정 (사용자 결정 2026-09-11). 계정별 자동화 id 는 `insta_<계정>` 처럼 짓는다.
import type { AutomationDef, CompanyInfo, Department, WorkspaceConfig } from "./types";

/** 기본 정보 */
export const COMPANY: CompanyInfo = {
  name: "부업 AI 스튜디오",
  logoLetter: "부",
  /** 헤더 로고 이미지 (public/ 기준 경로). 비우면 logoLetter 사용 */
  logoImage: "",
  titlePrefix: "부업",
  titleAccent: "AI Studio",
  pageTitle: "부업 AI 스튜디오 — 콘텐츠 자동화 현황",
  description: "인스타그램 게시글·릴스, 유튜브 쇼츠, 네이버 블로그까지 계정별 콘텐츠 자동화가 돌아가는 픽셀 스튜디오",
  windowLabel: "side_studio.exe — 편집실",
  reportName: "부업 AI 스튜디오",
};

/**
 * 부서 12개. id = 고정(엔진용) / name·short·icon = 자유롭게 변경.
 * 앞 4칸이 플랫폼별 팀. 한 팀에 직원(하위 작업) 6명까지 — 계정당 2명이면 팀당 계정 3개, 넘으면 같은 플랫폼 2팀을 연다.
 */
export const DEPARTMENTS: readonly Department[] = [
  {
    id: "research",
    name: "인스타 게시글팀",
    short: "insta.post",
    icon: "📸",
    task: "주제 정리 → 글·이미지 제작 → 업로드",
    report: "계정별로 정해진 주제에 맞춰 게시글을 만들어 올립니다.",
  },
  {
    id: "brand",
    name: "인스타 게시글 3팀",
    short: "insta.reels",
    icon: "🎞️",
    task: "대본 → 영상 제작 → 업로드",
    report: "짧은 세로 영상을 만들어 계정에 올립니다.",
  },
  {
    id: "strategy1",
    name: "쇼츠팀",
    short: "yt.shorts",
    icon: "📱",
    task: "대본 → 영상 제작 → 업로드",
    report: "유튜브 쇼츠를 만들어 채널에 올립니다.",
  },
  {
    id: "qa",
    name: "블로그팀",
    short: "naver.blog",
    icon: "✍️",
    task: "주제 정리 → 글 작성 → 발행",
    report: "네이버 블로그 글을 써서 발행합니다.",
  },
  {
    id: "strategy2",
    name: "인스타 게시글 2팀",
    short: "insta.post2",
    icon: "📸",
    task: "계정이 3개를 넘으면 여는 팀",
    report: "(예비) 인스타 게시글 계정이 늘면 사용합니다.",
  },
  {
    id: "reels",
    name: "릴스 2팀",
    short: "insta.reels2",
    icon: "🎞️",
    task: "계정이 3개를 넘으면 여는 팀",
    report: "(예비) 릴스 계정이 늘면 사용합니다.",
  },
  {
    id: "carousel",
    name: "쇼츠 2팀",
    short: "yt.shorts2",
    icon: "📱",
    task: "계정이 3개를 넘으면 여는 팀",
    report: "(예비) 쇼츠 채널이 늘면 사용합니다.",
  },
  {
    id: "partner",
    name: "블로그 2팀",
    short: "naver.blog2",
    icon: "✍️",
    task: "계정이 3개를 넘으면 여는 팀",
    report: "(예비) 블로그 계정이 늘면 사용합니다.",
  },
  {
    id: "finance",
    name: "수익 정산팀",
    short: "revenue.xls",
    icon: "💰",
    task: "플랫폼별 수익 정리",
    report: "(예비) 수익 자동화가 붙으면 사용합니다.",
  },
  {
    id: "review",
    name: "성과 분석팀",
    short: "insight.log",
    icon: "📊",
    task: "조회수·팔로워 추이",
    report: "(예비) 통계 자동화가 붙으면 사용합니다.",
  },
  {
    id: "ops",
    name: "자동화 운영팀",
    short: "automation.ops",
    icon: "⚙️",
    task: "실행 성공률·오류 재시도",
    report: "실패한 자동화는 다음 실행에서 재시도합니다.",
  },
  {
    id: "secretary",
    name: "비서실",
    short: "secretary.side",
    icon: "📋",
    task: "전 팀 상태 브리핑",
    report: "실제로 돌아간 팀과 오류만 추려 보고합니다.",
  },
];

/** 화면에서 숨길 부서. 앞 4칸(플랫폼 팀)만 쓴다. 계정이 늘어 2팀을 열면 여기서 뺀다. */
export const HIDDEN_DEPARTMENTS: string[] = [
  "reels", "carousel", "partner", "finance", "review", "ops", "secretary",
];

/**
 * 자동화 목록 = 계정 목록. `/new-automation` 으로 붙일 때 채운다.
 * 예: { id: "insta_main", dept: "research", name: "인스타 게시글 · main", workflow: "insta.yml",
 *       inputs: { account: "main" }, tasks: [{ id: "topic", … }, { id: "make", … }, { id: "upload", … }] }
 */
export const AUTOMATIONS: AutomationDef[] = [
  // 계정 = 자동화. 코드는 automations/insta 한 벌, 계정은 inputs.account 로 구분한다.
  { id: "insta_aitips", dept: "research", name: "인스타 게시글 · aitips (AI 툴·프롬프트 꿀팁)",
    workflow: "insta.yml", inputs: { account: "aitips" }, schedule: "매일 06:30 후보 · 07:30·12:30·18:30 게시",
    review: { kind: "topics", title: "오늘의 주제 검토" },
    tasks: [
      { id: "topic", name: "소재 선정", role: "매일 06:30 후보 20건을 검토 칸에 올리고, 07:30 에 예약이 없으면 1순위 게시", colors: ["#2b2f36", "#f3ead6", "#f2b544"] },
      { id: "write", name: "글쓰기", role: "카드 원고·캡션·해시태그 작성과 자동 심사", colors: ["#3a2f1f", "#fbf1d9", "#d99a1e"] },
      { id: "card", name: "카드 제작", role: "1080×1350 카드 8장 렌더링", colors: ["#1f2329", "#e8dcc2", "#f2b544"] },
      { id: "upload", name: "업로드", role: "공개 URL 에 올리고 인스타그램에 게시", colors: ["#4d5157", "#faf8f3", "#e0a52a"] },
    ] },
  // 2026-09-14 여러 계정 운영 — 계정마다 카드 하나, 코드는 같은 insta.yml (inputs.account 로 구분). 인스타 토큰을 등록하기 전엔 후보만 뽑는다
  { id: "insta_parent", dept: "strategy2", name: "인스타 게시글 · parent (육아 꿀팁·혜택)",
    workflow: "insta.yml", inputs: { account: "parent" }, schedule: "매일 06:30 후보 · 07:30·12:30·18:30 게시",
    review: { kind: "topics", title: "오늘의 주제 검토" },
    tasks: [
      { id: "topic", name: "육아 소재 선정", role: "육아 지원금·제도·방법 후보 20건, 빈 시간대는 1순위 자동", colors: ["#3a2a24", "#ffe9dd", "#ff8a5b"] },
      { id: "write", name: "육아 글쓰기", role: "대상·금액·기간·근거 기관이 든 기사와 캡션", colors: ["#3a2f1f", "#fbf1d9", "#ff8a5b"] },
      { id: "card", name: "육아 카드 제작", role: "1080×1350 카드 렌더링(밝은 살구색 테마)", colors: ["#2b2420", "#fff7f0", "#ff8a5b"] },
      { id: "upload", name: "육아 업로드", role: "공개 URL 에 올리고 인스타그램에 게시", colors: ["#4d5157", "#faf8f3", "#ff8a5b"] },
    ] },
  { id: "insta_benefit", dept: "brand", name: "인스타 게시글 · benefit (돈 되는 혜택 알림)",
    workflow: "insta.yml", inputs: { account: "benefit" }, schedule: "매일 06:30 후보 · 07:30·12:30·18:30 게시",
    review: { kind: "topics", title: "오늘의 주제 검토" },
    tasks: [
      { id: "topic", name: "혜택 소재 선정", role: "지원금·환급·제도 변화 후보 20건, 빈 시간대는 1순위 자동", colors: ["#16263d", "#dff7ea", "#5ee0a0"] },
      { id: "write", name: "혜택 글쓰기", role: "대상·금액·기간·신청 방법이 든 기사와 캡션", colors: ["#0f1b2d", "#e6f0ff", "#5ee0a0"] },
      { id: "card", name: "혜택 카드 제작", role: "1080×1350 카드 렌더링(남색·민트 테마)", colors: ["#0a1220", "#f5f7fb", "#5ee0a0"] },
      { id: "upload", name: "혜택 업로드", role: "공개 URL 에 올리고 인스타그램에 게시", colors: ["#4d5157", "#faf8f3", "#5ee0a0"] },
    ] },
];

export const workspace: WorkspaceConfig = {
  id: "side",
  label: "부업",
  icon: "🎬",
  company: COMPANY,
  departments: DEPARTMENTS,
  hidden: HIDDEN_DEPARTMENTS,
  automations: AUTOMATIONS,
  showPlanned: false,
};
