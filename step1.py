"""1단계 실행: 그날 가장 좋은 콘텐츠 원고 만들기 (뉴스·꿀팁 비율은 정하지 않음)

  재료: 해외 AI 매체 기사(뉴스) + AI 회사 공식 블로그 글(꿀팁 재료)
  → 한 바구니에서 보내고 싶거나 저장하고 싶은 것 고르기 → 종류에 맞게 원고 (꿀팁은 지어내기 금지)

사용법:
  python step1.py            # 전체 실행 (Gemini 키 필요)
  python step1.py --news     # 재료 수집만 테스트 (키 없어도 됨)
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

import checker
import news

load_dotenv()

MAX_REVISIONS = 2  # 무료 등급은 하루 요청 수가 적어서 자동 수정은 2번까지 (문제가 남았을 때만 2번째)
POSTS_PER_DAY = 5  # 하루에 만들 원고 수 (뉴스·꿀팁 섞어서)


def polish(card: dict) -> dict:
    """검사기에 걸린 곳을 AI가 스스로 고치게 한다. 그래도 남으면 warnings에 적어둔다."""
    import writer

    for attempt in range(1, MAX_REVISIONS + 1):
        problems = checker.find_problems(card)
        if not problems:
            break
        print(f"   🔍 검사에서 {len(problems)}개 발견 → 자동 수정 {attempt}회차")
        for p in problems:
            print(f"      · {p}")
        time.sleep(4)
        # 수정본에는 원고 칸만 있으니, kind(뉴스/꿀팁) 같은 나머지 정보는 원래 값을 유지한다
        card = checker.fix_names({**card, **writer.revise_card(card, problems).model_dump()})
    card["warnings"] = checker.find_problems(card)
    if card["warnings"]:
        print(f"   ⚠️ 끝까지 남은 문제 {len(card['warnings'])}개 (검수 때 확인)")
    else:
        print("   ✅ 검사 통과")
    return card


def gather() -> list[dict]:
    """뉴스 기사와 꿀팁 재료를 한 바구니에 모은다. 각 항목에 kind("news"/"tip")를 붙인다."""
    import tips

    print("🌰 해외 AI 뉴스 모으는 중...")
    items = [{**a, "kind": "news"} for a in news.fetch_latest_news()]
    print("\n💡 꿀팁 재료(AI 회사 공식 블로그) 모으는 중...")
    items += [{**s, "kind": "tip"} for s in tips.fetch_tip_sources()]
    news_n = sum(i["kind"] == "news" for i in items)
    print(f"→ 뉴스 {news_n}개 + 꿀팁 재료 {len(items) - news_n}개\n")
    return items


def main() -> None:
    items = gather()
    if "--news" in sys.argv:
        for a in items:
            print(f"- <{a['kind']}> ({a['source']}) {a['title']}")
        return
    if not items:
        print("새 재료가 없어요. 나중에 다시 실행해 보세요.")
        return

    import writer

    print(f"🐿️ 보내고 싶거나 저장하고 싶은 콘텐츠 {POSTS_PER_DAY}개 고르는 중...")
    try:
        picked = writer.pick_contents(items, n=POSTS_PER_DAY)
    except RuntimeError as e:
        print(f"⛔ {e}")
        return
    jobs = [(a["kind"], a) for a in picked]
    for a in picked:
        print(f"  ✔ {'💡' if a['kind'] == 'tip' else '📰'} {a['title']}")

    out_dir = Path("output") / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "cards.json"
    # 같은 날 다시 실행하면 이어서 추가한다
    results = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else []

    for i, (kind, a) in enumerate(jobs, 1):
        label = "💡 꿀팁" if kind == "tip" else "📰 뉴스"
        print(f"\n✍️ [{i}/{len(jobs)}] {label} 원고 쓰는 중: {a['title']}")
        try:
            body = news.fetch_article_body(a["link"], fallback=a["summary"])
            write = writer.write_tip_card if kind == "tip" else writer.write_card_news
            # kind를 먼저 붙여야 검사기가 꿀팁(5장)·뉴스(4장)를 구분한다
            card = checker.fix_names({"kind": kind, **write(a, body).model_dump()})
            card = polish(card)
        except RuntimeError as e:  # 모든 모델 한도 소진
            print(f"\n⛔ {e}")
            break
        results.append({"source": a["source"], "link": a["link"], "original_title": a["title"], **card})
        # 한 개 쓸 때마다 바로 저장해서, 중간에 멈춰도 써둔 원고는 남게 한다
        out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        news.mark_seen([a["link"]])
        print(f"   → {card['hook_title']}")
        time.sleep(4)  # 무료 등급 분당 요청 제한 배려

    print(f"\n✅ 원고 {len(results)}개 저장됨: {out_file}")


if __name__ == "__main__":
    main()
