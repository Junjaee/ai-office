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
};
