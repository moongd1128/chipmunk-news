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
    # 카드에 찍히는 날짜는 '만든 날'이 아니라 '지금(검수·발행하는 날)'.
    # 좋은 주제를 며칠 나눠 올려도 게시물 날짜가 올리는 날과 맞게 ([발행] 직전에 다시 찍으니까)
    common = {"date": date.today().strftime("%Y.%m.%d"), "source": card["source"], "handle": HANDLE,
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
            page.add_style_tag(content=_HIDE_COOKIES)  # 쿠키 안내는 '동의' 없이 화면에서만 숨김
            page.screenshot(path=str(path), type="jpeg", quality=85)
            return page.inner_text("body")[:3000]
        except Exception as e:  # noqa: BLE001
            print(f"   (캡처 실패: {e})")
            return ""
        finally:
            page.close()

    def shoot_site(self, url: str, path: Path) -> str:
        return self._pool.submit(self._shoot_site, url, path).result()

    def _scan_site(self, url: str, out_dir: Path, width: int, height: int, max_tiles: int = 6) -> list[tuple[float, Path]]:
        """사이트를 마우스 휠로 내려가며 구간마다 찍는다. [(휠로 내린 거리, 사진)] — 녹화 때 같은 거리만큼 내리면 같은 장면."""
        import hashlib as _h

        self._ensure_page()
        out_dir.mkdir(parents=True, exist_ok=True)
        page = self._browser.new_page(viewport={"width": width, "height": height})
        tiles, last, y = [], None, 0.0
        try:
            try:
                page.goto(url, wait_until="load", timeout=30_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(1500)
            page.add_style_tag(content=_HIDE_COOKIES)
            page.mouse.move(width / 2, height / 2)
            for j in range(max_tiles):
                path = out_dir / f"tile_{j}.jpg"
                page.screenshot(path=str(path), type="jpeg", quality=60, scale="css")
                digest = _h.sha1(path.read_bytes()).hexdigest()
                if digest == last:  # 더 안 내려가면(페이지 끝) 그만
                    path.unlink()
                    break
                last = digest
                tiles.append((y, path))
                step = height * 0.85
                for _ in range(10):
                    page.mouse.wheel(0, step / 10)
                    page.wait_for_timeout(40)
                y += step
                page.wait_for_timeout(700)  # 부드러운 스크롤·나타나는 효과가 끝날 때까지
        finally:
            page.close()
        return tiles

    def scan_site(self, url: str, out_dir: Path, width: int, height: int) -> list[tuple[float, Path]]:
        return self._pool.submit(self._scan_site, url, out_dir, width, height).result()

    def _record_site(self, url: str, out_dir: Path, width: int, height: int, seconds: float,
                     target_y: float = 0.0) -> tuple[Path, float]:
        """사이트를 열고, 고른 장면(target_y: 구간 찍을 때 휠로 내린 거리)까지 천천히 내려가서 멈추는 모습을 녹화한다.
        (영상 파일, 스크롤 시작부터 녹화 끝까지 걸린 초)"""
        import time

        self._ensure_page()
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx = self._browser.new_context(viewport={"width": width, "height": height},
                                        record_video_dir=str(out_dir), record_video_size={"width": width, "height": height})
        started = time.time()
        page = ctx.new_page()
        try:
            try:
                page.goto(url, wait_until="load", timeout=30_000)
            except Exception:  # noqa: BLE001 - 느린 사이트는 뜬 데까지만
                pass
            page.wait_for_timeout(1500)
            page.add_style_tag(content=_HIDE_COOKIES)
            page.mouse.move(width / 2, height / 2)
            # 화면에 나오는 건 마지막 '천천히 다가가는' 부분만. 그 전까지는 녹화에 안 쓰는 구간에서 미리 내려 둔다
            approach = height * 0.3 if target_y > 0 else height * 0.12
            before = max(0.0, target_y - approach)
            done = 0.0
            while done < before:  # 구간 찍을 때와 같은 방식(작게 나눠서)으로 내려야 같은 장면에 도착
                step = min(height * 0.085, before - done)
                page.mouse.wheel(0, step)
                done += step
                page.wait_for_timeout(40)
            page.wait_for_timeout(700)  # 부드러운 스크롤·나타나는 효과가 멈출 때까지
            offset = time.time() - started
            # 마우스 휠로 처음엔 조금 빠르게, 점점 천천히 다가가서 멈춘다 (나머지 시간은 멈춘 화면을 보여줌)
            frames = int(seconds * 30 * 0.55)
            for k in range(frames):
                page.mouse.wheel(0, approach * 2 * (1 - k / frames) / frames)
                page.wait_for_timeout(1000 / 30)
            page.wait_for_timeout(max(0.0, offset + seconds + 0.3 - (time.time() - started)) * 1000)
        finally:
            video = page.video
            tail = time.time() - started - offset  # 스크롤 시작 ~ 녹화 끝
            ctx.close()
        # 녹화 영상의 시계는 실제 시계와 어긋날 수 있어서(첫 화면이 늦게 뜨면 앞부분이 빠짐),
        # 시작 시각이 아니라 '끝에서 몇 초 전'으로 돌려준다 → reels.py가 영상 길이에서 빼서 자른다
        return Path(video.path()), tail

    def record_site(self, url: str, out_dir: Path, width: int, height: int, seconds: float,
                    target_y: float = 0.0) -> tuple[Path, float]:
        return self._pool.submit(self._record_site, url, out_dir, width, height, seconds, target_y).result()

    def _shoot_frames(self, html: str, out_dir: Path, width: int, height: int, seconds: float, fps: int) -> int:
        """render(t) 함수가 있는 HTML을 1/fps초마다 한 장씩 찍는다 (글씨가 또렷한 움직이는 릴스용). 찍은 장 수."""
        self._ensure_page()
        out_dir.mkdir(parents=True, exist_ok=True)
        page = self._browser.new_page(viewport={"width": width, "height": height})
        try:
            page.route(re.compile(r"(jsdelivr\.net|fonts\.googleapis\.com|fonts\.gstatic\.com)"), _cached_route)
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            frames = int(seconds * fps)
            for k in range(frames):
                page.evaluate(f"render({k / fps})")
                page.screenshot(path=str(out_dir / f"f_{k:04d}.jpg"), type="jpeg", quality=90)
            return frames
        finally:
            page.close()

    def shoot_frames(self, html: str, out_dir: Path, width: int, height: int, seconds: float, fps: int) -> int:
        return self._pool.submit(self._shoot_frames, html, out_dir, width, height, seconds, fps).result()

    def _shoot_png(self, html: str, path: Path, width: int, height: int) -> None:
        """투명 배경 PNG로 찍는다 (릴스 위에 얹을 글씨 판)."""
        self._ensure_page()
        page = self._browser.new_page(viewport={"width": width, "height": height})
        try:
            page.route(re.compile(r"(jsdelivr\.net|fonts\.googleapis\.com|fonts\.gstatic\.com)"), _cached_route)
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(path), type="png", omit_background=True)
        finally:
            page.close()

    def shoot_png(self, html: str, path: Path, width: int, height: int) -> None:
        self._pool.submit(self._shoot_png, html, path, width, height).result()


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


def scan_site(url: str, out_dir: Path, width: int, height: int) -> list[tuple[float, Path]]:
    """사이트를 위→아래로 구간마다 찍는다 (AI가 가장 직관적인 장면을 고르게). [(내린 거리, 사진)]"""
    return _shooter.scan_site(url, out_dir, width, height)


def record_site(url: str, out_dir: Path, width: int, height: int, seconds: float,
                target_y: float = 0.0) -> tuple[Path, float]:
    """고른 장면(target_y)까지 천천히 내려가 멈추는 모습을 녹화한다 (움직이는 릴스용).
    (영상 파일, 스크롤 시작부터 녹화 끝까지 걸린 초)"""
    return _shooter.record_site(url, out_dir, width, height, seconds, target_y)


# 쿠키 안내 창은 '동의'를 누르지 않고 화면에서만 숨긴다
_HIDE_COOKIES = ("[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],"
                 "[aria-label*=cookie i]{display:none!important}")


def shoot_frames(html: str, out_dir: Path, width: int, height: int, seconds: float, fps: int = 30) -> int:
    """render(t)가 있는 HTML을 한 장씩 찍는다 (꿀팁·뉴스 움직이는 릴스용). 찍은 장 수."""
    return _shooter.shoot_frames(html, out_dir, width, height, seconds, fps)


def shoot_png(html: str, path: Path, width: int, height: int) -> None:
    """투명 배경 PNG로 찍는다 (릴스 위 글씨 판)."""
    _shooter.shoot_png(html, path, width, height)


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
