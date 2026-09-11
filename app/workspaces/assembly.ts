// 국회 사무실 설정. 부서 id 12개는 엔진이 참조하므로 바꾸지 말 것 (이름·아이콘·업무는 자유).
import type { AutomationDef, CompanyInfo, Department, WorkspaceConfig } from "./types";

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
 * 화면에서 숨길 부서. 엔진은 12개 부서를 전제로 움직이므로 지우지 않고 숨긴다.
 */
export const HIDDEN_DEPARTMENTS: string[] = ["finance", "ops", "secretary"];

/**
 * 자동화 목록. 부서 하나에 자동화 하나(이상). tasks = 직원(업무명).
 * workflow 가 있는 것만 실제로 돌릴 수 있고, 나머지는 "준비 중".
 * 하위 작업 id 는 Python 설정(automations/<id>/config.actions.yaml 의 tasks:)과 같아야 한다(테스트로 강제).
 */
export const AUTOMATIONS: AutomationDef[] = [
  {
    id: "minutes", dept: "research", name: "국회회의록 수집",
    workflow: "minutes.yml", // 예약 없음 — 수동으로만 (2026-09-11)
    tasks: [
      { id: "collect", name: "회의록 수집", role: "본회의·위원회 회의록 목록 조회와 PDF 저장", colors: ["#6b3d34", "#d9efee", "#006bce"] },
      { id: "replace", name: "확정본 교체", role: "임시회의록이 확정본으로 바뀌면 다시 저장", colors: ["#2f2a3d", "#cfd6dc", "#b9cbdc"] },
      { id: "audit", name: "국감·국조 수집", role: "국정감사·국정조사는 사이트에서 직접 수집", colors: ["#8a4a3c", "#b9cbdc", "#006bce"], planned: true },
    ],
  },
  { id: "news", dept: "brand", name: "기사 수집",
    workflow: "news.yml", schedule: "3시간마다",
    tasks: [
      { id: "collect", name: "기사 모으기", role: "구글 뉴스에서 의원·위원회 기사 검색", colors: ["#2f4858", "#e8eef2", "#0f766e"] },
      { id: "digest", name: "요약 정리", role: "중복 기사를 합치고 묶음별로 정리해 드라이브에 저장", colors: ["#4a3b2f", "#f0e6d8", "#b45309"] },
    ] },
  { id: "sns", dept: "strategy1", name: "SNS 확인",
    tasks: [
      { id: "facebook", name: "페이스북 확인", role: "페이스북 새 게시글 확인·알림" },
      { id: "instagram", name: "인스타 확인", role: "인스타그램 새 게시글 확인·알림" },
    ] },
  { id: "mail", dept: "qa", name: "상임위 메일",
    tasks: [
      { id: "summary", name: "메일 요약 알림", role: "상임위 메일 요약해 텔레그램 전송" },
      { id: "attach", name: "첨부 저장", role: "메일 첨부파일을 드라이브 수신함에 저장" },
    ] },
  { id: "question", dept: "strategy2", name: "질의서",
    tasks: [
      { id: "draft", name: "질의서 초안", role: "회의 자료 기반 질의서 초안 작성" },
      { id: "digest", name: "자료 요약", role: "회의 자료에서 안건·쟁점 요약" },
      { id: "evidence", name: "근거 조사", role: "수치·출처 확인과 최신 뉴스 검색" },
    ] },
  { id: "shorts", dept: "reels", name: "쇼츠",
    tasks: [
      { id: "video", name: "영상 생성", role: "쇼츠 영상 초안 생성" },
      { id: "edit", name: "자막·편집", role: "자막 입히기와 컷 편집" },
    ] },
  { id: "press", dept: "carousel", name: "보도자료",
    tasks: [{ id: "draft", name: "보도자료 초안", role: "질의 결과를 보도자료 형식으로 작성" }] },
  { id: "calendar", dept: "partner", name: "의사일정",
    tasks: [{ id: "sync", name: "의사일정 반영", role: "상임위 의사일정을 캘린더에 반영" }] },
  { id: "filing", dept: "review", name: "자료 분류",
    tasks: [{ id: "sort", name: "자료 분류", role: "받은 자료를 회의 날짜별 폴더로 분류" }] },
];

export const workspace: WorkspaceConfig = {
  id: "assembly",
  label: "국회",
  icon: "🏛️",
  company: COMPANY,
  departments: DEPARTMENTS,
  hidden: HIDDEN_DEPARTMENTS,
  automations: AUTOMATIONS,
  showPlanned: false,
};
