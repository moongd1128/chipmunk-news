"""GitHub Actions용: 밀려 있는 텔레그램 버튼·명령을 처리하고, 이어서 20분 동안 빠른 모드로 깨어 있는다

- 몇 분마다 자동 실행: 눌린 버튼이 있을 때만 여기까지 온다
- 직접 실행([Run workflow], FORCE_LIVE=1): 버튼이 없어도 빠른 모드로 켜둔다
- PC에서 bot.py가 켜져 있으면 텔레그램이 동시 접속을 막아서(409) 그냥 넘어간다
"""
import asyncio
import os

from telegram.error import Conflict

import bot
import state

LIVE_MINUTES = 20


async def process_pending() -> bool | None:
    """밀린 버튼·명령을 처리한다. PC 봇이 켜져 있으면 None, 처리한 게 있으면 True."""
    app = bot.build_app()
    await app.initialize()
    try:
        try:
            updates = await app.bot.get_updates(timeout=0, allowed_updates=["message", "callback_query"])
        except Conflict:
            return None
        if not updates:
            print("밀린 버튼 없음")
            return False
        print(f"밀린 버튼·명령 {len(updates)}개 처리")
        for u in updates:
            await app.process_update(u)
        # 처리한 것까지 텔레그램에 '받았음' 알리기 (다음에 다시 안 오게)
        await app.bot.get_updates(offset=updates[-1].update_id + 1, timeout=0)
        state.push()
        return True
    finally:
        await app.shutdown()


async def main() -> None:
    state.pull()
    handled = await process_pending()
    if handled is None:
        print("PC 봇이 켜져 있어서 GitHub은 쉬어요")
        return
    # 버튼을 누르기 시작했다 = 지금 검수 중 → 한동안 깨어 있어서 다음 버튼은 바로 반응
    if handled or os.environ.get("FORCE_LIVE"):
        await bot.run_live(LIVE_MINUTES)


if __name__ == "__main__":
    state.ensure_bucket()
    asyncio.run(main())
