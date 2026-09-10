"""automations 아래 테스트가 자기 자동화 폴더의 모듈(errors, google_news …)을 그대로 import 하게 한다.

`pytest automations` 처럼 여러 자동화를 한 번에 돌릴 때, pytest 는 automations/ 만 sys.path 에 넣는다.
그러면 `from errors import …` 같은 줄이 깨지므로 자동화 폴더들을 직접 넣어 준다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for folder in sorted(p for p in ROOT.iterdir() if p.is_dir() and (p / "tests").is_dir()):
    sys.path.insert(0, str(folder))
