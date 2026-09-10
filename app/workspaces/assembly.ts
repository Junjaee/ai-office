// 국회 사무실 설정. 부서 id 12개는 엔진이 참조하므로 바꾸지 말 것 (이름·아이콘·업무는 자유).
import type { CeoProfile, CompanyInfo, Department, StaffEntry, WorkspaceConfig } from "./types";

/** 회사 기본 정보 */
export const COMPANY: CompanyInfo = {
  name: "의원실 AI 오피스",
  logoLetter: "국",
  /** 헤더 로고 이미지 (public/ 기준 경로). 비우면 logoLetter 사용 */
  logoImage: "/na-mark.png",
  titlePrefix: "의원실",
  titleAccent: "AI Office",
  pageTitle: "의원실 AI 오피스 — 자동화 현황",
  description: "국회회의록 수집부터 기사·SNS 모니터링, 질의서 초안까지 의원실 자동화가 돌아가는 픽셀 사무실",
  windowLabel: "assembly_office.exe — 대표실",
  reportName: "의원실 AI 오피스",
};

/** 대표(나) — 사무실 대표실에 앉아 있는 캐릭터 */
export const CEO_PROFILE: CeoProfile = {
  name: "신준재",
  callsign: "대표님",
  role: "보좌진 · 자동화 총괄",
  hair: "#42283a",
  shirt: "#0c2b80",
  accent: "#e1e4e6",
  skin: "#ffdcc4",
  thoughts: [
    "자동으로 돌 수 있는 일은 전부 직원에게 맡긴다.",
    "오늘 회의록 새로 올라온 게 있나?",
    "질의서는 근거부터, 표현은 나중에.",
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
    name: "국회회의록 수집팀",
    short: "minutes.lab",
    icon: "📜",
    task: "회의록 신규분 수집·확정본 교체",
    report: "21·22대 회의록 전부 받아 두었고, 매일 새 것만 더합니다.",
  },
  {
    id: "brand",
    name: "뉴스 모니터링팀",
    short: "news.watch",
    icon: "📰",
    task: "의원 관련 기사 수집",
    report: "자동화가 붙으면 아침마다 기사 목록을 정리합니다.",
  },
  {
    id: "strategy1",
    name: "SNS 모니터링팀",
    short: "sns.watch",
    icon: "📱",
    task: "페이스북·인스타 게시글 확인",
    report: "로그인 브라우저가 준비되면 새 글을 확인합니다.",
  },
  {
    id: "qa",
    name: "상임위 메일팀",
    short: "mail.desk",
    icon: "✉️",
    task: "상임위 메일 확인·텔레그램 알림",
    report: "메일 확인 스킬을 붙이면 새 메일을 요약해 알립니다.",
  },
  {
    id: "strategy2",
    name: "질의서 작성팀",
    short: "brief.write",
    icon: "✍️",
    task: "회의 자료 요약·질의서 초안",
    report: "수신함 자료를 회의별로 정리하고 초안을 씁니다.",
  },
  {
    id: "reels",
    name: "영상 제작팀",
    short: "video.edit",
    icon: "🎬",
    task: "쇼츠 영상 제작",
    report: "영상 API가 연결되면 초안을 만듭니다.",
  },
  {
    id: "carousel",
    name: "보도자료팀",
    short: "press.room",
    icon: "🗞️",
    task: "보도자료 초안 작성",
    report: "질의 결과를 보도자료 형식으로 옮깁니다.",
  },
  {
    id: "partner",
    name: "일정·의사일정팀",
    short: "schedule.hq",
    icon: "📅",
    task: "의사일정 정리",
    report: "상임위 일정을 캘린더에 맞춥니다.",
  },
  {
    id: "finance",
    name: "지출·정산팀",
    short: "ledger.xls",
    icon: "🧾",
    task: "지출 내역 시트 갱신",
    report: "내역이 오면 시트에 한 줄씩 쌓습니다.",
  },
  {
    id: "review",
    name: "자료실 정리팀",
    short: "archive.box",
    icon: "🗂️",
    task: "드라이브 자료 분류",
    report: "받은 자료를 회의 폴더로 나눠 넣습니다.",
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
    short: "secretary.hq",
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
  { dept: "research", rank: "lead", name: "회의록 수집", role: "본회의·위원회 회의록 목록 조회와 PDF 저장",
    colors: ["#6b3d34", "#d9efee", "#006bce"],
    thoughts: ["오늘 올라온 회의록 0건이면 그것도 보고.", "PDF 없는 건은 따로 표시."] },
  { dept: "research", rank: "member", name: "확정본 교체", role: "임시회의록이 확정본으로 바뀌면 다시 저장",
    colors: ["#2f2a3d", "#cfd6dc", "#b9cbdc"],
    thoughts: ["임시로 남은 회기만 다시 확인.", "같은 파일명에 덮어쓴다."] },
  { dept: "research", rank: "member", name: "국감·국조 수집", role: "Open API에 없는 국정감사·국정조사는 사이트에서 직접 수집",
    colors: ["#8a4a3c", "#b9cbdc", "#006bce"],
    thoughts: ["국감은 연도별 폴더로.", "국조는 회기별로."] },

  // brand
  { dept: "brand", rank: "lead", name: "기사 수집", role: "의원 관련 기사 매일 수집·정리",
    colors: ["#372b4a", "#f3f4f6", "#cfd6dc"],
    thoughts: ["자동화 준비 중.", "같은 기사 재탕은 하나로."] },

  // strategy1
  { dept: "strategy1", rank: "lead", name: "페이스북 확인", role: "페이스북 새 게시글 확인·알림",
    colors: ["#c26e4b", "#006bce", "#d9efee"],
    thoughts: ["로그인 브라우저가 있어야 해.", "자동화 준비 중."] },
  { dept: "strategy1", rank: "member", name: "인스타 확인", role: "인스타그램 새 게시글 확인·알림",
    colors: ["#2d4b46", "#b9cbdc", "#b9cbdc"],
    thoughts: ["차단당하지 않게 천천히.", "자동화 준비 중."] },

  // qa
  { dept: "qa", rank: "lead", name: "메일 요약 알림", role: "상임위 메일 요약해 텔레그램 전송",
    colors: ["#6b3d34", "#d9efee", "#006bce"],
    thoughts: ["과방위·재경위 메일부터.", "자동화 준비 중."] },
  { dept: "qa", rank: "member", name: "첨부 저장", role: "메일 첨부파일을 드라이브 수신함에 저장",
    colors: ["#2f2a3d", "#cfd6dc", "#b9cbdc"],
    thoughts: ["hwp와 pdf 같이 있는지 확인.", "회의 날짜별 폴더."] },

  // strategy2
  { dept: "strategy2", rank: "lead", name: "질의서 초안", role: "회의 자료 기반 질의서 초안 작성",
    colors: ["#8a4a3c", "#b9cbdc", "#006bce"],
    thoughts: ["[사실확인]→[급소]→[추궁]→[대안].", "음슴체, 볼드는 핵심만."] },
  { dept: "strategy2", rank: "member", name: "자료 요약", role: "회의 자료에서 안건·쟁점 요약",
    colors: ["#372b4a", "#f3f4f6", "#cfd6dc"],
    thoughts: ["안건·일시·장소부터.", "미확인 정보는 ⚠️ 표시."] },
  { dept: "strategy2", rank: "member", name: "근거 조사", role: "수치·출처 확인과 최신 뉴스 검색",
    colors: ["#c26e4b", "#006bce", "#d9efee"],
    thoughts: ["수치엔 출처와 확인일.", "최신 뉴스 한 번 더."] },

  // reels
  { dept: "reels", rank: "lead", name: "영상 생성", role: "쇼츠 영상 초안 생성",
    colors: ["#2d4b46", "#b9cbdc", "#b9cbdc"],
    thoughts: ["영상 API 비용부터 정리.", "자동화 준비 중."] },
  { dept: "reels", rank: "member", name: "자막·편집", role: "자막 입히기와 컷 편집",
    colors: ["#6b3d34", "#d9efee", "#006bce"],
    thoughts: ["원본은 보존, 편집본만 새로.", "30초 안에."] },

  // carousel
  { dept: "carousel", rank: "lead", name: "보도자료 초안", role: "질의 결과를 보도자료 형식으로 작성",
    colors: ["#2f2a3d", "#cfd6dc", "#b9cbdc"],
    thoughts: ["제목 한 줄에 핵심 수치.", "배포 전엔 반드시 검토."] },

  // partner
  { dept: "partner", rank: "lead", name: "의사일정 반영", role: "상임위 의사일정을 캘린더에 반영",
    colors: ["#8a4a3c", "#b9cbdc", "#006bce"],
    thoughts: ["의사일정(안)이 오면 바로.", "소위 일정은 별도 표시."] },

  // finance
  { dept: "finance", rank: "lead", name: "지출 기록", role: "지출 내역 시트 기록 (ai-home으로 이전 예정)",
    colors: ["#372b4a", "#f3f4f6", "#cfd6dc"],
    thoughts: ["이 일은 ai-home에서 맡을 예정."] },

  // review
  { dept: "review", rank: "lead", name: "자료 분류", role: "받은 자료를 회의 날짜별 폴더로 분류",
    colors: ["#c26e4b", "#006bce", "#d9efee"],
    thoughts: ["YYYYMMDD_회의구분 규칙.", "수신함은 처리 후 비운다."] },

  // ops
  { dept: "ops", rank: "lead", name: "실행 감시", role: "모든 자동화의 성공·오류 집계",
    colors: ["#2d4b46", "#b9cbdc", "#b9cbdc"],
    thoughts: ["실패는 다음 실행에서 재시도.", "36시간 넘게 갱신 없으면 오래됨 표시."] },

  // secretary
  { dept: "secretary", rank: "lead", name: "브리핑", role: "실제 팀 상태 요약 보고",
    colors: ["#6b3d34", "#d9efee", "#006bce"],
    thoughts: ["실제로 돌아간 팀만 정리해서 보고.", "오류 팀은 먼저."] },
];

/**
 * 아직 자동화가 붙지 않은 부서 → 화면에 "연동 대기"(자동화 준비 중)로 표시됩니다.
 * 자동화를 붙이고 status/<id>.json 을 올리면 실제 상태가 이 표시를 덮어씁니다.
 */
export const PENDING_INTEGRATIONS: Record<string, string> = {
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
 * 결과 보관함 링크 (구글 드라이브 _회의록 폴더 등). 비워두면 화면에서 링크 버튼이 숨겨집니다.
 */
export const STORAGE_LINK = "";

/**
 * 화면에서 숨길 부서. 엔진은 12개 부서를 전제로 움직이므로 지우지 않고 숨긴다.
 */
export const HIDDEN_DEPARTMENTS: string[] = [];

export const workspace: WorkspaceConfig = {
  id: "assembly",
  label: "국회",
  icon: "🏛️",
  palette: "assembly",
  company: COMPANY,
  ceo: CEO_PROFILE,
  departments: DEPARTMENTS,
  staff: STAFF_LIST,
  pending: PENDING_INTEGRATIONS,
  hidden: HIDDEN_DEPARTMENTS,
  storageLink: STORAGE_LINK,
};
