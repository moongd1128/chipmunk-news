"""PC와 GitHub Actions가 같은 상태를 보도록, 작업 기록을 Supabase 비공개 버킷에 보관한다.

보관하는 것 (state.tar.gz 하나로 묶어서):
  data/            이미 쓴 기사 기록, 갱신된 인스타 토큰
  output/<날짜>/   최근 7일 치 원고(cards.json)와 받아 둔 표지 사진·사이트 캡처
  (카드 이미지·영상처럼 다시 만들 수 있는 건 빼고, 받아 둔 표지 사진·사이트 캡처는 넣는다)

배경음악(assets/bgm)도 공개 저장소에 올리면 안 돼서 같은 비공개 버킷에 둔다.

사용법:
  python state.py pull       # Supabase → 이 컴퓨터
  python state.py push       # 이 컴퓨터 → Supabase
  python state.py push-bgm   # assets/bgm 음악 올리기 (처음 한 번)
  python state.py pull-bgm   # 음악 내려받기 (Actions에서 사용)
"""
import io
import os
import re
import sys
import tarfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

BUCKET = "private"
STATE_KEY = "state/state.tar.gz"
KEEP_DAYS = 7  # 좋은 후보를 며칠 나눠 올릴 수 있게 일주일 치 보관


def _base() -> str:
    u = urlparse(os.environ["SUPABASE_URL"].strip())
    return f"{u.scheme}://{u.netloc}"


def _headers(content_type: str | None = None) -> dict:
    key = os.environ["SUPABASE_KEY"]
    h = {"apikey": key}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    if content_type:
        h["Content-Type"] = content_type
    return h


def ensure_bucket() -> None:
    """비공개 버킷이 없으면 만든다."""
    r = requests.post(f"{_base()}/storage/v1/bucket", headers=_headers("application/json"),
                      json={"id": BUCKET, "name": BUCKET, "public": False}, timeout=30)
    if r.status_code not in (200, 201) and "already exists" not in r.text and r.status_code != 409:
        r.raise_for_status()


def _put(key: str, data: bytes, content_type: str) -> None:
    h = _headers(content_type)
    h["x-upsert"] = "true"
    r = requests.post(f"{_base()}/storage/v1/object/{BUCKET}/{key}", headers=h, data=data, timeout=180)
    r.raise_for_status()


def _get(key: str) -> bytes | None:
    r = requests.get(f"{_base()}/storage/v1/object/{BUCKET}/{key}", headers=_headers(), timeout=180)
    if r.status_code in (400, 404):
        return None
    r.raise_for_status()
    return r.content


# 언제든 다시 만들 수 있는 것은 공유하지 않는다 (Supabase 무료는 파일 하나 50MB까지라 용량 아끼기)
#   카드 이미지(01.jpg~)·스토리 사진은 [발행]·버튼 누를 때 다시 찍고, 영상·녹화·프레임은 그때그때 만든다
_REMAKE = re.compile(r"^\d\d\.jpg$|^story\.jpg$|\.mp4$|\.webm$|\.png$")
_REMAKE_DIRS = {"motion", "tip_frames", "news_frames"}


def _keep(path: Path) -> bool:
    """state에 넣을 파일인지. 원고(cards.json), 받아 둔 표지 후보 사진(cand_, 주소가 하루 만에 만료돼서 꼭 필요),
    사이트 캡처(shots), AI 그림(drawn.png)은 넣고, 다시 만들 수 있는 건 뺀다."""
    if _REMAKE_DIRS & set(path.parts):
        return False
    if path.name == "drawn.png":
        return True
    return not _REMAKE.search(path.name)


def push() -> None:
    buf = io.BytesIO()
    recent = {(date.today() - timedelta(days=d)).isoformat() for d in range(KEEP_DAYS)}
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if Path("data").exists():
            tar.add("data")
        for day_dir in Path("output").glob("*"):
            if day_dir.is_dir() and day_dir.name in recent:
                for p in day_dir.rglob("*"):
                    if p.is_file() and _keep(p):
                        tar.add(str(p))
    _put(STATE_KEY, buf.getvalue(), "application/gzip")
    print(f"☁️ 상태 올림 ({len(buf.getvalue()) // 1024}KB)")


def pull() -> None:
    data = _get(STATE_KEY)
    if not data:
        print("☁️ 아직 올라간 상태가 없어요 (처음 실행)")
        return
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(".", filter="data")
    print(f"☁️ 상태 내려받음 ({len(data) // 1024}KB)")


def push_bgm() -> None:
    files = sorted(Path("assets/bgm").glob("*.mp3"))
    for f in files:
        _put(f"bgm/{f.name}", f.read_bytes(), "audio/mpeg")
        print(f"🎵 올림: {f.name}")


def pull_bgm() -> None:
    r = requests.post(f"{_base()}/storage/v1/object/list/{BUCKET}", headers=_headers("application/json"),
                      json={"prefix": "bgm", "limit": 100}, timeout=30)
    r.raise_for_status()
    out = Path("assets/bgm")
    out.mkdir(parents=True, exist_ok=True)
    for item in r.json():
        name = item["name"]
        if name.endswith(".mp3") and not (out / name).exists():
            (out / name).write_bytes(_get(f"bgm/{name}"))
    print(f"🎵 음악 {len(list(out.glob('*.mp3')))}곡 준비")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    ensure_bucket()
    {"pull": pull, "push": push, "push-bgm": push_bgm, "pull-bgm": pull_bgm}.get(cmd, lambda: print(__doc__))()
