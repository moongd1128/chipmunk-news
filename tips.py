"""AI 꿀팁 재료 수집: AI 회사·서비스의 공식 블로그와 업데이트 소식

꿀팁은 지어내면 안 되니까 공식 글만 쓴다. 이미 쓴 글은 news.py와 같은 기록(data/seen.json)으로 거른다.
"""
import re
import time

import feedparser

import news

# 독자(AI를 더 잘 쓰고 싶은 사람: 직장인·크리에이터·1인 사업자·대학생 등)에게 쓸모없는 주제: 개발자용, 대기업 관리자용, 학교 행정, 기업 제휴·도입 사례, 정책·연구 등
# 제목에 이런 말이 있으면 꿀팁 재료에서 미리 뺀다 (AI가 가끔 지시를 무시해서 코드로 확실하게)
NOT_FOR_EVERYONE = re.compile(
    r"BigQuery|Vertex|Looker|Cloud|API|SDK|developer|Codex|enterprise|admin|"
    r"Classroom|teacher|educator|school|partner|brings .+ (into|to) ChatGPT|customer|"
    r"case study|hotel|bank|government|sovereign|security|compliance|policy|research|safety|"
    r"invest|funding|hiring|economic|nonprofit|healthcare|"
    # 관리자 설정·보안·주간 요약·기업 사례 ("A사가 OO를 76배 줄였다" 같은 글)
    r"configure|encrypt|cryptograph|Assured|Recap|Carrier|plugin|\bcuts\b|\bwith OpenAI\b|"
    r"responsibly|midterm|election|evaluator|Azure|insider|mission",
    re.IGNORECASE,
)

# 소스: (주소, 제목에 꼭 있어야 하는 말)
# OpenAI·앤트로픽·마이크로소프트 블로그는 대부분 기업 사례·정책 글이라,
# 일반인이 쓰는 제품 이름이 제목에 있는 글만 꿀팁 재료로 쓴다
TIP_FEEDS = {
    "Google Gemini": ("https://blog.google/products/gemini/rss/", None),
    "Google AI": ("https://blog.google/technology/ai/rss/", None),
    "Google Workspace": ("https://workspaceupdates.googleblog.com/feeds/posts/default", None),
    "OpenAI": ("https://openai.com/news/rss.xml", re.compile(r"ChatGPT|Sora", re.I)),
    "Anthropic": ("https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml",
                  re.compile(r"Claude", re.I)),
    "Notion": ("https://www.notion.com/releases/rss.xml", None),
    "Microsoft": ("https://blogs.microsoft.com/feed/", re.compile(r"Copilot", re.I)),
}
MAX_AGE_DAYS = 14  # 꿀팁은 뉴스보다 오래 유효해서 2주까지 본다


def fetch_tip_sources() -> list[dict]:
    seen = news._load_seen()
    now = time.time()
    out = []
    for source, (url, must_have) in TIP_FEEDS.items():
        feed = feedparser.parse(url, agent="Mozilla/5.0 (chipmunk-news bot)")
        count = skipped = 0
        for e in feed.entries:
            link = e.get("link")
            published = e.get("published_parsed") or e.get("updated_parsed")
            if not link or link in seen:
                continue
            if not published or now - time.mktime(published) > MAX_AGE_DAYS * 86400:
                continue
            title = e.get("title", "")
            if NOT_FOR_EVERYONE.search(title) or (must_have and not must_have.search(title)):
                skipped += 1
                continue
            out.append({"source": source, "title": e.get("title", "").strip(), "link": link,
                        "summary": news._clean(e.get("summary", ""))[:600]})
            count += 1
        print(f"  {source}: 새 글 {count}개" + (f" (일반인용 아님 {skipped}개 제외)" if skipped else ""))
    return out
