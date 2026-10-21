"""3단계: 텔레그램 검수 봇

실행:  python bot.py   (켜져 있는 동안 버튼에 반응해요. 끄려면 Ctrl+C)

텔레그램 명령어:
  /start  처음 연결 (Chat ID 자동 저장)
  /run    오늘 뉴스 모으기 → 원고 → 카드 이미지 → 후보 보내기 (몇 분 걸려요)
  /send   가장 최근에 만든 카드를 다시 보내기

카드마다 붙는 버튼:
  🔄 다른 사진   AI가 고른 다음 순위 사진으로 바꾸기
  🏷️ 로고 표지   로고 표지 ↔ 사진 표지 바꾸기
  ✏️ 다른 제목   AI가 뽑은 제목 후보 3개(질문형·숫자형·반전형) 중 다음 것으로
  🎨 AI로 그리기 Gemini로 표지 그림 그리기 (결제 등록 전에는 안 돼요)
  👀 전체 보기   6장 전부 미리보기
  ✅ 발행        한 번 더 확인한 뒤 인스타에 캐러셀로 올리기 (publisher.py)
  ❌ 건너뛰기    이 카드는 안 올리기
"""
import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv, set_key
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import images
import publisher
import render

load_dotenv()
logging.basicConfig(level=logging.WARNING)

STATUS_TEXT = {"pending": "⏳ 검수 대기", "approved": "✅ 발행 대기열에 올라감", "skipped": "❌ 건너뜀",
               "published": "🎉 인스타에 올라갔어요"}


def publisher_ready() -> bool:
    return all(os.environ.get(k) for k in ("INSTAGRAM_ACCESS_TOKEN", "SUPABASE_URL", "SUPABASE_KEY"))


# ---------- 원고 파일 다루기 ----------

def _cards_file(day: str) -> Path:
    return Path("output") / day / "cards.json"


def load_cards(day: str) -> list[dict]:
    f = _cards_file(day)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_cards(day: str, cards: list[dict]) -> None:
    _cards_file(day).write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")


def cover_path(day: str, n: int) -> Path:
    return Path("output") / day / f"card_{n:02d}" / "01.jpg"


# ---------- 메시지 모양 ----------

def caption(card: dict, n: int, total: int) -> str:
    info = card.get("image", {})
    mode = {"photo": "사진", "logo": "로고", "drawn": "AI 그림", "text": "글자"}.get(info.get("mode"), "?")
    ranked = info.get("ranked", [])
    photo_pos = f" ({info.get('pos', 0) + 1}/{len(ranked)})" if info.get("mode") == "photo" and ranked else ""
    warn = f"\n⚠️ 확인 필요: {len(card['warnings'])}건" if card.get("warnings") else ""
    kind = "💡 꿀팁" if card.get("kind") == "tip" else "📰 뉴스"
    return (
        f"[{n}/{total}] {kind} · {card['hook_title']}\n"
        f"{card['subtitle']}\n\n"
        f"표지: {mode}{photo_pos}\n"
        f"출처: {card['source']} · {card['link']}{warn}\n\n"
        f"{STATUS_TEXT[card.get('status', 'pending')]}"
    )[:1024]


def keyboard(day: str, n: int, card: dict) -> InlineKeyboardMarkup | None:
    if card.get("status") == "published":  # 이미 올라간 건 되돌릴 수 없으니 보기 버튼만
        link = card.get("published", {}).get("permalink")
        return InlineKeyboardMarkup([[InlineKeyboardButton("📱 인스타에서 보기", url=link)]]) if link else None
    if card.get("status", "pending") != "pending":
        return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ 다시 검수", callback_data=f"undo|{day}|{n}")]])
    is_logo = card.get("image", {}).get("mode") == "logo"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 다른 사진", callback_data=f"next|{day}|{n}"),
         InlineKeyboardButton("🖼️ 사진 표지" if is_logo else "🏷️ 로고 표지", callback_data=f"logo|{day}|{n}")],
        [InlineKeyboardButton("✏️ 다른 제목", callback_data=f"title|{day}|{n}"),
         InlineKeyboardButton("🎨 AI로 그리기", callback_data=f"draw|{day}|{n}")],
        [InlineKeyboardButton("👀 전체 보기", callback_data=f"all|{day}|{n}")],
        [InlineKeyboardButton("✅ 발행", callback_data=f"ok|{day}|{n}"),
         InlineKeyboardButton("❌ 건너뛰기", callback_data=f"skip|{day}|{n}")],
    ])


async def _answer(query, text: str | None = None, show_alert: bool = False) -> None:
    """버튼 눌림에 답한다. GitHub Actions처럼 몇 분 뒤에 처리하면 텔레그램이
    '너무 오래된 버튼'이라며 거절하는데, 그래도 나머지 작업(표지 바꾸기 등)은 계속하게 한다."""
    try:
        await query.answer(text, show_alert=show_alert)
    except BadRequest:
        pass


# ---------- 상태 동기화 (PC ↔ GitHub Actions) ----------

SYNC_EACH_CHANGE = False  # PC 봇에서는 True: 바뀔 때마다 Supabase에 올려서 GitHub와 맞춘다


async def _sync() -> None:
    if SYNC_EACH_CHANGE:
        import state

        await asyncio.to_thread(state.push)


# ---------- 권한 ----------

def _allowed(update: Update) -> bool:
    """내 Chat ID에서 온 것만 처리 (다른 사람이 봇을 눌러도 무시)."""
    my_id = os.environ.get("TELEGRAM_CHAT_ID")
    return bool(my_id) and str(update.effective_chat.id) == my_id


# ---------- 명령어 ----------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    saved = os.environ.get("TELEGRAM_CHAT_ID")
    if not saved:
        set_key(".env", "TELEGRAM_CHAT_ID", chat_id, quote_mode="never")
        os.environ["TELEGRAM_CHAT_ID"] = chat_id
        await update.message.reply_text("🐿️ 연결 완료! 이제 이 채팅으로 칩다람 카드 후보를 보내드릴게요.\n"
                                        "/send 최근 카드 보기 · /run 오늘 카드 새로 만들기")
    elif saved == chat_id:
        await update.message.reply_text("🐿️ 이미 연결돼 있어요.\n/send 최근 카드 보기 · /run 오늘 카드 새로 만들기")
    # 다른 사람이 /start 하면 아무 대답도 하지 않는다


async def send_cards(bot: Bot, chat_id: str, day: str, only_pending: bool = False) -> None:
    cards = load_cards(day)
    if not cards:
        await bot.send_message(chat_id, "오늘 만든 카드가 없어요. /run 으로 만들어 주세요.")
        return
    for n, card in enumerate(cards, 1):
        path = cover_path(day, n)
        if not path.exists() or (only_pending and card.get("status", "pending") != "pending"):
            continue
        with open(path, "rb") as f:
            await bot.send_photo(chat_id, f, caption=caption(card, n, len(cards)),
                                 reply_markup=keyboard(day, n, card))


def latest_day() -> str:
    """원고가 있는 가장 최근 날짜 (없으면 오늘)."""
    days = sorted(p.parent.name for p in Path("output").glob("*/cards.json"))
    return days[-1] if days else date.today().isoformat()


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await send_cards(context.bot, update.effective_chat.id, latest_day())


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    day = date.today().isoformat()
    await update.message.reply_text("🌰 오늘 AI 뉴스를 모으는 중이에요... (몇 분 걸려요)")
    import step1

    await asyncio.to_thread(step1.main)
    await update.message.reply_text("🎨 카드 이미지를 만드는 중이에요...")
    await asyncio.to_thread(render.render, day)
    await _sync()
    await send_cards(context.bot, update.effective_chat.id, day)


# ---------- 버튼 ----------

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update):
        await _answer(query)
        return
    action, day, n = query.data.split("|")
    n = int(n)
    cards = load_cards(day)
    card = cards[n - 1]
    info = card.setdefault("image", {"mode": "text", "companies": [], "candidates": [], "ranked": [], "busy": [], "pos": 0})

    if action == "all":
        await _answer(query, "6장 보내는 중")
        # 버튼으로는 표지만 다시 찍으니, 전체를 볼 때 6장을 최신 상태로 맞춘다
        await asyncio.to_thread(render.render, day, n)
        folder = Path("output") / day / f"card_{n:02d}"
        files = [open(p, "rb") for p in sorted(folder.glob("0*.jpg"))]
        try:
            await context.bot.send_media_group(query.message.chat_id, [InputMediaPhoto(f) for f in files])
        finally:
            for f in files:
                f.close()
        return

    if action == "ok":  # 실수로 눌러도 바로 올라가지 않게 한 번 더 묻기
        await _answer(query)
        await query.edit_message_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 인스타에 올리기", callback_data=f"publish|{day}|{n}"),
            InlineKeyboardButton("↩️ 취소", callback_data=f"cancel|{day}|{n}"),
        ]]))
        return

    if action == "cancel":
        await _answer(query, "취소했어요")
        await query.edit_message_reply_markup(keyboard(day, n, card))
        return

    if action == "publish":
        await _answer(query, "올리는 중... (30초~1분)")
        await query.edit_message_caption(caption(card, n, len(cards)) + "\n\n📤 인스타에 올리는 중...")
        await asyncio.to_thread(render.render, day, n)  # 6장 모두 최신 상태로
        if not publisher_ready():
            card["status"] = "approved"
            note = "\n\n(인스타 연결 전이라 발행 대기열에만 올렸어요)"
        else:
            try:
                await asyncio.to_thread(publisher.publish_carousel, day, n)
                cards = load_cards(day)  # 발행 정보가 저장된 최신 원고
                card = cards[n - 1]
                card["status"], note = "published", ""
            except Exception as e:  # noqa: BLE001 - 어떤 오류든 텔레그램에 보여주고 다시 시도할 수 있게
                card["status"], note = "pending", f"\n\n❌ 발행 실패: {e}"
        save_cards(day, cards)
        await _sync()
        await query.edit_message_caption(caption(card, n, len(cards)) + note, reply_markup=keyboard(day, n, card))
        return

    if action in ("skip", "undo"):
        card["status"] = {"skip": "skipped", "undo": "pending"}[action]
        save_cards(day, cards)
        await _sync()
        await _answer(query, STATUS_TEXT[card["status"]])
        await query.edit_message_caption(caption(card, n, len(cards)), reply_markup=keyboard(day, n, card))
        return

    # 표지를 바꾸는 버튼들
    if action == "next":
        if not info["ranked"]:
            await _answer(query, "다른 사진 후보가 없어요. 🏷️ 로고 표지나 🎨 AI로 그리기를 써보세요.", show_alert=True)
            return
        if info["mode"] == "photo":
            info["pos"] = (info["pos"] + 1) % len(info["ranked"])
        info["mode"] = "photo"
        msg = f"사진 {info['pos'] + 1}/{len(info['ranked'])}"
    elif action == "logo":
        if info["mode"] == "logo":
            if not info["ranked"]:
                await _answer(query, "사진 후보가 없어서 로고 표지를 유지해요.", show_alert=True)
                return
            info["mode"], msg = "photo", "사진 표지로 바꿨어요"
        else:
            if not info["companies"]:
                await _answer(query, "이 기사엔 연결된 회사 로고가 없어요.", show_alert=True)
                return
            info["mode"], msg = "logo", "로고 표지로 바꿨어요"
    elif action == "title":
        options = card.get("title_options") or []
        if len(options) < 2:
            await _answer(query, "이 카드엔 다른 제목 후보가 없어요.", show_alert=True)
            return
        cur = options.index(card["hook_title"]) if card["hook_title"] in options else -1
        card["hook_title"] = options[(cur + 1) % len(options)]
        msg = f"제목 {options.index(card['hook_title']) + 1}/{len(options)}"
    elif action == "draw":
        await _answer(query, "그리는 중...")
        ok = await asyncio.to_thread(images.draw_with_gemini, card, Path("output") / day / f"card_{n:02d}")
        if not ok:
            await context.bot.send_message(query.message.chat_id,
                                           "🎨 AI 그림은 아직 설정이 안 됐어요 (Gemini 결제 등록이 필요해요).")
            return
        msg = "AI가 그린 그림으로 바꿨어요"
    else:
        await _answer(query)
        return

    save_cards(day, cards)
    if action != "draw":
        await _answer(query, msg)
    await asyncio.to_thread(render.render, day, n, False, True)  # 표지 1장만 (빠르게)
    await _sync()
    with open(cover_path(day, n), "rb") as f:
        await query.edit_message_media(InputMediaPhoto(f, caption=caption(card, n, len(cards))),
                                       reply_markup=keyboard(day, n, card))


def build_app() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN이 없어요.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CallbackQueryHandler(on_button))
    return app


def main() -> None:
    """PC에서 켜두는 빠른 모드: 버튼에 2~3초 안에 반응한다."""
    global SYNC_EACH_CHANGE
    import state

    print("☁️ GitHub 쪽 최신 상태 받는 중...")
    state.pull()
    SYNC_EACH_CHANGE = True
    app = build_app()
    print("🐿️ 칩다람 봇이 켜졌어요 (PC 빠른 모드). 끄면 GitHub이 몇 분마다 대신 처리해요. (끄려면 Ctrl+C)")
    # drop_pending_updates는 쓰지 않는다: 꺼져 있는 동안 눌린 버튼은 GitHub이 이미 처리했거나,
    # 아직 안 했으면 여기서 이어서 처리하면 된다 ([발행]은 확인 버튼을 한 번 더 거쳐서 안전)
    app.run_polling()


if __name__ == "__main__":
    main()
