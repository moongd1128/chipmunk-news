"""텔레그램 버튼 대기열 (문지기 방식)

텔레그램 webhook을 Supabase 문지기(supabase/functions/telegram-hook)에 연결하면,
눌린 버튼은 텔레그램이 아니라 비공개 버킷 private/queue/ 에 쌓인다. 봇(GitHub·PC)은 여기서 꺼내 처리한다.
webhook이 꺼져 있으면(문지기를 아직 안 켰거나 끈 경우) 예전처럼 텔레그램 getUpdates를 쓴다.

깨어 있는 봇은 queue/_awake.json에 시각을 계속 적어 둔다 →
문지기는 이걸 보고 '깨어 있으면 그냥 두고, 자고 있으면 바로 답하고 GitHub을 깨운다'.
"""
import json
import os
import time

import requests

import state

PREFIX = "queue/"
AWAKE = f"{PREFIX}_awake.json"
AWAKE_SECONDS = 60  # 문지기 쪽(AWAKE_SECONDS)과 같게


def webhook_on() -> bool:
    """문지기(webhook)가 켜져 있는지."""
    r = requests.get(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/getWebhookInfo", timeout=20)
    return bool(r.json().get("result", {}).get("url"))


def _names() -> list[str]:
    r = requests.post(f"{state._base()}/storage/v1/object/list/{state.BUCKET}", headers=state._headers("application/json"),
                      json={"prefix": PREFIX.rstrip("/"), "limit": 1000, "sortBy": {"column": "name", "order": "asc"}},
                      timeout=30)
    r.raise_for_status()
    return sorted(i["name"] for i in r.json() if i["name"].endswith(".json") and not i["name"].startswith("_"))


def pending() -> list[tuple[str, dict]]:
    """쌓인 버튼·명령을 누른 순서대로 [(이름, update)]."""
    out = []
    for name in _names():
        data = state._get(f"{PREFIX}{name}")
        if data:
            out.append((name, json.loads(data)))
    return out


def done(names: list[str]) -> None:
    """처리한 것은 대기열에서 지운다."""
    if names:
        requests.delete(f"{state._base()}/storage/v1/object/{state.BUCKET}", headers=state._headers("application/json"),
                        json={"prefixes": [f"{PREFIX}{n}" for n in names]}, timeout=30).raise_for_status()


def awake_elsewhere() -> bool:
    """다른 봇(PC나 다른 GitHub 실행)이 지금 깨어 있는지."""
    data = state._get(AWAKE)
    return bool(data) and time.time() - json.loads(data)["at"] < AWAKE_SECONDS


def heartbeat() -> None:
    """'나 깨어 있어요' 표시 (문지기가 GitHub을 또 깨우지 않게)."""
    state._put(AWAKE, json.dumps({"at": time.time()}).encode(), "application/json")


def sleep() -> None:
    """빠른 모드가 끝나면 표시를 지운다 → 다음 버튼부터는 문지기가 바로 답하고 GitHub을 깨운다."""
    requests.delete(f"{state._base()}/storage/v1/object/{state.BUCKET}", headers=state._headers("application/json"),
                    json={"prefixes": [AWAKE]}, timeout=30)
