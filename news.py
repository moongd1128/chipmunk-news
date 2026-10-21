"""1단계-1: 해외 AI 뉴스 RSS 수집"""
import json
import time
from pathlib import Path

import feedparser
import trafilatura

RSS_URLS = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Ars Technica": "https://arstechnica.com/ai/feed/",
    "MIT Tech Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "The Decoder": "https://the-decoder.com/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss",
}

SEEN_FILE = Path("data/seen.json")
MAX_AGE_HOURS = 48  # 이보다 오래된 기사는 버림


def _load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def mark_seen(links: list[str]) -> None:
    seen = _load_seen() | set(links)
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=1), encoding="utf-8")


def _clean(html: str) -> str:
    return (trafilatura.extract(f"<html><body>{html}</body></html>") or html).strip()


def fetch_latest_news() -> list[dict]:
    """모든 RSS에서 최근 기사 중 아직 안 쓴 것만 모아서 돌려준다."""
    seen = _load_seen()
    now = time.time()
    articles = []
    for source, url in RSS_URLS.items():
        feed = feedparser.parse(url, agent="Mozilla/5.0 (chipmunk-news bot)")
        if not feed.entries:
            print(f"  ⚠️ {source}: 기사를 못 가져왔어요")
            continue
        count = 0
        for entry in feed.entries:
            link = entry.get("link")
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if not link or link in seen:
                continue
            if published and now - time.mktime(published) > MAX_AGE_HOURS * 3600:
                continue
            articles.append({
                "source": source,
                "title": entry.get("title", "").strip(),
                "link": link,
                "summary": _clean(entry.get("summary", ""))[:600],
            })
            count += 1
        print(f"  {source}: 새 기사 {count}개")
    return articles


def fetch_article_body(url: str, fallback: str = "") -> str:
    """기사 본문을 가져온다. 실패하면 RSS 요약을 대신 쓴다."""
    downloaded = trafilatura.fetch_url(url)
    body = trafilatura.extract(downloaded) if downloaded else None
    return (body or fallback)[:6000]
