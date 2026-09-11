"""글 생성기 — 무료 경로만 쓴다 (사용자 결정 2026-09-11).

제공자(순서대로 시도, 하나가 실패하면 다음으로):
  claude_cli  : Claude 구독으로 `claude -p` 실행. CI 에서는 Secret CLAUDE_CODE_OAUTH_TOKEN, 이 PC 에서는 `claude login` 상태를 쓴다.
  gemini      : Gemini API 무료 등급 (환경변수 GEMINI_API_KEY).

사용:
    llm = LLM(["claude_cli", "gemini"])
    data = llm.json(system="...", user="...", schema={...})   # JSON dict 를 돌려준다 (스키마 검증 포함)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

import requests

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CLAUDE_TIMEOUT = 600


class LLMError(RuntimeError):
    """모든 제공자가 실패했다."""


def extract_json(text: str) -> dict:
    """응답 본문에서 첫 JSON 객체를 꺼낸다. ```json 울타리·앞뒤 설명이 있어도 된다."""
    if not text:
        raise ValueError("빈 응답")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("JSON 객체를 찾지 못함")
        candidate = text[start:end + 1]
    return json.loads(candidate)


def validate(data: dict, schema: dict | None) -> None:
    if schema and jsonschema:
        jsonschema.validate(data, schema)


@dataclass
class Attempt:
    provider: str
    ok: bool
    note: str = ""


@dataclass
class LLM:
    providers: list[str]
    claude_bin: str = "claude"
    claude_model: str = ""          # 비우면 CLI 기본 모델
    gemini_model: str = GEMINI_MODEL
    timeout: int = CLAUDE_TIMEOUT
    attempts: list[Attempt] = field(default_factory=list)
    last_provider: str = ""

    # ── 공개 API ──
    def json(self, *, system: str, user: str, schema: dict | None = None, retries: int = 1) -> dict:
        """system+user 로 JSON 응답을 받아 dict 로. 스키마 위반이면 같은 제공자에게 한 번 더(오류를 붙여) 시킨다."""
        errors: list[str] = []
        for name in self.providers:
            call = getattr(self, f"_call_{name}", None)
            if call is None:
                errors.append(f"{name}: 알 수 없는 제공자")
                continue
            if not self._available(name):
                self.attempts.append(Attempt(name, False, "자격 증명 없음"))
                errors.append(f"{name}: 자격 증명 없음")
                continue
            prompt = user
            for i in range(retries + 1):
                try:
                    text = call(system, prompt)
                    data = extract_json(text)
                    validate(data, schema)
                    self.attempts.append(Attempt(name, True))
                    self.last_provider = name
                    return data
                except (ValueError, json.JSONDecodeError) as exc:
                    note = f"JSON 형식 오류: {str(exc)[:120]}"
                    prompt = user + f"\n\n[이전 응답이 JSON 형식을 어겼습니다: {note}. 설명 없이 JSON 객체 하나만 출력하세요.]"
                except Exception as exc:  # noqa: BLE001 - jsonschema.ValidationError 포함, 제공자 오류 포함
                    note = f"{type(exc).__name__}: {str(exc)[:160]}"
                    if _is_schema_error(exc):
                        prompt = user + f"\n\n[이전 응답이 스키마를 어겼습니다: {note}. 요구한 키와 형식을 정확히 지키세요.]"
                    else:
                        self.attempts.append(Attempt(name, False, note))
                        errors.append(f"{name}: {note}")
                        break
                if i == retries:
                    self.attempts.append(Attempt(name, False, note))
                    errors.append(f"{name}: {note}")
        raise LLMError("글 생성기 전부 실패 — " + " / ".join(errors))

    # ── 제공자 ──
    def _available(self, name: str) -> bool:
        if name == "claude_cli":
            return shutil.which(self.claude_bin) is not None
        if name == "gemini":
            return bool((os.environ.get("GEMINI_API_KEY") or "").strip())
        return False

    def _call_claude_cli(self, system: str, user: str) -> str:
        # 프롬프트는 길어서 명령줄에 못 싣는다(Windows 8천 자 제한) → 시스템 프롬프트는 파일, 사용자 프롬프트는 표준입력으로
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(system)
            sys_path = f.name
        cmd = [self.claude_bin, "-p", "--output-format", "json", "--system-prompt-file", sys_path,
               "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Agent,NotebookEdit"]
        if self.claude_model:
            cmd += ["--model", self.claude_model]
        try:
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=self.timeout, shell=os.name == "nt")
        finally:
            try:
                os.unlink(sys_path)
            except OSError:
                pass
        out = (proc.stdout or "").strip()
        if not out:
            raise RuntimeError(f"claude 출력 없음 (exit {proc.returncode}): {(proc.stderr or '')[:200]}")
        try:
            envelope = json.loads(out)
        except json.JSONDecodeError:
            return out                      # 예전 CLI 는 본문만 줄 수도 있다
        if envelope.get("is_error"):
            raise RuntimeError(f"claude 오류: {str(envelope.get('result'))[:200]}")
        result = envelope.get("result")
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)

    def _call_gemini(self, system: str, user: str) -> str:
        key = os.environ["GEMINI_API_KEY"].strip()
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
        }
        r = requests.post(GEMINI_URL.format(model=self.gemini_model), params={"key": key}, json=body, timeout=120)
        if r.status_code == 429:
            raise RuntimeError("Gemini 무료 한도 초과(429)")
        if not r.ok:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"Gemini 응답 형식 이상: {json.dumps(data)[:200]}")


def _is_schema_error(exc: BaseException) -> bool:
    return jsonschema is not None and isinstance(exc, jsonschema.ValidationError)
