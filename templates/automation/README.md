# __NAME__

무엇을 하는지 한두 줄. (입력 → 결과물, 어느 드라이브 폴더/시트에 저장하는지)

실행은 GitHub Actions(`.github/workflows/__ID__.yml`)가 맡고, 대시보드(`/__WORKSPACE__`)의 **▶ 시작** 버튼이나 Actions 탭 "Run workflow"로 언제든 수동 실행할 수 있다. 끝나면 `../common/report_status.py` 가 `public/status/__WORKSPACE__/__ID__.json` 을 커밋해 화면 상태가 바뀐다.

## 실행

```bash
cd "/g/내 드라이브/dev/자동화"                      # 저장소 = 이 폴더
python automations/__ID__/run___ID__.py --dry-run   # 시험 (상태 파일 안 씀)
python automations/__ID__/run___ID__.py             # 실제
```

## 설정 (config.actions.yaml)

- `tasks` 화면 직원 id 목록 — `app/workspaces/__WORKSPACE__.ts` 와 같아야 함
- `result_link` 결과 폴더 링크 (카드 버튼)
- 비밀값은 환경변수로만: (여기에 필요한 이름을 적는다)

## 테스트

```bash
python -m pytest -q automations/__ID__
```

## 문제 해결

- (자주 나는 오류와 대처를 적는다)
