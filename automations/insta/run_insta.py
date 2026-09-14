"""인스타그램 게시글 자동화 — 소재(topic) → 글(write: 조사·기사·검수) → 카드(card: 요약·사진·렌더) → 업로드(upload).

실행 방식(--mode, 사용자 결정 2026-09-11 "주제는 내가 검토한 뒤 만든다"):
  topics   매일 06:30 — 후보 10개를 골라 public/review/<사무실>/<자동화>.json 에 저장 (대시보드 검토 칸이 읽음)
  auto     매일 07:30 — 예약이 없으면 편집장 1순위를 자동 선택해 바로 게시 (사용자 결정 2026-09-12)
  queue    사이트에서 고른 후보(--picks id,id)를 예약에 넣는다: N개 → 24÷N 시간 간격. 첫 개는 바로 게시
  publish  매시 정각 — 예약 시각이 된 것을 기사→카드→게시
  run      (예전 방식) 후보 중 1건을 골라 바로 게시. 이 PC 시험용

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
import insta_review as review  # noqa: E402
import insta_sources as sources  # noqa: E402
import insta_watch as watch  # noqa: E402
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
    chosen = [c for c in chosen if not review.is_repeat(c, recent)] or chosen
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
            if research.is_social(cand["link"]):
                # 참고 계정(인스타) 글: 페이지를 긁지 않는다 — 캡션(summary)만 근거로 쓰고 사진은 다른 출처에서 찾는다
                art = {"title": cand["title"], "text": cand.get("summary", ""), "links": [], "images": []}
            else:
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
        art = item["article"]
        extra = [c.get("source", "") for c in art.get("claims", [])] + list(art.get("sources") or [])
        images = research.image_candidates(cand.get("article") or {}, cand.get("related") or [], main_url=cand["link"],
                                           extra_links=[u for u in extra if isinstance(u, str)])
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


def step_video(cfg: dict, acct: dict, p: writer.Profile, out: Path, written: dict, progress, found: dict | None = None) -> dict | None:
    """소재에 영상(공식 유튜브·X·공식 페이지 mp4)이 있으면 받아서 릴스로. 없거나 실패하면 None (카드로 간다)."""
    import insta_video as video

    if not video.tools_ok():
        progress("ffmpeg 없음 — 영상 건너뜀")
        return None
    topic = json.loads((out / "topic.json").read_text(encoding="utf-8"))
    item = written["posts"][0]
    cand = next((c for c in topic["chosen"] if c["key"] == item["candidate"]["key"]), topic["chosen"][0])
    found = found or video.find_video(cand)
    if not found:
        return None
    progress(f"영상 ({found['kind']}) {found['url'][:60]}")
    d = out / "reel"
    try:
        meta = video.download(found["url"], d, progress=progress)
        art = item["article"]
        credit = video.credit_text(meta)
        reel = video.make_reel(meta["path"], d / "reel.mp4", title=art["title"], sub=art.get("subtitle", ""), credit=credit,
                               brand=cards_brand(), handle=acct.get("handle") or p.handle, theme=p.theme, progress=progress)
        thumb = video.thumbnail(reel["path"], d / "thumb.jpg")
    except Exception as exc:  # noqa: BLE001 — 영상이 안 되면 카드로
        progress(f"영상 실패({type(exc).__name__}: {str(exc)[:80]}) — 카드로 진행")
        return None
    result = {"dir": str(d), "file": reel["path"], "thumb": str(thumb), "duration": reel["duration"], "credit": credit,
              "source_url": meta.get("page") or meta["url"], "video_url": meta["url"], "kind": found["kind"]}
    (out / "reel.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def cards_brand() -> str:
    import insta_cards as cards

    return cards.BRAND


def step_upload_reel(cfg: dict, acct: dict, out: Path, written: dict, reel: dict, args, progress) -> dict:
    import insta_publisher as pub

    token, user_id = pub.account_env(args.account)
    ig = pub.Instagram(token, user_id)
    today = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    item = written["posts"][0]
    post = item["article"]
    stamp = datetime.now(KST).strftime("%H%M%S")
    urls = pub.upload_public([Path(reel["file"]), Path(reel["thumb"])], f"insta/{args.account}/{today}-{stamp}")
    progress("영상 공개 URL 준비")
    caption = post["caption"].rstrip() + f"\n\n{reel['credit']}\n{reel['source_url']}\n\n" + " ".join(post["hashtags"])
    res = pub.publish_reel(ig, urls[0], caption, cover_url=urls[1] if len(urls) > 1 else "", progress=progress)
    row = {"date": today, "account": args.account, "key": item["candidate"]["key"], "title": item["candidate"]["title"],
           "hook": post["title"], "media_id": res["media_id"], "permalink": res["permalink"] or profile_link(acct), "video_url": urls[0],
           "posted_at": datetime.now(KST).isoformat(timespec="seconds"), "dm_keyword": post.get("dm_keyword", ""), "dm_text": post.get("dm_text", ""),
           "kind": "reel", "credit": reel["credit"], "provider": item.get("provider", "")}
    append_posted(args.account, row)
    progress(f"릴스 게시 완료 {res['permalink']}")
    commit_data(args.account, today)
    (out / "upload.json").write_text(json.dumps([row], ensure_ascii=False, indent=1), encoding="utf-8")
    return {"published": [row]}


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
               "posted_at": datetime.now(KST).isoformat(timespec="seconds"), "dm_keyword": post.get("dm_keyword", ""), "dm_text": post.get("dm_text", ""),
               "permalink": res["permalink"] or profile_link(acct), "image_urls": urls, "provider": item.get("provider", "")}
        append_posted(args.account, row)
        commit_data(args.account, today)             # 게시 직후 바로 기록·커밋 — 뒤에서 무슨 오류가 나도 다시 올리지 않게
        results.append(row)
        progress(f"게시 완료 {res['permalink']}")
    commit_data(args.account, today)
    (out / "upload.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"published": results}


def profile_link(acct: dict) -> str:
    return str(acct.get("result_link") or "https://www.instagram.com/")


def commit_paths(paths: list[Path], message: str) -> None:
    """저장소 안 파일을 로컬 커밋해 둔다. push 는 report_status 가 한다 (--until·--dry-run 이면 push 안 됨)."""
    repo = HERE.parent.parent
    if not (repo / ".git").exists():
        return
    rels = [str(x.resolve().relative_to(repo.resolve())) for x in paths if x.exists()]
    if not rels:
        return
    subprocess.run(["git", "-C", str(repo), "add", *rels], check=False)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=False)


def commit_data(account: str, today: str) -> None:
    commit_paths([posted_path(account)], f"insta({account}): 게시 기록 {today}")


# ───────────────────────── 검토 방식: topics / queue / publish ─────────────────────────

def review_file(cfg: dict, account: str) -> Path:
    return review.review_path(HERE.parent.parent, cfg.get("office_workspace", "side"), f"insta_{account}")


def do_topics(cfg: dict, acct: dict, p: writer.Profile, llm: LLM, args, progress) -> dict:
    """후보 N개(review_count, 기본 10)를 골라 검토 파일에 저장. 이미 올린 것·예약된 것은 뺀다."""
    path = review_file(cfg, args.account)
    data = review.load(path)
    exclude = {r.get("key", "") for r in load_posted(args.account)} | review.active_keys(data)
    watched, wfailed = watch.collect_watch(list(p.watch_accounts or []), exclude_keys=exclude, cap=p.watch_cap,
                                           per_account=p.watch_per_account, progress=progress)
    foreign, ffailed = watch.collect_watch(list(p.watch_foreign or []), flag="🇺🇸", max_age_hours=p.watch_foreign_hours,
                                           exclude_keys=exclude, cap=p.watch_cap, per_account=p.watch_per_account, progress=progress)
    cands, failed = sources.collect(p.sources, max_age_hours=p.max_age_hours, signals=p.source_signals,
                                    exclude_keys=exclude, progress=progress)
    cands = sources.cap_by_source(cands, p.source_caps or {})
    cands = foreign + watched + cands                       # 미국 원출처(IG) → 한국 참고 계정 → RSS
    failed = ffailed + wfailed + failed
    if not cands:
        raise RuntimeError("소재 후보가 없습니다 (출처 전부 실패: " + "; ".join(failed[:3]) + ")")
    limit = int(acct.get("candidates_to_llm", 30)) + len(watched) + len(foreign)
    want = int(acct.get("review_count", 10))
    recent = recent_titles(load_posted(args.account))
    rows = sources.as_prompt_rows(cands, limit)
    if recent:
        rows += "\n\n[이미 올린 주제 — 같은 내용·같은 소식은 고르지 않는다]\n" + "\n".join(f"- {t}" for t in recent[-40:])
    s_, u_ = writer.pick_prompt(p, rows, want)
    picks = llm.json(system=s_, user=u_, schema=writer.PICK_SCHEMA)["picks"]
    chosen = []
    for pk in picks:
        i = int(pk["index"]) - 1
        if 0 <= i < min(limit, len(cands)):
            c = cands[i]
            chosen.append({"key": c.key, "title": c.title, "link": c.link, "source": c.source,
                           "published": c.published.isoformat(timespec="minutes") if c.published else "",
                           "summary": c.summary[:300], "angle": pk.get("angle", ""), "reason": pk.get("reason", ""),
                           "title_ko": pk.get("title_ko", ""), "gap": bool(pk.get("gap")),
                           "video": ("video" in c.signals) or video_mod().is_video_site(c.link)})
    if not chosen:
        raise RuntimeError("편집장이 고른 번호가 후보 범위를 벗어났습니다")
    now = datetime.now(KST)
    data = review.set_candidates(data, chosen, now=now)
    review.save(path, data)
    commit_paths([path], f"insta({args.account}): 후보 {len(chosen)}건 {now:%Y-%m-%d %H:%M}")
    progress(f"후보 {len(cands)}건 → {len(chosen)}건 저장 (검토 대기)")
    lines = [f"[후보]{' 🇺🇸빈자리' if c.get('gap') else ''} {c['title'][:60]} — {c['source']}" for c in chosen]
    return {"counts": {"new": 0, "failed": 0, "total": len(load_posted(args.account))}, "lines": lines,
            "tasks": {"topic": (True, f"후보 {len(chosen)}건 · 사이트에서 골라 주세요")}}


def is_rate_limited(error: str) -> bool:
    """인스타 API 앱 호출 한도(code 4 'Application request limit reached') 인가."""
    e = (error or "").lower()
    return "request limit" in e or "(code 4)" in e or "rate limit" in e


def video_mod():
    import insta_video

    return insta_video


def do_queue(cfg: dict, acct: dict, p: writer.Profile, refs: str, llm: LLM, args, progress) -> dict:
    """사이트에서 고른 후보를 예약에 넣고(24÷N 시간 간격), 바로 만들 것(첫 개)은 이어서 만든다."""
    path = review_file(cfg, args.account)
    data = review.load(path)
    ids = [x.strip() for x in (args.picks or "").split(",") if x.strip()]
    now = datetime.now(KST)
    data, added = review.enqueue(data, ids, now=now, max_per_day=int(acct.get("max_per_day", 3)), slots=slots_of(acct))
    if not added:
        raise RuntimeError("예약할 후보가 없습니다 (이미 예약됐거나 후보 목록이 바뀌었어요 — 사이트를 새로 고쳐 주세요)")
    review.save(path, data)
    commit_paths([path], f"insta({args.account}): 예약 {len(added)}건 ({data.get('interval_hours')}시간 간격)")
    for q in added:
        progress(f"예약 {q['due'][11:16]} — {q['title'][:50]}")
    result = do_publish(cfg, acct, p, refs, llm, args, progress)
    result["lines"] = [f"[예약] {len(added)}건 · {data.get('interval_hours')}시간 간격"] + result["lines"]
    return result


def do_stats(cfg: dict, acct: dict, args, progress) -> dict:
    """올린 게시물의 실제 지표와 계정 팔로워 수를 받아 data/insta/<계정>/stats.json 에 저장·커밋 (성과 확인용)."""
    import insta_publisher as pub

    token, user_id = pub.account_env(args.account)
    ig = pub.Instagram(token, user_id)
    info = ig.account()
    rows = []
    for r in load_posted(args.account):
        if not r.get("media_id"):
            continue
        try:
            m = ig.metrics(r["media_id"])
        except Exception as exc:  # noqa: BLE001
            m = {"error": str(exc)[:120]}
        rows.append({"date": r.get("date"), "title": r.get("hook") or r.get("title"), "permalink": r.get("permalink"),
                     "kind": r.get("kind", "carousel"), **{k: m.get(k) for k in ("media_type", "views", "reach", "saved", "shares", "total_interactions",
                                                                                  "like_count", "comments_count", "insights_error", "error")}})
    now = datetime.now(KST)
    out = {"checked_at": now.isoformat(timespec="seconds"), "account": {k: info.get(k) for k in ("username", "followers_count", "follows_count", "media_count")},
           "posts": rows}
    path = posted_path(args.account).with_name("stats.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    commit_paths([path], f"insta({args.account}): 지표 {now:%Y-%m-%d %H:%M}")
    lines = [f"[계정] 팔로워 {info.get('followers_count')} · 게시물 {info.get('media_count')}"]
    for r in rows:
        lines.append(f"[지표] 조회 {r.get('views')} · 도달 {r.get('reach')} · 저장 {r.get('saved')} · 공유 {r.get('shares')} · 좋아요 {r.get('like_count')} · 댓글 {r.get('comments_count')} — {str(r.get('title'))[:30]}")
    for ln in lines:
        progress(ln)
    return {"counts": {"new": 0, "failed": 0, "total": len(rows)}, "lines": lines,
            "tasks": {"upload": (True, f"팔로워 {info.get('followers_count')} · 지표 {len(rows)}건")}}


def do_auto(cfg: dict, acct: dict, p: writer.Profile, refs: str, llm: LLM, args, progress) -> dict:
    """매일 07:30 KST — 아무도 안 골랐으면 편집장 1순위 후보(auto_pick 개수)를 바로 만들어 게시. 예약이 있으면 그냥 publish."""
    n = int(acct.get("auto_pick", 1))
    path = review_file(cfg, args.account)
    data = review.load(path)
    now = datetime.now(KST)
    posted = {r.get("key", "") for r in load_posted(args.account)}
    data, added = review.auto_pick(data, exclude_keys=posted, now=now, n=n, max_per_day=int(acct.get("max_per_day", 3)), slots=slots_of(acct))
    if added:
        review.save(path, data)
        commit_paths([path], f"insta({args.account}): 자동 선택 {len(added)}건 {now:%Y-%m-%d %H:%M}")
        for q in added:
            progress(f"자동 선택 — {q['title'][:50]}")
    else:
        progress("자동 선택 없음 (예약이 이미 있거나 후보가 없음)")
    result = do_publish(cfg, acct, p, refs, llm, args, progress)
    if added:
        result["lines"] = [f"[자동 선택] {len(added)}건 · 07:30 첫 게시"] + result["lines"]
    return result


def recent_titles(rows: list[dict], days: int = 21) -> list[str]:
    """최근 올린 글의 제목·소재 제목 — 같은 주제를 또 고르지 않게 편집장·자동 선택에 준다."""
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    out: list[str] = []
    for r in rows:
        if str(r.get("date", "")) >= cutoff:
            out += [str(r.get("hook") or ""), str(r.get("title") or "")]
    return [t for t in out if t]


def slots_of(acct: dict) -> tuple:
    """계정 설정의 고정 게시 시간대 (기본 07:30·12:30·18:30)."""
    return tuple(str(x) for x in (acct.get("slots") or review.DEFAULT_SLOTS))


def do_publish(cfg: dict, acct: dict, p: writer.Profile, refs: str, llm: LLM, args, progress) -> dict:
    """예약 시각이 된 항목을 하나씩 기사→카드→게시. 결과는 검토 파일에 표시. 첫 시간대(07:30) 창이면 예약이 없을 때 1순위를 자동 선택."""
    path = review_file(cfg, args.account)
    data = review.load(path)
    now = datetime.now(KST)
    slot = review.in_slot_window(now, slots_of(acct))
    if slot and int(acct.get("auto_pick", 1)) > 0:      # 시간대 창인데 그 칸이 비어 있으면 편집장 1순위를 자동 선택 (사용자 위임 2026-09-14)
        rows = load_posted(args.account)
        posted = {r.get("key", "") for r in rows}
        last = max((review._parse(r.get("posted_at")) for r in rows if r.get("posted_at")), default=None)
        data, added = review.auto_pick(data, exclude_keys=posted, now=now, n=int(acct.get("auto_pick", 1)), slots=slots_of(acct),
                                       posted_titles=recent_titles(rows), last_post=last)
        if added:
            review.save(path, data)
            commit_paths([path], f"insta({args.account}): 자동 선택 {len(added)}건 {now:%Y-%m-%d %H:%M}")
            for q in added:
                progress(f"자동 선택({slot}) — {q['title'][:50]}")
    due = review.due_items(data, now)
    tasks: dict[str, tuple[bool, str]] = {"topic": (True, review.summarize(data))}
    lines: list[str] = []
    made = failed = 0
    if not due:
        lines.append("[예약] 지금 만들 것 없음")
        return {"counts": {"new": 0, "failed": 0, "total": len(load_posted(args.account))}, "lines": lines, "tasks": tasks}
    for q in due:
        already = next((r for r in load_posted(args.account) if r.get("key") == q.get("key")), None)
        if already:                                  # 이미 올린 소재 — 다시 만들지 않는다 (중복 게시 사고 2026-09-13 재발 방지)
            data = review.mark(data, q["id"], "done", now=now, permalink=already.get("permalink", ""))
            review.save(path, data); commit_paths([path], f"insta({args.account}): 이미 게시됨 {q['title'][:40]}")
            lines.append(f"[건너뜀] 이미 올린 소재 — {q['title'][:40]}")
            continue
        data = review.mark(data, q["id"], "making", now=now)
        review.save(path, data); commit_paths([path], f"insta({args.account}): 만드는 중 {q['title'][:40]}")
        cand = {k: q.get(k, "") for k in ("key", "title", "link", "source", "summary", "angle")}
        try:
            res = make_post(cfg, acct, p, refs, llm, cand, args, progress)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            res = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}", "tasks": {}, "lines": [f"[실패] {q['title'][:40]} — {type(exc).__name__}"]}
        now = datetime.now(KST)
        if res["ok"]:
            made += 1
            data = review.mark(data, q["id"], "done", now=now, permalink=res.get("permalink", ""))
            msg = "게시"
        elif is_rate_limited(res.get("error", "")) and int(q.get("retries", 0)) < 2:
            # 앱 호출 한도(게시 전 단계에서 걸림) — 최대 2번까지 다음 시간대에 다시 시도. 게시 뒤 오류는 publisher 가 삼키므로 여기 오지 않는다
            slots = slots_of(acct)
            retry = review.slot_times(1, now + timedelta(minutes=30), slots=slots, taken=review.active_dues(data))[0]
            data = review.mark(data, q["id"], "queued", now=now, due=retry.isoformat(timespec="seconds"), error="", retries=int(q.get("retries", 0)) + 1)
            lines.append(f"[대기] 인스타 요청 한도 — {retry:%m/%d %H:%M} 에 다시 시도({int(q.get('retries', 0)) + 1}/2): {q['title'][:40]}")
            msg = "한도 대기"
        else:
            failed += 1
            data = review.mark(data, q["id"], "failed", now=now, error=res.get("error", ""))
            msg = "실패"
        review.save(path, data); commit_paths([path], f"insta({args.account}): {msg} {q['title'][:40]}")
        tasks.update(res.get("tasks", {}))
        lines += res.get("lines", [])
    tasks["topic"] = (True, review.summarize(data))
    return {"counts": {"new": made, "failed": failed, "total": len(load_posted(args.account))}, "lines": lines, "tasks": tasks}


def make_post(cfg: dict, acct: dict, p: writer.Profile, refs: str, llm: LLM, cand: dict, args, progress) -> dict:
    """소재 하나 → 기사 → 카드 → 게시. {ok, permalink, tasks, lines, error}"""
    stamp = datetime.now(KST).strftime("%Y-%m-%d")
    out = HERE / "out" / args.account / stamp / review.short_id(cand["key"])
    out.mkdir(parents=True, exist_ok=True)
    topic = {"chosen": [dict(cand)], "n_candidates": 0}
    (out / "topic.json").write_text(json.dumps(topic, ensure_ascii=False, indent=1), encoding="utf-8")
    tasks: dict[str, tuple[bool, str]] = {}
    lines: list[str] = []
    # 영상이 딸린 소재면 먼저 확인해 두고(값싼 검사), 릴스용 짧은 기사 규칙으로 쓴다
    found = None
    if acct.get("reels", True):
        import insta_video as video

        found = video.find_video(cand) if video.tools_ok() else None
        if found:
            p = writer.reel_profile(p)
            progress(f"영상 소재 ({found['kind']}) — 릴스용으로 씁니다")
    progress(f"글 쓰는 중 — {cand['title'][:50]}")
    written = step_write(cfg, acct, p, refs, llm, out, topic, progress)
    v = written["posts"][0]["verdict"]
    ok_write = v.get("verdict") == "pass"
    tasks["write"] = (ok_write, f"검수 {v.get('total')}점 ({written['posts'][0].get('provider', '')})")
    lines.append(f"[기사] {written['posts'][0]['article']['title']} · 검수 {v.get('total')}점")
    if not ok_write:
        return {"ok": False, "error": f"검수 미달 {v.get('total')}점", "tasks": tasks, "lines": lines + [f"[보류] {str(v.get('feedback', ''))[:100]}"]}
    reel = None
    if found:
        progress("영상 받는 중")
        reel = step_video(cfg, acct, p, out, written, progress, found=found)
    if reel:
        tasks["card"] = (True, f"릴스 {reel['duration']:.0f}초 · {reel['credit']}")
        lines.append(f"[릴스] {reel['duration']:.0f}초 · {reel['credit']}")
        if args.dry_run:
            lines.append(f"[릴스] {reel['file']} (dry-run: 게시 안 함)")
            return {"ok": True, "permalink": "", "tasks": tasks, "lines": lines}
        progress("릴스 올리는 중")
        uploaded = step_upload_reel(cfg, acct, out, written, reel, args, progress)
        n = len(uploaded["published"])
        tasks["upload"] = (n > 0, f"{n}건 게시(릴스)")
        lines += [f"[게시] {r['permalink']}" for r in uploaded["published"]]
        return {"ok": n > 0, "permalink": uploaded["published"][0]["permalink"] if n else "", "tasks": tasks, "lines": lines}
    progress("카드 만드는 중")
    rendered = step_card(cfg, acct, p, llm, out, written, progress)
    tasks["card"] = (True, f"카드 {len(rendered['cards'][0]['files'])}장")
    if args.dry_run:
        lines.append(f"[카드] {rendered['cards'][0]['preview']} (dry-run: 게시 안 함)")
        return {"ok": True, "permalink": "", "tasks": tasks, "lines": lines}
    progress("올리는 중")
    uploaded = step_upload(cfg, acct, out, written, rendered, args, progress)
    n = len(uploaded["published"])
    tasks["upload"] = (n > 0, f"{n}건 게시")
    lines += [f"[게시] {r['permalink']}" for r in uploaded["published"]]
    return {"ok": n > 0, "permalink": uploaded["published"][0]["permalink"] if n else "", "tasks": tasks, "lines": lines}


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    acct = (cfg.get("accounts") or {}).get(args.account)
    if not acct:
        raise RuntimeError(f"설정에 없는 계정: {args.account}")
    p, refs = load_profile(acct["profile"])
    llm = LLM(list(cfg.get("llm_providers") or ["claude_cli", "gemini"]), gemini_model=cfg.get("gemini_model") or "gemini-2.5-flash")
    if args.mode == "topics":
        return do_topics(cfg, acct, p, llm, args, progress)
    if args.mode == "queue":
        return do_queue(cfg, acct, p, refs, llm, args, progress)
    if args.mode == "publish":
        return do_publish(cfg, acct, p, refs, llm, args, progress)
    if args.mode == "auto":
        return do_auto(cfg, acct, p, refs, llm, args, progress)
    if args.mode == "stats":
        return do_stats(cfg, acct, args, progress)
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
    p.add_argument("--mode", choices=["run", "topics", "queue", "publish", "auto", "stats"], default=os.environ.get("INSTA_MODE", "run"),
                   help="run=1건 자동 게시(시험) / topics=후보 저장 / queue=고른 것 예약+첫 개 게시 / publish=예약된 것 게시")
    p.add_argument("--picks", default=os.environ.get("INSTA_PICKS", ""), help="queue 방식에서 고른 후보 id (쉼표)")
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
