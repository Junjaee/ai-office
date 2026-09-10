// 홈 사무실 설정. 부서 id 12개는 엔진이 참조하므로 바꾸지 말 것 (이름·아이콘·업무는 자유).
import type { CeoProfile, CompanyInfo, Department, StaffEntry, WorkspaceConfig } from "./types";

/** 기본 정보 */
export const COMPANY: CompanyInfo = {
  name: "우리집 AI 홈",
  logoLetter: "홈",
  /** 헤더 로고 이미지 (public/ 기준 경로). 비우면 logoLetter 사용 */
  logoImage: "",
  titlePrefix: "우리집",
  titleAccent: "AI Home",
  pageTitle: "우리집 AI 홈 — 가정 자동화 현황",
  description: "지출 정산, 장보기, 가족 일정, 공과금까지 집안일 자동화가 돌아가는 픽셀 홈오피스",
  windowLabel: "ai_home.exe — 서재",
  reportName: "우리집 AI 홈",
};

/** 대표(나) — 서재에 앉아 있는 캐릭터 */
export const CEO_PROFILE: CeoProfile = {
  name: "신준재",
  callsign: "집주인",
  role: "가장 · 집안 자동화 총괄",
  hair: "#42283a",
  shirt: "#1e3a8a",
  accent: "#e2e8f0",
  skin: "#ffdcc4",
  thoughts: [
    "집안일도 자동으로 돌 수 있는 건 전부 맡긴다.",
    "이번 달 지출, 어디서 샜지?",
    "주말 일정 겹치는 거 없나 확인.",
  ],
};

/**
 * 부서 12개.
 * id = 고정(엔진용) / name·short·icon = 자유롭게 변경
 * task = 오늘 하는 일 / report = 팀장 한줄보고
 */
export const DEPARTMENTS: readonly Department[] = [
  {
    id: "research",
    name: "지출·정산팀",
    short: "ledger.xls",
    icon: "🧾",
    task: "지출 내역 시트 갱신·월별 정산",
    report: "내역이 오면 시트에 한 줄씩 쌓고 월말에 정리합니다.",
  },
  {
    id: "brand",
    name: "장보기·생필품팀",
    short: "grocery.list",
    icon: "🛒",
    task: "떨어진 생필품 목록·장보기 리스트",
    report: "자동화가 붙으면 재구매 시기를 알려 드립니다.",
  },
  {
    id: "strategy1",
    name: "가족 일정팀",
    short: "family.cal",
    icon: "📅",
    task: "가족 캘린더 정리·겹침 확인",
    report: "캘린더가 연결되면 주간 일정을 브리핑합니다.",
  },
  {
    id: "qa",
    name: "공과금·고지서팀",
    short: "bills.desk",
    icon: "💡",
    task: "납부 기한 확인·고지서 정리",
    report: "고지서 메일이 연결되면 기한 전에 알립니다.",
  },
  {
    id: "strategy2",
    name: "건강·운동팀",
    short: "health.log",
    icon: "🏃",
    task: "운동·건강 기록 정리",
    report: "기록 앱이 연결되면 주간 리포트를 만듭니다.",
  },
  {
    id: "reels",
    name: "여행 계획팀",
    short: "trip.plan",
    icon: "✈️",
    task: "여행 일정·예약 정리",
    report: "여행 폴더의 계획서를 일정표로 바꿉니다.",
  },
  {
    id: "carousel",
    name: "집안 관리팀",
    short: "house.care",
    icon: "🧹",
    task: "청소·수리·소모품 교체 주기",
    report: "필터·건전지 같은 교체 주기를 관리합니다.",
  },
  {
    id: "partner",
    name: "차량 관리팀",
    short: "car.log",
    icon: "🚗",
    task: "정비·보험·검사 일정",
    report: "정기검사와 보험 갱신 시기를 알립니다.",
  },
  {
    id: "finance",
    name: "자산·투자팀",
    short: "asset.watch",
    icon: "📈",
    task: "주식·코인 현황 정리",
    report: "시세 연동이 되면 아침마다 현황을 정리합니다.",
  },
  {
    id: "review",
    name: "취미·콘텐츠팀",
    short: "hobby.studio",
    icon: "🎵",
    task: "유튜브·AI 노래 프로젝트 정리",
    report: "만든 콘텐츠와 진행 상황을 기록합니다.",
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
    short: "secretary.home",
    icon: "📋",
    task: "전 팀 상태 브리핑",
    report: "실제로 돌아간 팀과 오류만 추려 보고합니다.",
  },
];

/**
 * 직원 명단.
 * dept = 위 부서 id / rank: "lead"(팀장) 또는 "member"(팀원)
 * colors = [머리색, 옷색, 포인트색]
 * thoughts = 자리를 비웠을 때 머리 위에 뜨는 혼잣말
 */
export const STAFF_LIST: StaffEntry[] = [
  // research
  { dept: "research", rank: "lead", name: "내역 수집", role: "카드·계좌 지출 내역 받아오기",
    colors: ["#6b3d34", "#e0f2fe", "#3b82f6"],
    thoughts: ["오늘 내역 새로 들어온 게 있나.", "중복 결제는 하나로."] },
  { dept: "research", rank: "member", name: "시트 정리", role: "지출 시트 기록·월별 합계",
    colors: ["#2f2a3d", "#cbd5e1", "#bfdbfe"],
    thoughts: ["카테고리 빠진 줄 확인.", "월말 합계는 수식으로."] },

  // brand
  { dept: "brand", rank: "lead", name: "재구매 알림", role: "생필품 재구매 시기 알림",
    colors: ["#8a4a3c", "#bfdbfe", "#3b82f6"],
    thoughts: ["자동화 준비 중."] },

  // strategy1
  { dept: "strategy1", rank: "lead", name: "일정 정리", role: "가족 캘린더 정리·겹침 확인",
    colors: ["#372b4a", "#f1f5f9", "#cbd5e1"],
    thoughts: ["자동화 준비 중."] },

  // qa
  { dept: "qa", rank: "lead", name: "납부 알림", role: "공과금 납부 기한 알림",
    colors: ["#c26e4b", "#3b82f6", "#e0f2fe"],
    thoughts: ["자동화 준비 중."] },

  // strategy2
  { dept: "strategy2", rank: "lead", name: "건강 기록", role: "운동·건강 기록 정리",
    colors: ["#2d4b46", "#bfdbfe", "#bfdbfe"],
    thoughts: ["자동화 준비 중."] },

  // reels
  { dept: "reels", rank: "lead", name: "여행 일정표", role: "여행 계획을 일정표로 정리",
    colors: ["#6b3d34", "#e0f2fe", "#3b82f6"],
    thoughts: ["자동화 준비 중."] },

  // carousel
  { dept: "carousel", rank: "lead", name: "교체 주기", role: "소모품 교체·수리 주기 관리",
    colors: ["#2f2a3d", "#cbd5e1", "#bfdbfe"],
    thoughts: ["자동화 준비 중."] },

  // partner
  { dept: "partner", rank: "lead", name: "차량 일정", role: "정비·보험·검사 일정 알림",
    colors: ["#8a4a3c", "#bfdbfe", "#3b82f6"],
    thoughts: ["자동화 준비 중."] },

  // finance
  { dept: "finance", rank: "lead", name: "시세 정리", role: "주식·코인 현황 정리",
    colors: ["#372b4a", "#f1f5f9", "#cbd5e1"],
    thoughts: ["자동화 준비 중."] },

  // review
  { dept: "review", rank: "lead", name: "콘텐츠 정리", role: "유튜브·AI 노래 프로젝트 기록",
    colors: ["#c26e4b", "#3b82f6", "#e0f2fe"],
    thoughts: ["자동화 준비 중."] },

  // ops
  { dept: "ops", rank: "lead", name: "실행 감시", role: "모든 자동화의 성공·오류 집계",
    colors: ["#2d4b46", "#bfdbfe", "#bfdbfe"],
    thoughts: ["실패는 다음 실행에서 재시도.", "36시간 넘게 갱신 없으면 오래됨 표시."] },

  // secretary
  { dept: "secretary", rank: "lead", name: "브리핑", role: "실제 팀 상태 요약 보고",
    colors: ["#6b3d34", "#e0f2fe", "#3b82f6"],
    thoughts: ["실제로 돌아간 팀만 정리해서 보고.", "오류 팀은 먼저."] },
];

/**
 * 아직 자동화가 붙지 않은 부서 → 화면에 "연동 대기"(자동화 준비 중)로 표시됩니다.
 * 자동화를 붙이고 status/<id>.json 을 올리면 실제 상태가 이 표시를 덮어씁니다.
 */
export const PENDING_INTEGRATIONS: Record<string, string> = {
  research: "자동화 준비 중",
  brand: "자동화 준비 중",
  strategy1: "자동화 준비 중",
  qa: "자동화 준비 중",
  strategy2: "자동화 준비 중",
  reels: "자동화 준비 중",
  carousel: "자동화 준비 중",
  partner: "자동화 준비 중",
  finance: "자동화 준비 중",
  review: "자동화 준비 중",
};

/**
 * 결과 보관함 링크 (구글 드라이브 폴더 등). 비워두면 화면에서 링크 버튼이 숨겨집니다.
 */
export const STORAGE_LINK = "";

/**
 * 화면에서 숨길 부서. 엔진은 12개 부서를 전제로 움직이므로 지우지 않고 숨긴다.
 * 자동화를 붙일 때 여기서 빼면 다시 나타난다.
 */
export const HIDDEN_DEPARTMENTS: string[] = [
  "brand", "strategy1", "qa", "strategy2", "reels", "carousel", "partner", "finance", "review",
];

export const workspace: WorkspaceConfig = {
  id: "home",
  label: "홈",
  icon: "🏠",
  palette: "home",
  company: COMPANY,
  ceo: CEO_PROFILE,
  departments: DEPARTMENTS,
  staff: STAFF_LIST,
  pending: PENDING_INTEGRATIONS,
  hidden: HIDDEN_DEPARTMENTS,
  storageLink: STORAGE_LINK,
};
