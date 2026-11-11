# 시간제보육 예약 (아이사랑 독립반)

아이사랑(childcare.go.kr)에 로그인해 시간제보육 **독립반** 자리를 잡는다.
사무실 `home` · 부서 `strategy1`(육아·돌봄팀) · 워크플로 `.github/workflows/childcare.yml` · GitHub 서버(`ubuntu-latest`)에서 돈다.

## 지금 어디까지 돼 있나

**이 PC 에서 도는 exe 로 완성(2026-11-11).** 실제 예약 1건을 넣었다 취소해 검증했다.
GitHub 서버에서 돌리는 길은 접었다 — 로그인을 사람이 한 번 해 줘야 해서 서버에 둘 이유가 없다.

| 파일 | 하는 일 |
|---|---|
| `app.py` | 창(tkinter) + 전체 흐름. exe 의 본체 |
| `launcher.py` | 크롬에 붙기 · 서버 시계 맞추기 · 정각 대기 |
| `childcare_site.py` | 아이사랑 조작 — 장전(arm)·발사(fire)·열림 확인 |
| `build_exe.cmd` | exe 로 묶기 (드라이브 밖에서 빌드, CP949 로 저장할 것) |

쓰는 법은 `ai-home/04_시간제보육/README.md`.

## 알아낸 것 (2026-11-10 실측)

- **해외 IP 차단 아님.** GitHub 서버(미국 Azure)에서 아이사랑 메인이 한국과 똑같이 뜬다. 화면 없는 브라우저(headless)로도 정상.
- **화면을 자바스크립트로 그리고 주소를 스스로 바꾼다.** 페이지를 연 직후에는 제목도 비어 있고 버튼도 없다. 주소(`?menuno=50`)로 바로 들어가면 라우터가 메인(`?menuno=1&state=…`)으로 되돌린다.
  → 그래서 `childcare_site.settle()` 로 **제목이 채워질 때까지 기다린 뒤** 누른다. 이 기다림을 빼면 "메인으로 튕긴다".
- **로그인은 아이사랑이 아니라 유보통합포털에서 한다** (2026-11-10, 사용자가 주소를 알려 줌).
  아이사랑의 "로그인" 링크(`?menuno=50`)를 타면 `sso.childcare.go.kr/sso/logout` 과 메인 사이를
  끝없이 오가며 로그인 화면이 끝내 안 뜬다(이 PC 에서도 같음). 대신 이 주소로 바로 들어간다:

      https://enter.childinfo.go.kr/icms/total/login/login.html?ltype=id&returnUrl=<돌아올 주소>

  `returnUrl` 에 아이사랑 주소를 넣으면 로그인 뒤 그 화면으로 돌아온다(확인함).
- **보안키패드는 꺼져 있다.** 폼의 숨은 값 `kybrdscrtyyn=N`, 키패드는 "키보드 보안 프로그램 적용" 버튼을 눌러야 켜진다.
  그래서 평범한 입력으로 된다 — 아이디 `#mbrid`, 비밀번호 `#uspass`, 보내기는 `ssoLoginCheck()` 를 부르는 `<a>`.
- 일반 HTTP 요청(curl)에는 암호화된 응답(`DOCUMENTSAFER`)이 오거나 연결이 끊긴다. 그래서 requests 가 아니라 **진짜 브라우저(Playwright)** 를 쓴다.

## 예약 규칙 (제도)

| | 독립반 (우리가 쓰는 것) | 통합반 |
|---|---|---|
| 운영 | 평일 09:00~18:00 | 평일 09:00~16:00 |
| 사전예약 | **이용일 14일 전 09:00** ~ 1일 전 24:00 | 14일 전 ~ 2일 전 |
| 당일예약 | 가능 (당일 14시까지) | 불가 |

**매일 아침 9시 정각에 14일 뒤 자리가 열린다.** 2단계에서 이 시각을 노린다
(예약은 워크플로 cron 이 아니라 `worker/schedule.ts` 에 적는다 — 저장소 규칙).

## 비밀값

**없다.** 사람이 크롬에서 직접 로그인하고, 매크로는 그 크롬에 붙기만 한다
(`--remote-debugging-port=9222`, 전용 프로필 `%LOCALAPPDATA%\childcare-chrome`).
비밀번호를 저장하지도 입력하지도 않는다.

## 공개 저장소라서 지키는 것

이 저장소는 공개다. 그래서 **로그인한 뒤 화면은 사진으로 남기지 않고 구조(버튼·입력란 이름)만** 뽑는다.
아이 이름·생년월일·전화번호처럼 보이는 글자는 `childcare_site.redact()` 가 가린다. 기관 이름과 예약 내용도 상태 파일·일지에 넣지 않는다.

## 실행

```bash
python automations/childcare/run_childcare.py --dry-run
```

아이디·비밀번호가 환경변수(`CHILDCARE_ID`, `CHILDCARE_PW`)에 있어야 한다.

## 예약 화면 해부 (2026-11-11 실측)

기관찾기(`?menuno=242`)에서 `a#occasionRes[data-stcode=…]` 를 누르면 입소신청(`?menuno=605`).
거기서 아동 라디오(`input[name=occasionChk]`) → `#tab1`(이용정보 신청) 을 열면 표가 나온다.

| 것 | 선택자 | 비고 |
|---|---|---|
| 반 | `select#clname` | 기관마다 다르다 (힐스송파 = 15 들꽃향기) |
| 이용시간 수 | `select#rtm` | 1~9 |
| 표의 칸 | `a.time-option#tm_<시각>_<행>` | 행 = 오늘부터 며칠 뒤(0~14) |
| 칸 글자 | 숫자 / `X` | 숫자 = 더 받을 수 있는 아동 수, 0이면 자리 없음 |
| 추가 | `#timecareTableAddBtn` | `f_AddQualRow()` — 서버를 한 번 부른다 |
| **예약** | `#timecareConfirm` | `fnSave()` → `insertOcreqst()` → 확인창 → 넷퍼넬 → 전송 |

**추가 버튼이 실제로 하는 일은 숨은 값 8개를 채우고 목록 행 하나를 만드는 것뿐이다.**
그래서 그 값을 직접 써 넣으면 서버를 한 번도 안 부르고 장전된다(`arm()`, 약 1ms).

```
sdateArray=2026-11-24(화)   resdtArray=20261124    rtmArray=1
resbgntmArray=09 : 00       resendtmArray=10 : 00  resclseqArray=15
restimeArray=09 : 00  ~  10 : 00     infoNum=1
```

콜론 둘레 공백과 물결 양옆 공백까지 화면과 똑같아야 한다 (`tests/test_slot.py` 가 지킨다).

### 넷퍼넬 (중요)

`netfunnel-pcms.js` 가 올라와 있다 — 티켓팅 사이트의 그 대기열이다.
**한 발만 쏜다.** 대기표를 받은 뒤 또 쏘면 줄 뒤로 밀리거나 막힌다.
대신 확인창(`#layer-confirm-popup-confirm2`)을 MutationObserver 로 뜨는 즉시 누른다 —
사람은 0.5~1초, 이쪽은 1프레임이다.

성공하면 `1건 예약 중 1건 예약되었습니다.` 가 뜬다.

### 오픈 시각

공식 안내는 "이용일 14일 전 09:00" 이고, 실제로 예약 가능일이 `오늘 ~ 오늘+14` 로 나오는 것은 확인했다.
하지만 **초 단위는 확인 못 했고 기관마다 다를 수 있다.** 그래서 예상 시각 전부터
`is_open()` 으로 가볍게 지켜보다가 열리는 순간 쏜다.

### 시계

이 PC 시계는 틀린다(실측 -195ms). 아이사랑 응답의 `Date` 헤더는 초 단위라 그냥 읽으면 최대 1초가 틀리므로,
**초가 넘어가는 순간**을 잡아 ms 까지 맞춘다(`launcher.server_offset_ms`).
