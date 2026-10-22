"""AI 사이트 모음 콘텐츠: "이거 불법 아냐? 싶은 무료 AI 사이트 5개" 같은 저장용 목록 카드

흐름:
  1) Product Hunt AI 신상 목록에서 후보를 모은다 (회사용·개발자용은 코드로 먼저 거름)
  2) AI가 평범한 인스타 사용자가 바로 써볼 만한 것을 고른다
  3) 사이트를 실제로 열어서: 안 열리거나 봇 차단 화면이면 빼고, 첫 화면을 캡처하고, 사이트 글을 모은다
  4) AI가 사이트 글을 근거로 원고를 쓴다 ("무료"·"가입 없이" 같은 말은 사이트 글에 근거가 있을 때만 → checker.py가 검사)

일주일에 2번(화·금)만 후보에 들어온다. 좋은 도구가 매일 나오지는 않아서.

사용법:
  python tools.py          # 후보만 보기 (AI·캡처 없이)
"""
import os
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
import trafilatura

import news
import tips

FEED = "https://www.producthunt.com/feed?category=artificial-intelligence"
TOOL_DAYS = (1, 4)  # 화(1)·금(4)
SITES_PER_CARD = 5
MAX_AGE_DAYS = 10
SOURCE_NAME = "AI 사이트 모음"

# 일반인용이 아닌 것: 꿀팁 재료 거름망 + 회사 영업·고객관리·광고·개발 도구
NOT_FOR_EVERYONE = re.compile(
    tips.NOT_FOR_EVERYONE.pattern + r"|B2B|sales|CRM|customer support|support team|recruit|ads\b|advertis|"
    r"marketing team|agency|devops|deploy|code review|\bcode\b|coding|engineer|workflow automation|"
    r"compliance|lead gen|outbound|GTM|SaaS|teams?\b|startup|founder|investor|crypto|trading",
    re.IGNORECASE,
)
# 봇 차단·오류 화면이면 캡처해도 쓸 수 없다
BLOCKED = re.compile(r"just a moment|verify you are human|access denied|attention required|"
                     r"enable javascript|404|page not found|captcha", re.I)


def is_tool_day(today: date | None = None) -> bool:
    if os.environ.get("FORCE_TOOLS"):
        return True
    return (today or date.today()).weekday() in TOOL_DAYS


def _seen_key(domain: str) -> str:
    return f"tool:{domain}"


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def fetch_candidates() -> list[dict]:
    """Product Hunt AI 신상 중 최근 것, 일반인용 아닌 것은 뺀다."""
    seen = news._load_seen()
    feed = feedparser.parse(FEED, agent="Mozilla/5.0 (chipmunk-news bot)")
    now = time.time()
    out, skipped = [], 0
    for e in feed.entries:
        published = e.get("published_parsed") or e.get("updated_parsed")
        if published and now - time.mktime(published) > MAX_AGE_DAYS * 86400:
            continue
        summary = e.get("summary", "")
        tagline = news._clean(summary.split("<a")[0]).strip()
        link = next(iter(re.findall(r'href="(https://www\.producthunt\.com/r/[^"]+)"', summary)), None)
        if not link or link in seen:
            continue
        if NOT_FOR_EVERYONE.search(f"{e.get('title', '')} {tagline}"):
            skipped += 1
            continue
        out.append({"name": e.get("title", "").strip(), "tagline": tagline, "ph_link": link})
    print(f"  Product Hunt: 후보 {len(out)}개 (일반인용 아님 {skipped}개 제외)")
    return out


def _page_text(url: str) -> str:
    """사이트 첫 화면과 요금 안내 글을 합친다 ("무료" 같은 말의 근거로 씀)."""
    texts = []
    for path in ("", "/pricing"):
        try:
            r = requests.get(url.rstrip("/") + path if path else url, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.ok:
                texts.append(trafilatura.extract(r.text) or "")
        except requests.RequestException:
            pass
    return "\n".join(t for t in texts if t)[:4000]


def check_sites(picked: list[dict], shots_dir: Path) -> list[dict]:
    """고른 후보를 실제로 열어 본다. 열리고, 차단 화면이 아니고, 이미 쓴 사이트가 아닌 것만 SITES_PER_CARD개."""
    import render

    seen = news._load_seen()
    shots_dir.mkdir(parents=True, exist_ok=True)
    ok = []
    for c in picked:
        try:
            url = requests.get(c["ph_link"], timeout=15, allow_redirects=True,
                               headers={"User-Agent": "Mozilla/5.0"}).url
        except requests.RequestException:
            print(f"   ✖ {c['name']}: 주소를 못 찾음")
            continue
        url = url.split("?")[0]
        domain = domain_of(url)
        if not domain or "producthunt.com" in domain or _seen_key(domain) in seen:
            continue
        shot = shots_dir / f"{domain.replace('.', '_')}.jpg"
        shown = render.shoot_site(url, shot)  # 화면에 보이는 글
        text = _page_text(url)
        if not shown or BLOCKED.search(shown[:300]) or len(shown) < 80:
            print(f"   ✖ {c['name']} ({domain}): 안 열리거나 차단 화면")
            shot.unlink(missing_ok=True)
            continue
        print(f"   ✔ {c['name']} ({domain})")
        ok.append({**c, "url": url, "domain": domain, "shot": str(shot),
                   "page_text": (shown + "\n" + text)[:4000]})
        if len(ok) == SITES_PER_CARD:
            break
    return ok


def to_card(model, sites: list[dict]) -> dict:
    """AI 원고(ToolsCard) + 확인한 사이트 정보 → 다른 카드와 같은 모양(slides)으로.
    주소·캡처는 AI가 아니라 코드가 넣는다 (AI가 주소를 지어내지 못하게)."""
    data = model.model_dump()
    items = data.pop("items")
    slides = []
    for it in items:
        k = it["site"]
        if not 0 <= k < len(sites):
            continue
        s = sites[k]
        slides.append({"heading": it["heading"], "body": it["note"], "bad": "", "good": "",
                       "site_index": k, "site": it["name"] or s["name"], "domain": s["domain"],
                       "url": s["url"], "shot": s["shot"]})
    stamp = date.today().strftime("%Y.%m")
    caption = data["caption"]
    if "기준" not in caption:  # 무료 범위 등은 바뀔 수 있어서 날짜를 꼭 남긴다
        caption = caption.replace("\n\n", f"\n\n({stamp} 기준 정보예요)\n\n", 1)
    return {**data, "caption": caption, "slides": slides, "kind": "tools", "source": SOURCE_NAME,
            "link": slides[0]["url"] if slides else "",
            "sites": [{k: s[k] for k in ("name", "url", "domain", "page_text")} for s in sites],
            "action_tip": data.get("action_tip", ""), "companies": [], "cover_type": "image"}


def model_items(card: dict) -> list[dict]:
    """고쳐 쓰기(revise)할 때 AI에게 보여줄 원래 모양(items)."""
    return [{"site": s["site_index"], "name": s["site"], "heading": s["heading"], "note": s["body"]}
            for s in card["slides"]]


def make_card(day: str) -> dict | None:
    """오늘의 AI 사이트 모음 원고 하나. 사이트가 모자라면 None."""
    import checker
    import writer

    cands = fetch_candidates()
    if len(cands) < SITES_PER_CARD:
        print("   ⚠️ 후보가 모자라서 이번엔 건너뛰어요")
        return None
    picked = [cands[i] for i in writer.pick_tools(cands, n=SITES_PER_CARD + 4)]
    print(f"   🧰 AI가 고른 후보 {len(picked)}개 → 사이트 열어보는 중")
    sites = check_sites(picked, Path("output") / day / "shots")
    if len(sites) < SITES_PER_CARD:
        print(f"   ⚠️ 쓸 수 있는 사이트가 {len(sites)}개뿐이라 이번엔 건너뛰어요")
        return None
    card = checker.fix_names(to_card(writer.write_tools_card(sites), sites))
    return card


def mark_used(card: dict) -> None:
    """한 번 소개한 사이트는 다시 안 쓰게 기록한다 (뉴스와 같은 data/seen.json)."""
    news.mark_seen([_seen_key(s["domain"]) for s in card.get("sites", [])])


if __name__ == "__main__":
    for c in fetch_candidates():
        print(f"- {c['name']}: {c['tagline']}")
