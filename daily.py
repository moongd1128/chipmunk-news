"""매일 아침 작업 (GitHub Actions에서 실행, PC에서도 같은 명령으로 가능)

  상태 받기 → 인스타 토큰 연장 → 원고 → 카드 이미지 → 릴스 → 상태 올리기 → 텔레그램으로 후보 보내기
"""
import asyncio
import os
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


def main() -> None:
    day = date.today().isoformat()
    state.ensure_bucket()
    state.pull()
    state.pull_bgm()
    try:
        publisher.refresh_token_if_old()
    except Exception as e:  # noqa: BLE001 - 토큰 연장이 실패해도 카드 만들기는 계속
        print(f"⚠️ 토큰 연장 중 오류: {e}")

    step1.main()
    if not bot.load_cards(day):
        asyncio.run(notify("🐿️ 오늘은 원고를 만들지 못했어요 (새 재료가 없거나 AI 한도 초과). 로그를 확인해 주세요."))
        return
    render.render(day)
    reels.make_all(day)
    state.push()
    asyncio.run(notify("🌰 오늘의 칩다람 카드가 도착했어요! 버튼은 PC가 꺼져 있으면 몇 분 뒤에 반영돼요."))
    asyncio.run(send_today(day))


if __name__ == "__main__":
    main()
