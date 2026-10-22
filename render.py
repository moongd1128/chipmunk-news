"""2단계: 원고(cards.json) → 카드뉴스 이미지(1080x1350 JPEG)

사용법:
  python render.py                 # 오늘 원고 전부
  python render.py 2026-10-18      # 특정 날짜
  python render.py 2026-10-18 3    # 특정 날짜의 3번째 원고만
  python render.py 2026-10-18 --refresh   # 표지 종류·이미지를 처음부터 다시 고르기
"""
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape
from playwright.sync_api import sync_playwright

import checker
import images

load_dotenv()

HANDLE = "@chipmunk.news.kr"  # 인스타 아이디 (바뀌면 여기만 고치기)
WIDTH, HEIGHT = 1080, 1350
DEFAULT_EMOJI = "🌰"

env = Environment(loader=FileSystemLoader("templates"), autoescape=True)


def _lines(text: str) -> Markup:
    """본문 글자: 줄바꿈은 <br>로, **핵심 단어**는 색 강조로 (나머지는 안전하게 이스케이프)."""
    html = str(escape(text)).replace("\n", "<br>")
    html = checker.HIGHLIGHT.sub(r'<b class="hl">\1</b>', html)
    return Markup(html.replace("**", ""))  # 짝 안 맞는 별표가 화면에 보이지 않게


env.filters["lines"] = _lines
template = env.get_template("card.html")


PHOTO_SLIDE = 1  # 사진을 넣을 본문 슬라이드 번호 (표지 말고 1장만)


def build_pages(card: dict, day: str, assets: dict) -> list[str]:
    """원고 하나를 표지 1장 + 본문 4장 + 마지막 1장의 HTML로 만든다.
    assets: images.cover_assets()의 결과 (표지 사진, 본문 사진, 로고)."""
    emojis = checker.EMOJI.findall(card["hook_title"])
    title = checker.EMOJI.sub("", card["hook_title"]).replace("️", "").strip()
    common = {"date": day.replace("-", "."), "source": card["source"], "handle": HANDLE,
              "kind_tag": card.get("kind", "news")}

    pages = [template.render(kind="cover", title=title, emoji=emojis[0] if emojis else DEFAULT_EMOJI,
                             subtitle=card["subtitle"], image=assets["cover"], logos=assets["logos"],
                             rivalry=assets.get("rivalry"),
                             focus=assets.get("focus"), **common)]
    tools = card.get("kind") == "tools"
    for i, s in enumerate(card["slides"], 1):
        if tools:  # AI 사이트 모음: 사이트 주소 + 화면 캡처 + 큰 글씨 2줄 + 작은 글씨 1줄
            shot = Path(s.get("shot", ""))
            pages.append(template.render(kind="site", index=i, heading=s["heading"], body=s["body"],
                                         domain=s["domain"], total=len(card["slides"]),
                                         shot=images._data_uri(shot.read_bytes()) if shot.is_file() else None,
                                         **common))
            continue
        pages.append(template.render(kind="slide", index=i, heading=s["heading"], body=s["body"],
                                     bad=s.get("bad"), good=s.get("good"),
                                     image=assets["slide"] if i == PHOTO_SLIDE else None, **common))
    pages.append(template.render(kind="end", takeaway=card["takeaway"], action_tip=card.get("action_tip"),
                                 share_target=card.get("share_target"),
                                 sites=[(s["site"], s["domain"]) for s in card["slides"]] if tools else None,
                                 **common))
    return pages


CACHE_DIR = Path("assets/cache")  # 글꼴·이모지 파일을 한 번 받아두고 재사용


class _Shooter:
    """브라우저를 한 번만 켜두고 계속 쓴다 (텔레그램 버튼 반응 속도를 위해).
    Playwright는 켠 스레드에서만 써야 해서, 전용 스레드 하나에서 모든 작업을 돌린다."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._page = None

    def _ensure_page(self):
        if self._page is None:
            self._pw = sync_playwright().start()
            # GitHub Actions에는 크롬이 이미 깔려 있어서 그걸 쓴다 (191MB 크롬을 받다가 멈추는 일이 잦아서)
            channel = "chrome" if os.environ.get("GITHUB_ACTIONS") else None
            self._browser = self._pw.chromium.launch(channel=channel)
            self._page = self._browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
            self._page.route(re.compile(r"(jsdelivr\.net|fonts\.googleapis\.com|fonts\.gstatic\.com)"), _cached_route)
        return self._page

    def _shoot(self, jobs: list[tuple[str, Path]]) -> None:
        page = self._ensure_page()
        for html, path in jobs:
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(path), type="jpeg", quality=92)

    def shoot(self, jobs: list[tuple[str, Path]]) -> None:
        self._pool.submit(self._shoot, jobs).result()

    def _shoot_site(self, url: str, path: Path) -> str:
        self._ensure_page()
        page = self._browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            try:
                page.goto(url, wait_until="load", timeout=30_000)
            except Exception:  # noqa: BLE001 - 느린 사이트는 뜬 데까지만
                pass
            page.wait_for_timeout(2500)
            # 쿠키 안내 창은 '동의'를 누르지 않고 화면에서만 숨긴다
            page.add_style_tag(content="[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],"
                                       "[aria-label*=cookie i]{display:none!important}")
            page.screenshot(path=str(path), type="jpeg", quality=85)
            return page.inner_text("body")[:3000]
        except Exception as e:  # noqa: BLE001
            print(f"   (캡처 실패: {e})")
            return ""
        finally:
            page.close()

    def shoot_site(self, url: str, path: Path) -> str:
        return self._pool.submit(self._shoot_site, url, path).result()


def _cached_route(route) -> None:
    """글꼴·CSS 요청은 디스크에 저장해 두고 다음부터는 인터넷 대신 그걸 쓴다."""
    url = route.request.url
    path = CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()
    meta = path.with_suffix(".type")
    if path.exists() and meta.exists():
        route.fulfill(body=path.read_bytes(), content_type=meta.read_text(), headers={"access-control-allow-origin": "*"})
        return
    resp = route.fetch()
    body = resp.body()
    if resp.ok:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        meta.write_text(resp.headers.get("content-type", "application/octet-stream"))
    route.fulfill(response=resp, body=body)


_shooter = _Shooter()


def shoot_site(url: str, path: Path) -> str:
    """사이트 첫 화면을 캡처하고, 화면에 보이는 글을 돌려준다 (AI 사이트 모음용). 실패하면 빈 글."""
    return _shooter.shoot_site(url, path)


def render(day: str, only: int | None = None, refresh: bool = False, cover_only: bool = False) -> list[Path]:
    """refresh=True면 표지 종류·후보 이미지를 처음부터 다시 고른다.
    cover_only=True면 표지 1장만 다시 찍는다 (텔레그램 버튼용, 빠름)."""
    day_dir = Path("output") / day
    cards_file = day_dir / "cards.json"
    cards = json.loads(cards_file.read_text(encoding="utf-8"))
    made = []
    for n, card in enumerate(cards, 1):
        if only and n != only:
            continue
        out_dir = day_dir / f"card_{n:02d}"
        out_dir.mkdir(exist_ok=True)
        print(f"🎨 [{n}/{len(cards)}] {card['hook_title']}")
        if refresh or "image" not in card:
            images.prepare(card)
            cards_file.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        assets = images.cover_assets(card, out_dir)
        pages = build_pages(card, day, assets)
        if cover_only:
            pages = pages[:1]
        jobs = [(html, out_dir / f"{k:02d}.jpg") for k, html in enumerate(pages, 1)]
        _shooter.shoot(jobs)
        made += [path for _, path in jobs]
    print(f"✅ 이미지 {len(made)}장 저장됨: {day_dir}")
    return made


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    day = args[0] if args else date.today().isoformat()
    only = int(args[1]) if len(args) > 1 else None
    render(day, only, refresh="--refresh" in sys.argv)
    sys.stdout.flush()
    os._exit(0)  # 켜둔 브라우저까지 한 번에 정리하고 끝내기
