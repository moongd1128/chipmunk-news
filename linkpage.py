"""프로필 링크 페이지: 인스타에 올린 카드의 원문 링크 모음 (GitHub Pages)

인스타 본문에는 링크를 못 넣으니, "원문 보고 싶다"는 사람이 프로필 링크로 오면
그날 올라간 카드 제목 + 원문 기사(꿀팁은 공식 글) 링크를 볼 수 있게 한다.

흐름:
  [발행] 성공 → publisher.py가 record()로 data/links.json에 한 줄 추가
  → pages.yml(GitHub Actions)이 build()로 site/index.html을 만들어 GitHub Pages에 올림

사용법:
  python linkpage.py build      # site/index.html 만들기
  python linkpage.py backfill   # 예전에 발행한 카드를 기록에 채워 넣기 (처음 한 번)
"""
import json
import shutil
import sys
import time
from html import escape
from pathlib import Path

LINKS_FILE = Path("data/links.json")  # data/는 state.py로 PC·GitHub이 같이 씀 (공개 저장소엔 안 올라감)
CHANGED_FLAG = Path(".links_changed")  # 버튼 처리 끝에 페이지를 다시 만들지 알려주는 표시
SITE_DIR = Path("site")
PROFILE_URL = "https://www.instagram.com/chipmunk.news.kr/"
MAX_ITEMS = 60  # 페이지에 보여줄 최근 게시물 수


def load() -> list[dict]:
    return json.loads(LINKS_FILE.read_text(encoding="utf-8")) if LINKS_FILE.exists() else []


def record(day: str, n: int, card: dict, cover_url: str) -> None:
    """발행한 카드 하나를 기록한다 (같은 카드면 덮어씀)."""
    items = [i for i in load() if i["id"] != f"{day}-{n}"]
    items.append({
        "id": f"{day}-{n}", "day": day, "kind": card.get("kind", "news"),
        "title": card["hook_title"], "subtitle": card.get("subtitle", ""),
        "source": card["source"], "link": card["link"], "cover": cover_url,
        "post": card.get("published", {}).get("permalink", ""),
        "at": card.get("published", {}).get("at") or int(time.time()),  # 인스타에 올라간 시각 (최신이 위로)
    })
    LINKS_FILE.parent.mkdir(exist_ok=True)
    LINKS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    CHANGED_FLAG.touch()


def backfill() -> None:
    """예전에 발행한 카드 중 기록에 없는 것을 채운다 (표지는 공개 저장소에 다시 올림)."""
    import publisher

    have = {i["id"] for i in load()}
    for cards_file in sorted(Path("output").glob("*/cards.json")):
        day = cards_file.parent.name
        for n, card in enumerate(json.loads(cards_file.read_text(encoding="utf-8")), 1):
            if card.get("status") != "published" or f"{day}-{n}" in have:
                continue
            cover = cards_file.parent / f"card_{n:02d}" / "01.jpg"
            url = publisher.upload_public(cover, f"{day}/card_{n:02d}/links_cover.jpg")
            record(day, n, card, url)
            print(f"➕ {day} {n}번: {card['hook_title']}")


def _item_html(i: dict) -> str:
    tag = "💡 꿀팁" if i["kind"] == "tip" else "📰 뉴스"
    source = f"{i['source']} 공식 글" if i["kind"] == "tip" else i["source"]
    post = (f'<a class="btn ghost" href="{escape(i["post"])}">인스타에서 보기</a>' if i.get("post") else "")
    return f"""
    <article class="item">
      <img class="cover" src="{escape(i['cover'])}" alt="" loading="lazy">
      <div class="info">
        <span class="tag {escape(i['kind'])}">{tag}</span>
        <h2>{escape(i['title'])}</h2>
        <p class="sub">{escape(i['subtitle'])}</p>
        <div class="btns">
          <a class="btn" href="{escape(i['link'])}">원문 보기 · {escape(source)}</a>
          {post}
        </div>
      </div>
    </article>"""


def build() -> Path:
    items = sorted(load(), key=lambda i: (i["day"], i["at"]), reverse=True)[:MAX_ITEMS]
    sections, day = [], None
    for i in items:
        if i["day"] != day:
            day = i["day"]
            sections.append(f'<h3 class="day">{day.replace("-", ".")}</h3>')
        sections.append(_item_html(i))
    body = "\n".join(sections) or '<p class="empty">곧 첫 소식이 올라와요 🌰</p>'

    SITE_DIR.mkdir(exist_ok=True)
    shutil.copy("assets/mascot/mascot_profile.jpg", SITE_DIR / "profile.jpg")
    html = TEMPLATE.replace("{{items}}", body).replace("{{profile_url}}", PROFILE_URL)
    out = SITE_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"🔗 링크 페이지 만듦: {out} ({len(items)}개)")
    return out


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>칩다람 | AI 뉴스·꿀팁 원문 모음</title>
<meta name="description" content="칩다람 카드뉴스의 원문 기사·공식 글 링크를 모아뒀어요.">
<link rel="icon" href="profile.jpg">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
  :root { --bg:#FFF7EC; --ink:#2B1D14; --muted:#8A6F5A; --accent:#F2762E; --soft:#F7E2C8; --white:#fff; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:"Pretendard",sans-serif; background:var(--bg); color:var(--ink); word-break:keep-all; }
  .wrap { max-width:560px; margin:0 auto; padding:28px 16px 48px; }
  header { text-align:center; }
  header img { width:88px; height:88px; border-radius:50%; box-shadow:0 8px 20px rgba(43,29,20,.12); }
  header h1 { margin-top:12px; font-size:22px; font-weight:800; }
  header p { margin-top:6px; font-size:15px; color:var(--muted); line-height:1.5; }
  .follow { display:inline-block; margin-top:14px; background:var(--ink); color:var(--white); text-decoration:none;
    font-weight:700; font-size:15px; padding:10px 20px; border-radius:999px; }
  .day { margin:28px 4px 10px; font-size:14px; color:var(--muted); font-weight:700; }
  .item { display:flex; gap:12px; background:var(--white); border-radius:18px; padding:12px; margin-bottom:10px;
    box-shadow:0 6px 16px rgba(43,29,20,.06); }
  .cover { width:84px; height:105px; object-fit:cover; border-radius:12px; flex-shrink:0; background:var(--soft); }
  .info { min-width:0; flex:1; }
  .tag { font-size:12px; font-weight:800; color:var(--accent); }
  .tag.tip { color:#B8860B; }
  .item h2 { margin-top:2px; font-size:16px; line-height:1.35; font-weight:800; }
  .sub { margin-top:3px; font-size:13px; color:var(--muted); line-height:1.4; }
  .btns { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
  .btn { font-size:13px; font-weight:700; text-decoration:none; color:var(--white); background:var(--accent);
    padding:7px 12px; border-radius:999px; }
  .btn.ghost { background:var(--soft); color:var(--ink); }
  .empty { text-align:center; margin-top:40px; color:var(--muted); }
  footer { margin-top:32px; text-align:center; font-size:12px; color:var(--muted); line-height:1.6; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <img src="profile.jpg" alt="칩다람">
    <h1>칩다람 | AI 뉴스·꿀팁</h1>
    <p>카드뉴스에 나온 원문 기사·공식 글을 모아뒀어요 🌰<br>궁금한 소식은 원문에서 더 자세히 보세요</p>
    <a class="follow" href="{{profile_url}}">인스타그램 팔로우하기</a>
  </header>
  <main>
{{items}}
  </main>
  <footer>매일 아침 업데이트 · @chipmunk.news.kr<br>원문의 저작권은 각 매체·회사에 있어요</footer>
</div>
</body>
</html>
"""


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        build()
    elif cmd == "backfill":
        from dotenv import load_dotenv

        load_dotenv()
        backfill()
    else:
        print(__doc__)
