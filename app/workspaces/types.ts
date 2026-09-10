// 워크스페이스(사무실) 하나의 설정. 엔진은 company.config.ts 를 통해 현재 워크스페이스 값을 읽는다.
export type CompanyInfo = {
  name: string;
  logoLetter: string;
  /** 헤더 로고 이미지 (public/ 기준 경로). 비우면 logoLetter 사용 */
  logoImage: string;
  titlePrefix: string;
  titleAccent: string;
  pageTitle: string;
  description: string;
  windowLabel: string;
  reportName: string;
};

export type CeoProfile = {
  name: string;
  callsign: string;
  role: string;
  hair: string;
  shirt: string;
  accent: string;
  skin: string;
  thoughts: string[];
};

export type Department = {
  id: string;
  name: string;
  short: string;
  icon: string;
  task: string;
  report: string;
};

export type StaffEntry = {
  dept: string;
  rank: "lead" | "member";
  name: string;
  role: string;
  colors: [string, string, string];
  thoughts: string[];
  callsign?: string;
};

/** 자동화의 하위 작업 = 화면의 직원 한 명 (이름은 업무명) */
export type TaskDef = {
  /** 상태 파일 tasks[].id 와 일치 */
  id: string;
  /** 직원 이름 = 업무명 (사무실 안에서 유일) */
  name: string;
  /** 카드·툴팁 한 줄 */
  role: string;
  /** [머리색, 옷색, 포인트색]. 없으면 순환 팔레트 */
  colors?: [string, string, string];
  /** 아직 자동화되지 않은 업무 → "준비 중", 집계 제외 */
  planned?: boolean;
};

/** 자동화 하나 = 부서 카드 하나 = 시작 버튼 단위 */
export type AutomationDef = {
  /** = public/status/<ws>/<id>.json 의 id */
  id: string;
  /** 12개 부서 id 중 하나 */
  dept: string;
  /** 카드 제목 */
  name: string;
  /** .github/workflows 파일명. 없으면 준비 중(시작 버튼 없음) */
  workflow?: string;
  /** workflow_dispatch 기본 입력 (request_id 는 Worker 가 덧붙임) */
  inputs?: Record<string, string>;
  /** "매일 09:00" 같은 예약 설명. 있으면 예약 밀림 배너 대상 */
  schedule?: string;
  /** 1개 이상, 부서 합계 6개 이하 */
  tasks: TaskDef[];
};

export type WorkspaceConfig = {
  /** URL 경로 (/assembly, /home, /stock …) 이자 public/status/<id>/ 폴더 이름 */
  id: string;
  /** 상단 사무실 선택 탭에 보이는 이름 */
  label: string;
  icon: string;
  /** globals.css 의 html[data-ws="…"] 팔레트 이름 */
  palette: string;
  company: CompanyInfo;
  ceo: CeoProfile;
  departments: readonly Department[];
  staff: StaffEntry[];
  pending: Record<string, string>;
  hidden: string[];
  storageLink: string;
  /** 자동화 목록 (직원·카드·실행 허용 목록의 원천) */
  automations: AutomationDef[];
  /** true 면 자동화 없는 부서도 회색으로 그림 (기본 false) */
  showPlanned?: boolean;
};
