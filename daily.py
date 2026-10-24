"""매일 아침 작업 (GitHub Actions에서 실행, PC에서도 같은 명령으로 가능)

  상태 받기 → 인스타 토큰 연장 → 원고 → 카드 이미지 → 릴스 → 상태 올리기 → 텔레그램으로 후보 보내기
"""
import asyncio
import os
import time
from datetime import date

from dotenv import load_dotenv

load_dotenv()

import bot  # noqa: E402
import publisher  # noqa: E402
import reels  # noqa: E402
import render  # noqa: E402
import state  # noqa: E402
import step1  # noqa: E402


async def notify(text: str) -> None:
    app = bot.build_app()
    await app.initialize()
    try:
        await app.bot.send_message(os.environ["TELEGRAM_CHAT_ID"], text)
    finally:
        await app.shutdown()


async def send_today(day: str) -> None:
    app = bot.build_app()
    await app.initialize()
    try:
        await bot.send_cards(app.bot, os.environ["TELEGRAM_CHAT_ID"], day, only_pending=True)
    finally:
        await app.shutdown()


def _stage(name: str, started: float) -> float:
    now = time.time()
    print(f"\n⏱️ [{name}] {now - started:.0f}초\n", flush=True)
    return now


def main() -> None:
    day = date.today().isoformat()
    t = time.time()
    state.ensure_bucket()
    state.pull()
    state.pull_bgm()
    try:
        publisher.refresh_token_if_old()
    except Exception as e:  # noqa: BLE001 - 토큰 연장이 실패해도 카드 만들기는 계속
        print(f"⚠️ 토큰 연장 중 오류: {e}")
    t = _stage("준비", t)

    step1.main()
    t = _stage("원고", t)
    if not bot.load_cards(day):
        asyncio.run(notify("🐿️ 오늘은 원고를 만들지 못했어요 (새 재료가 없거나 AI 한도 초과). 로그를 확인해 주세요."))
        return
    render.render(day)
    t = _stage("카드 이미지", t)
    reels.make_all(day)
    t = _stage("릴스", t)
    state.push()
    asyncio.run(notify(f"🌰 오늘의 칩다람 카드가 도착했어요! 앞으로 {LIVE_MINUTES}분 동안은 버튼이 바로 반응해요."))
    asyncio.run(send_today(day))
    # 카드가 막 도착했을 때 바로 검수하는 경우가 많으니, 한동안 깨어 있어서 버튼이 2~3초에 반응하게
    asyncio.run(bot.run_live(LIVE_MINUTES))


LIVE_MINUTES = 60  # 아침에 몰아서 검수하는 동안 버튼이 바로 반응하게


if __name__ == "__main__":
    main()
