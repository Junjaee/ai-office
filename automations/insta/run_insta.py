"""인스타그램 게시글 자동화 — 소재(topic) → 글(write: 조사·기사·검수) → 카드(card: 요약·사진·렌더) → 업로드(upload).

사용:
  python run_insta.py --account aitips                  # 실제 실행 (게시 + 상태 파일 커밋·push)
  python run_insta.py --account aitips --dry-run        # 게시·보고 없이 카드까지만 만들어 out/ 에 저장
  python run_insta.py --account aitips --until write    # 해당 단계까지만 (topic | write | card | upload). write 뒤에 out/…/article.md 를 읽고 확인
  python run_insta.py --account aitips --resume         # out/<계정>/<날짜>/ 에 남은 중간 결과를 이어서
  옵션: --config 경로, --pick N (후보 N번을 강제로 고름), --date YYYY-MM-DD

코드는 플랫폼당 한 벌이고 계정별 차이는 config.actions.yaml 의 accounts 와 profiles/<이름>.yaml 에 있다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import to_korean  # noqa: E402
import insta_research as research  # noqa: E402
import insta_sources as sources  # noqa: E402
import insta_writer as writer  # noqa: E402
from insta_llm import LLM, LLMError  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

KST = timezone(timedelta(hours=9))
HERE = Path(__file__).resolve().parent
AUTOMATION_NAME = "인스타 게시글"
STEPS = ["topic", "write", "card", "upload"]


# ───────────────────────── 파이프라인 ─────────────────────────

def load_profile(name: str) -> tuple[writer.Profile, str]:
    d = yaml.safe_load((HERE / "profiles" / f"{name}.yaml").read_text(encoding="utf-8")) or {}
    refs = (HERE / d.get("references", "")).read_text(encoding="utf-8") if d.get("references") else ""
    return writer.Profile.from_dict(d), refs


def posted_path(account: str) -> Path:
    return HERE.parent.parent / "data" / "insta" / account / "posted.jsonl"


def load_posted(account: str) -> list[dict]:
    p = posted_path(account)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_posted(account: str, row: dict) -> None:
    p = posted_path(account)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def step_topic(cfg: dict, acct: dict, p: writer.Profile, llm: LLM, out: Path, args, progress) -> dict:
    posted = load_posted(args.account)
    exclude = {r.get("key", "") for r in posted}
    cands, failed = sources.collect(p.sources, max_age_hours=p.max_age_hours, signals=p.source_signals,
                                    exclude_keys=exclude, progress=progress)
    if not cands:
        raise RuntimeError("소재 후보가 없습니다 (출처 전부 실패: " + "; ".join(failed[:3]) + ")")
    limit = int(acct.get("candidates_to_llm", 30))
    rows = sources.as_prompt_rows(cands, limit)
    if args.pick:
        picks = [{"index": args.pick, "reason": "수동 선택", "angle": ""}]
    else:
        s, u = writer.pick_prompt(p, rows, int(acct.get("posts_per_run", 1)))
        picks = llm.json(system=s, user=u, schema=writer.PICK_SCHEMA)["picks"]
    chosen = []
    for pk in picks:
        i = int(pk["index"]) - 1
        if 0 <= i < min(limit, len(cands)):
            c = cands[i]
            chosen.append({"key": c.key, "title": c.title, "link": c.link, "source": c.source,
                           "summary": c.summary, "angle": pk.get("angle", ""), "reason": pk.get("reason", "")})
    if not chosen:
        raise RuntimeError("편집장이 고른 번호가 후보 범위를 벗어났습니다")
    data = {"candidates": rows, "chosen": chosen, "failed_sources": failed, "n_candidates": len(cands),
            "provider": llm.last_provider}
    (out / "topic.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    progress(f"후보 {len(cands)}건 → 선정: {chosen[0]['title'][:60]}")
    return data


def step_write(cfg: dict, acct: dict, p: writer.Profile, refs: str, llm: LLM, out: Path, topic: dict, progress,
               seed_feedback: str = "", prev_article: dict | None = None) -> dict:
    """조사(소재 원문 + 같은 주제 기사·블로그) → 기사 한 편 → 글쓰기 전문가 검수. out/article.json + article.md."""
    posts = []
    for cand in topic["chosen"]:
        if not cand.get("article"):
            progress("소재 원문 읽는 중")
            art = sources.fetch_article(cand["link"])
            art["link_articles"] = []
            for link in art.get("links", [])[:2]:      # 공식 출처가 있으면 그 본문·사진도 같이
                more = sources.fetch_article(link, max_chars=2500)
                if more.get("text"):
                    art["text"] += f"\n\n[참고 링크 {link}]\n" + more["text"]
                    art["link_articles"].append({"link": link, "title": more.get("title", ""), "images": more.get("images", [])})
            cand["article"] = art
        if not cand.get("related"):
            progress("같은 주제의 기사·블로그 찾는 중")
            try:
                qs, qu = writer.query_prompt(cand)
                queries = llm.json(system=qs, user=qu, schema=writer.QUERY_SCHEMA)["queries"]
            except LLMError:
                queries = [cand["title"][:40]]
            cand["queries"] = queries
            cand["related"] = research.related_articles(queries, exclude={cand["link"]}, progress=progress)
        (out / "topic.json").write_text(json.dumps(topic, ensure_ascii=False, indent=1), encoding="utf-8")
        block = research.research_prompt_block(cand["related"])
        article, verdict = writer.generate_article(llm, p, refs, cand, block, seed_feedback=seed_feedback,
                                                   prev_article=prev_article, progress=progress)
        posts.append({"candidate": {k: v for k, v in cand.items() if k not in ("article", "related")},
                      "article": article, "verdict": verdict, "provider": llm.last_provider})
    data = {"posts": posts}
    (out / "article.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "article.md").write_text("\n\n---\n\n".join(article_markdown(x) for x in posts), encoding="utf-8")
    return data


def article_markdown(item: dict) -> str:
    """사람이 읽고 확인할 기사 본문(마크다운)."""
    a, v = item["article"], item.get("verdict", {})
    lines = [f"# {a['title']}", f"_{a.get('subtitle', '')}_", ""]
    for i, para in enumerate(a.get("paragraphs", []), 1):
        lines += [f"## {i}. {para.get('heading', '')}", para.get("text", ""), ""]
    lines += ["---", "**캡션**", a.get("caption", ""), " ".join(a.get("hashtags", [])), "",
              f"**검수** {v.get('total')}점 · {v.get('verdict')} — {v.get('feedback', '')}"]
    if v.get("better_titles"):
        lines.append("제목 대안: " + " / ".join(v["better_titles"]))
    lines += ["", "**출처**"] + [f"- {c.get('text')} — {c.get('source')}" for c in a.get("claims", [])]
    return "\n".join(lines)


def step_card(cfg: dict, acct: dict, p: writer.Profile, llm: LLM, out: Path, written: dict, progress) -> dict:
    """기사 → 카드 계획(문단마다 한 장으로 요약 + 사진 번호) → 렌더."""
    import insta_cards as cards

    topic = json.loads((out / "topic.json").read_text(encoding="utf-8"))
    result = []
    for i, item in enumerate(written["posts"], 1):
        cand = next((c for c in topic["chosen"] if c["key"] == item["candidate"]["key"]), topic["chosen"][0])
        images = research.image_candidates(cand.get("article") or {}, cand.get("related") or [], main_url=cand["link"])
        progress(f"사진 후보 {len(images)}장")
        plan = writer.plan_cards(llm, p, item["article"], images, progress=progress)
        d = out / f"post{i}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        paths = cards.render_cards(plan, d, template=p.template, theme=p.theme,
                                   handle=acct.get("handle") or p.handle, progress=progress)
        preview = cards.preview_strip(paths, d / "preview.jpg")
        result.append({"dir": str(d), "files": [str(x) for x in paths], "preview": str(preview)})
    (out / "cards.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"cards": result}


def step_upload(cfg: dict, acct: dict, out: Path, written: dict, rendered: dict, args, progress) -> dict:
    import insta_publisher as pub

    token, user_id = pub.account_env(args.account)
    ig = pub.Instagram(token, user_id)
    today = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    results = []
    for item, card in zip(written["posts"], rendered["cards"]):
        post = item["article"]
        stamp = datetime.now(KST).strftime("%H%M%S")
        urls = pub.upload_public([Path(x) for x in card["files"]], f"insta/{args.account}/{today}-{stamp}")
        progress(f"이미지 {len(urls)}장 공개 URL 준비")
        caption = post["caption"].rstrip() + "\n\n" + " ".join(post["hashtags"])
        res = pub.publish_carousel(ig, urls, caption, post.get("alt_text", ""), progress=progress)
        row = {"date": today, "account": args.account, "key": item["candidate"]["key"],
               "title": item["candidate"]["title"], "hook": post["title"], "media_id": res["media_id"],
               "permalink": res["permalink"], "image_urls": urls, "provider": item.get("provider", "")}
        append_posted(args.account, row)
        results.append(row)
        progress(f"게시 완료 {res['permalink']}")
    commit_data(args.account, today)
    (out / "upload.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"published": results}


def commit_data(account: str, today: str) -> None:
    """게시 기록(data/insta/<계정>/posted.jsonl)을 로컬 커밋해 둔다. push 는 report_status 가 한다."""
    repo = HERE.parent.parent
    if not (repo / ".git").exists():
        return
    rel = str(posted_path(account).relative_to(repo))
    subprocess.run(["git", "-C", str(repo), "add", rel], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", f"insta({account}): 게시 기록 {today}"], check=False)


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    acct = (cfg.get("accounts") or {}).get(args.account)
    if not acct:
        raise RuntimeError(f"설정에 없는 계정: {args.account}")
    p, refs = load_profile(acct["profile"])
    llm = LLM(list(cfg.get("llm_providers") or ["claude_cli", "gemini"]), gemini_model=cfg.get("gemini_model") or "gemini-2.5-flash")
    today = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    out = HERE / "out" / args.account / today
    out.mkdir(parents=True, exist_ok=True)
    until = STEPS.index(args.until) if args.until else len(STEPS) - 1
    tasks: dict[str, tuple[bool, str]] = {}
    lines: list[str] = []

    def cached(name: str):
        f = out / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if args.resume and f.exists() else None

    progress("소재 고르는 중")
    topic = cached("topic") or step_topic(cfg, acct, p, llm, out, args, progress)
    tasks["topic"] = (True, f"후보 {topic['n_candidates']}건 중 '{topic['chosen'][0]['title'][:40]}'")
    lines += [f"[소재] {c['title']} — {c['source']}" for c in topic["chosen"]]
    if until < 1:
        return _partial(tasks, lines, len(load_posted(args.account)))

    progress("글 쓰는 중")
    written = None if args.revise else cached("article")
    if written is None:
        seed = ""
        prev_article = None
        prev = out / "article.json"
        if args.revise and prev.exists():        # 다듬기: 이전 기사를 주고 지적된 부분만 고치게 한다
            try:
                prev_post = json.loads(prev.read_text(encoding="utf-8"))["posts"][0]
                seed = str(prev_post["verdict"].get("feedback", ""))
                prev_article = prev_post["article"]
            except (KeyError, IndexError, ValueError):
                seed = ""
        if args.feedback:                        # 사용자가 카드를 보고 직접 준 지적
            seed = (seed + "\n" if seed else "") + "[사용자 지적 — 반드시 반영]\n" + args.feedback
        for stale in ("cards.json",):
            (out / stale).unlink(missing_ok=True)
        written = step_write(cfg, acct, p, refs, llm, out, topic, progress, seed_feedback=seed, prev_article=prev_article)
    v = written["posts"][0]["verdict"]
    ok_write = v.get("verdict") == "pass"
    tasks["write"] = (ok_write, f"검수 {v.get('total')}점 ({written['posts'][0].get('provider', '')})")
    lines.append(f"[기사] {written['posts'][0]['article']['title']} · 검수 {v.get('total')}점 · {out / 'article.md'}")
    if not ok_write:
        lines.append(f"[보류] 검수 미달: {str(v.get('feedback', ''))[:120]}")
        return {"counts": {"new": 0, "failed": 1, "total": len(load_posted(args.account))}, "lines": lines, "tasks": tasks}
    if until < 2:
        return _partial(tasks, lines, len(load_posted(args.account)))

    progress("카드 만드는 중")
    rendered = cached("cards") or step_card(cfg, acct, p, llm, out, written, progress)
    if "cards" not in rendered:
        rendered = {"cards": rendered}
    tasks["card"] = (True, f"카드 {len(rendered['cards'][0]['files'])}장")
    if until < 3 or args.dry_run:
        lines.append(f"[카드] {rendered['cards'][0]['preview']}")
        return _partial(tasks, lines, len(load_posted(args.account)))

    progress("올리는 중")
    uploaded = step_upload(cfg, acct, out, written, rendered, args, progress)
    n = len(uploaded["published"])
    tasks["upload"] = (n > 0, f"{n}건 게시")
    lines += [f"[게시] {r['permalink']}" for r in uploaded["published"]]
    return {"counts": {"new": n, "failed": 0, "total": len(load_posted(args.account))}, "lines": lines, "tasks": tasks}


def _partial(tasks: dict, lines: list[str], total: int) -> dict:
    return {"counts": {"new": 0, "failed": 0, "total": total}, "lines": lines, "tasks": tasks}


# ───────────────────────── 아래는 템플릿 그대로(+계정 옵션) ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="게시·보고 없이 카드까지만")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    p.add_argument("--account", default=os.environ.get("INSTA_ACCOUNT", ""), help="계정 이름 (config accounts 키)")
    p.add_argument("--until", choices=STEPS, default="", help="이 단계까지만 실행")
    p.add_argument("--resume", action="store_true", help="out/ 의 중간 결과를 이어서")
    p.add_argument("--pick", type=int, default=0, help="후보 N번을 강제 선택")
    p.add_argument("--revise", action="store_true", help="지난 검수 지적을 반영해 기사를 다시 쓴다(--resume 과 함께)")
    p.add_argument("--feedback", default="", help="다듬기에 넣을 사용자 지적(--revise 와 함께). 줄바꿈 가능")
    p.add_argument("--date", default="", help="출력 폴더 날짜 (기본 오늘)")
    a = p.parse_args(argv)
    return a


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # 개인 설정(ai-side/…/config.yaml)에 env: 블록이 있으면 환경변수로 (이 PC 에서 시험할 때)
    for k, v in (cfg.get("env") or {}).items():
        os.environ.setdefault(k, str(v))
    return cfg


def build_summary(counts: dict, elapsed_sec: float) -> str:
    names = {"new": "게시", "failed": "실패", "total": "누적"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return ", ".join(parts)


def build_tasks(cfg: dict, task_results: dict) -> list[dict]:
    out: list[dict] = []
    for tid in cfg.get("tasks") or []:
        if tid not in task_results:
            out.append({"id": tid, "status": "idle", "summary": ""})
            continue
        ok, text = task_results[tid]
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg: dict, args, **kw) -> None:
    repo = (cfg.get("office_repo") or "").strip()
    acct = (cfg.get("accounts") or {}).get(args.account) or {}
    if repo and report_status:
        report_status(repo, automation_id=f"insta_{args.account}", name=f"{AUTOMATION_NAME} · {args.account}",
                      dept=acct.get("dept", "research"), next_run=acct.get("next_run", ""),
                      link=acct.get("result_link", ""), workspace=cfg.get("office_workspace", "side"), **kw)


def run(argv: list[str], work=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    if not args.account:
        args.account = cfg.get("default_account", "")
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    work = work or do_work
    progress = lambda m: print(f"  · {m}")  # noqa: E731

    try:
        result = work(cfg, args, progress)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        summary = to_korean(exc) if not isinstance(exc, LLMError) else "글 생성기가 응답하지 않아요"
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"{summary} ({detail})", file=sys.stderr)
        if not args.dry_run and not args.until:
            _report(cfg, args, ok=False, summary=summary, log_lines=[summary, detail],
                    started_at=started_at, duration_sec=int(time.monotonic() - started))
        return 1

    counts = dict(result.get("counts") or {})
    lines = list(result.get("lines") or [])
    task_results = dict(result.get("tasks") or {})
    ok = counts.get("failed", 0) == 0 and all(v[0] for v in task_results.values())
    summary = build_summary(counts, time.monotonic() - started)
    print(summary)
    for line in lines:
        print("  " + line)
    if not args.dry_run and not args.until:
        _report(cfg, args, ok=ok, summary=summary, counts=counts, log_lines=[summary] + lines[:4],
                tasks=build_tasks(cfg, task_results), started_at=started_at,
                duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
