"""5단계: 인스타그램 캐러셀 자동 발행

흐름:
  1) 카드 이미지 6장을 Supabase Storage(공개 저장소)에 올려서 인터넷 주소(URL)를 만든다
     (인스타 API는 내 컴퓨터 파일을 못 받고, 인터넷 주소로만 사진을 가져가요)
  2) 인스타 API에 사진마다 '캐러셀 조각'을 만들고 → 묶어서 캐러셀 1개 → 발행

필요한 .env 값:
  INSTAGRAM_ACCESS_TOKEN   Meta 앱 대시보드에서 만든 토큰 (60일마다 자동 연장)
  SUPABASE_URL             https://xxxx.supabase.co
  SUPABASE_KEY             Supabase의 service_role 키 (비밀)
  SUPABASE_BUCKET          공개 버킷 이름 (기본값 cards)

사용법:
  python publisher.py check               # 연결 확인 (아무것도 올리지 않음)
  python publisher.py 2026-10-20 3        # 그날 3번 카드를 캐러셀로 발행
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv, set_key

load_dotenv()

IG = "https://graph.instagram.com/v26.0"
TOKEN_REFRESH_DAYS = 50  # 토큰은 60일짜리라 50일 지나면 미리 연장


# ---------- 공개 저장소 (Supabase) ----------

def _bucket() -> str:
    return os.environ.get("SUPABASE_BUCKET", "cards")


def _supabase_base() -> str:
    """https://xxxx.supabase.co 까지만 (뒤에 /rest/v1 같은 게 붙어 있어도 떼어낸다)."""
    u = urlparse(os.environ["SUPABASE_URL"].strip())
    return f"{u.scheme}://{u.netloc}"


def upload_public(path: Path, remote_name: str) -> str:
    """파일을 Supabase 공개 버킷에 올리고 인터넷 주소를 돌려준다."""
    base = _supabase_base()
    key = os.environ["SUPABASE_KEY"]
    headers = {"apikey": key, "Content-Type": "image/jpeg", "x-upsert": "true"}
    if key.startswith("eyJ"):  # 예전 형식(service_role JWT) 키는 Authorization에도 넣어야 해요
        headers["Authorization"] = f"Bearer {key}"
    resp = requests.post(
        f"{base}/storage/v1/object/{_bucket()}/{remote_name}",
        headers=headers,
        data=path.read_bytes(), timeout=60,
    )
    resp.raise_for_status()
    return f"{base}/storage/v1/object/public/{_bucket()}/{remote_name}"


# ---------- 인스타 API ----------

TOKEN_FILE = Path("data/ig_token.json")  # 연장된 토큰 (PC·GitHub Actions가 state로 같이 씀)


def _token() -> str:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))["token"]
    return os.environ["INSTAGRAM_ACCESS_TOKEN"]


def _ig(method: str, path: str, **params) -> dict:
    resp = requests.request(method, f"{IG}/{path}", params={**params, "access_token": _token()}, timeout=60)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"인스타 API 오류: {data['error'].get('message')}")
    return data


def me() -> dict:
    return _ig("GET", "me", fields="user_id,username,account_type")


def refresh_token_if_old() -> None:
    """토큰이 오래됐으면 새 토큰으로 바꿔서 data/ig_token.json에 저장한다 (60일 만료 방지).
    data/는 state.py로 PC와 GitHub Actions가 같이 쓰니까, 어디서 연장해도 양쪽에 반영된다."""
    if TOKEN_FILE.exists():
        stamp = json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("refreshed_at", 0)
    else:
        stamp = float(os.environ.get("INSTAGRAM_TOKEN_REFRESHED_AT") or 0)
    if time.time() - float(stamp) < TOKEN_REFRESH_DAYS * 86400:
        return
    resp = requests.get("https://graph.instagram.com/refresh_access_token",
                        params={"grant_type": "ig_refresh_token", "access_token": _token()}, timeout=30).json()
    if "access_token" not in resp:
        print(f"⚠️ 인스타 토큰 연장 실패: {resp.get('error', {}).get('message', resp)}")
        return
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"token": resp["access_token"], "refreshed_at": int(time.time())}),
                          encoding="utf-8")
    if Path(".env").exists():  # PC에서는 .env도 같이 맞춰둔다
        set_key(".env", "INSTAGRAM_ACCESS_TOKEN", resp["access_token"], quote_mode="never")
    print("🔑 인스타 토큰을 60일 연장했어요")


def _wait_ready(container_id: str) -> None:
    """인스타가 사진을 다 받아갈 때까지 기다린다."""
    for _ in range(30):
        status = _ig("GET", container_id, fields="status_code")["status_code"]
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"인스타가 사진 처리에 실패했어요 ({status})")
        time.sleep(3)
    raise RuntimeError("인스타 사진 처리가 너무 오래 걸려요")


def build_caption(card: dict) -> str:
    tags = " ".join(card.get("hashtags", []))
    return f"{card['caption']}\n\n{tags}".strip()[:2200]


def publish_carousel(day: str, n: int) -> str:
    """그날 n번 카드 6장을 캐러셀로 발행하고, 게시물 주소를 돌려준다."""
    refresh_token_if_old()
    card_dir = Path("output") / day / f"card_{n:02d}"
    cards = json.loads((Path("output") / day / "cards.json").read_text(encoding="utf-8"))
    card = cards[n - 1]
    images = sorted(card_dir.glob("0*.jpg"))
    if not 2 <= len(images) <= 20:
        raise RuntimeError(f"캐러셀은 2~20장이어야 해요 (지금 {len(images)}장)")

    user_id = me()["user_id"]
    stamp = int(time.time())
    print(f"📤 사진 {len(images)}장 올리는 중...")
    urls = [upload_public(p, f"{day}/card_{n:02d}/{stamp}_{p.name}") for p in images]

    print("🧩 캐러셀 조각 만드는 중...")
    children = []
    for url in urls:
        cid = _ig("POST", f"{user_id}/media", image_url=url, is_carousel_item="true")["id"]
        children.append(cid)
    for cid in children:
        _wait_ready(cid)

    carousel = _ig("POST", f"{user_id}/media", media_type="CAROUSEL",
                   children=",".join(children), caption=build_caption(card))["id"]
    _wait_ready(carousel)

    print("🚀 발행 중...")
    media_id = _ig("POST", f"{user_id}/media_publish", creation_id=carousel)["id"]
    link = _ig("GET", media_id, fields="permalink").get("permalink", "")

    card["published"] = {"media_id": media_id, "permalink": link, "at": int(time.time())}
    (Path("output") / day / "cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 발행 완료: {link}")
    return link


def check() -> None:
    """키가 다 있는지, 인스타 계정과 저장소에 연결되는지만 확인한다 (게시물은 안 올림)."""
    for k in ("INSTAGRAM_ACCESS_TOKEN", "SUPABASE_URL", "SUPABASE_KEY"):
        print(f"  {k}: {'있음' if os.environ.get(k) else '없음 ❌'}")
    if os.environ.get("INSTAGRAM_ACCESS_TOKEN"):
        info = me()
        print(f"  인스타 계정: @{info.get('username')} ({info.get('account_type')})")
        limit = _ig("GET", f"{info['user_id']}/content_publishing_limit", fields="quota_usage,config")
        print(f"  오늘 발행 사용량: {limit.get('data', [{}])[0]}")
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        test = Path("assets/cache/_upload_test.jpg")
        test.parent.mkdir(parents=True, exist_ok=True)
        src = next(Path("output").glob("*/card_*/01.jpg"), None)
        if src:
            test.write_bytes(src.read_bytes())
            url = upload_public(test, "_test/upload_test.jpg")
            ok = requests.get(url, timeout=30).status_code == 200
            print(f"  저장소 업로드·공개 주소: {'OK' if ok else '실패 ❌ (버킷이 공개인지 확인)'}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        check()
    elif len(sys.argv) == 3:
        publish_carousel(sys.argv[1], int(sys.argv[2]))
    else:
        print(__doc__)
