"""GitHub Actions용: 밀려 있는 텔레그램 버튼·명령을 처리하고, 이어서 20분 동안 빠른 모드로 깨어 있는다

PC에서 bot.py가 켜져 있으면 텔레그램이 동시 접속을 막아서(409) 그냥 넘어간다.
"""
import asyncio

from telegram.error import Conflict

import bot
import state


async def main() -> None:
    app = bot.build_app()
    await app.initialize()
    try:
        try:
            updates = await app.bot.get_updates(timeout=0, allowed_updates=["message", "callback_query"])
        except Conflict:
            print("PC 봇이 켜져 있어서 GitHub은 쉬어요")
            return
        if not updates:
            print("처리할 버튼 없음")
            return
        print(f"버튼·명령 {len(updates)}개 처리")
        state.pull()
        for u in updates:
            await app.process_update(u)
        # 처리한 것까지 텔레그램에 '받았음' 알리기 (다음에 다시 안 오게)
        await app.bot.get_updates(offset=updates[-1].update_id + 1, timeout=0)
        state.push()
    finally:
        await app.shutdown()
    # 버튼을 누르기 시작했다는 건 지금 검수 중이라는 뜻 → 한동안 깨어 있어서 다음 버튼은 바로 반응
    await bot.run_live(LIVE_MINUTES)


LIVE_MINUTES = 20


if __name__ == "__main__":
    state.ensure_bucket()
    asyncio.run(main())
