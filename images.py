"""카드뉴스 이미지 준비

흐름:
  1) prepare(card): 표지 종류·검색어를 정하고, Pixabay 후보를 모아 AI가 직접 보고 순위를 매긴다.
     결과는 card["image"]에 저장된다 → 텔레그램 [다른 사진] / [로고 표지로] 버튼이 이 값만 바꾸면 된다.
  2) cover_assets(card, out_dir): 지금 선택된 상태대로 표지·본문에 넣을 이미지/로고를 돌려준다.

card["image"] = {
  "mode": "logo" | "photo" | "text",    # 지금 표지 종류
  "companies": [...],                   # 로고 표지에 쓸 회사
  "candidates": [{"url", "thumb", "tags"}],
  "ranked": [후보 번호...],              # AI가 고른 순서
  "busy": [후보 번호...],                # 주제엔 맞지만 빽빽한 것 → 표지로 쓰면 흐림 효과
  "pos": 0,                              # ranked에서 지금 쓰는 위치 ([다른 사진]을 누르면 +1)
}
"""
import base64
import os
from pathlib import Path

import requests
from google.genai import errors, types

import logos

PIXABAY_URL = "https://pixabay.com/api/"
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
# AI로 그릴 때 스타일 (캐릭터·글자 없이 주제만)
IMAGE_STYLE = "editorial illustration, clean modern composition, vivid but tasteful colors, no characters or mascots, no text, no letters, no logos"
PER_SEARCH = 4  # 검색 1번에 가져올 후보 수 (검색어 3개 × 사진·일러스트 = 최대 24장을 AI가 봄)


def _pixabay(query: str, image_type: str) -> list[dict]:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    resp = requests.get(PIXABAY_URL, params={
        "key": key, "q": query, "image_type": image_type, "min_width": 1000,
        "safesearch": "true", "order": "popular", "per_page": PER_SEARCH,
    }, timeout=20)
    resp.raise_for_status()
    return resp.json().get("hits", [])


def collect_candidates(queries: list[str]) -> list[dict]:
    """검색어마다 사진·일러스트를 모은다 (중복 제거)."""
    seen, out = set(), []
    for q in queries:
        for image_type in ("photo", "illustration"):
            for h in _pixabay(q, image_type):
                if h["id"] in seen:
                    continue
                seen.add(h["id"])
                out.append({"url": h["largeImageURL"], "thumb": h["webformatURL"], "tags": h.get("tags", "")})
    return out


def prepare(card: dict) -> None:
    """표지 종류를 정하고 후보 이미지에 AI 순위를 매겨서 card["image"]에 저장한다."""
    import writer

    if not card.get("image_queries"):
        card.update(writer.suggest_image(card).model_dump())

    # 회사와 그 회사 제품이 같이 오면 하나로 (예: 오픈AI + 챗GPT → 챗GPT)
    companies = logos.merge_family([c for c in card.get("companies", []) if c in logos.COMPANIES])[:2]
    candidates = collect_candidates(card["image_queries"])
    print(f"   🖼️ 후보 {len(candidates)}장 ({', '.join(card['image_queries'])})")

    ranked, busy = [], []
    if candidates:
        thumbs = [requests.get(c["thumb"], timeout=20).content for c in candidates]
        ranked, busy = writer.pick_images(card, thumbs)
        print(f"   👀 AI가 고른 쓸 만한 이미지 {len(ranked)}장 (그중 빽빽해서 흐림 처리할 것 {len(busy)}장)")

    # 표지는 눈길 끄는 이미지가 1순위. 회사가 나오면 그 위에 로고 배지를 얹는다.
    # 쓸 만한 이미지가 없을 때만 로고 표지, 회사도 없으면 글자 표지.
    if ranked:
        mode = "photo"
    elif companies:
        mode = "logo"
    else:
        mode = "text"
    card["image"] = {"mode": mode, "companies": companies, "candidates": candidates,
                     "ranked": ranked, "busy": busy, "pos": 0,
                     "rivalry": bool(card.get("rivalry")) and len(companies) == 2}
    logo_txt = f" + 로고({' vs '.join(companies)})" if companies else ""
    print(f"   🧭 표지: {'사진' + logo_txt if mode == 'photo' else '로고' + logo_txt if mode == 'logo' else '글자'}")


def _is_photo(data: bytes) -> bool:
    """진짜 사진 파일인지 (만료된 주소는 사진 대신 'This URL is expired' 같은 글자가 온다)."""
    return len(data) > 2000 and (data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG")


def _cached_photo(path: Path, url: str) -> bytes | None:
    """받아 둔 사진이 있으면 그걸, 없으면 받아서 저장. 사진이 아니면(만료 등) None."""
    if path.exists():
        data = path.read_bytes()
        if _is_photo(data):
            return data
        path.unlink()  # 예전에 잘못 저장된 것(만료 글자)은 지운다
    try:
        data = requests.get(url, timeout=30).content
    except requests.RequestException:
        return None
    if not _is_photo(data):
        return None
    path.write_bytes(data)
    return data


def _data_uri(data: bytes) -> str:
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def cover_assets(card: dict, out_dir: Path) -> dict:
    """지금 선택된 상태대로 {"cover": 사진 URI|None, "slide": 사진 URI|None, "logos": [...]}를 돌려준다."""
    info = card.get("image") or {}
    ranked, pos = info.get("ranked", []), info.get("pos", 0)
    photos = []
    out_dir.mkdir(parents=True, exist_ok=True)
    # Pixabay 사진 주소는 하루쯤 지나면 만료돼서, 지금 쓸 2장 + [다른 사진]으로 넘길 다음 2장까지 미리 받아 둔다.
    # (며칠 뒤에 발행해도 표지가 그대로 나오게. 받아 둔 사진은 state.py로 GitHub과도 공유)
    for idx in ranked[pos:pos + 4]:
        data = _cached_photo(out_dir / f"cand_{idx:02d}.jpg", info["candidates"][idx]["url"])
        if data and len(photos) < 2:
            photos.append(_data_uri(data))
    if info.get("mode") == "drawn" and (out_dir / "drawn.png").exists():
        photos.insert(0, _data_uri((out_dir / "drawn.png").read_bytes()))

    mode = info.get("mode", "text")
    cover_idx = ranked[pos] if mode == "photo" and pos < len(ranked) else None
    return {
        "cover": photos[0] if mode in ("photo", "drawn") and photos else None,
        # 빽빽한 사진이 표지면 한 곳만 선명하게 두고 나머지를 흐리게 (가짜 아웃포커스)
        "focus": cover_idx is not None and cover_idx in info.get("busy", []),
        # 본문 사진은 표지에 안 쓴 다음 순위 사진 (로고 표지면 1순위 사진)
        "slide": (photos[0] if mode == "logo" else photos[1] if len(photos) > 1 else None) if photos else None,
        # 회사가 나오는 기사면 표지 종류와 상관없이 로고를 넣는다 (사진 표지에선 배지로)
        # 이미 만들어진 원고에도 적용되게 여기서 한 번 더 합친다
        "logos": [logos.get(c) for c in logos.merge_family(info.get("companies", []))],
        "rivalry": bool(info.get("rivalry")),
    }


def draw_with_gemini(card: dict, out_dir: Path) -> bool:
    """[AI로 그리기] 버튼용. 무료 한도가 없거나 실패하면 False."""
    import writer

    try:
        resp = writer._client().models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=f"{card['image_prompt']}. Style: {IMAGE_STYLE}",
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"], image_config=types.ImageConfig(aspect_ratio="4:5")
            ),
        )
    except errors.ClientError as e:
        reason = "무료 한도 없음 (결제 등록 필요)" if e.code == 429 else f"오류 {e.code}"
        print(f"   🎨 AI 그림: {reason}")
        return False
    for part in resp.candidates[0].content.parts:
        if part.inline_data:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "drawn.png").write_bytes(part.inline_data.data)
            card["image"]["mode"] = "drawn"
            return True
    return False
