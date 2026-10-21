"""원고 자동 검사기: 사람이 일일이 안 봐도 되게 규칙 위반을 찾아내고, 이름 표기는 바로 고친다.

새로 자주 틀리는 이름이나 어려운 단어가 보이면 아래 표에만 추가하면 된다.
"""
import re

# 정해진 표기: [이렇게 틀리게 쓰면 → 이걸로 고침]
NAMES = {
    "앤트로픽": ["앤스로픽", "엔트로픽", "안트로픽", "앤쓰로픽", "Anthropic"],
    "오픈AI": ["오픈에이아이", "오픈 AI", "OpenAI"],
    "챗GPT": ["챗지피티", "쳇GPT", "ChatGPT"],
    "클로드": ["Claude"],
    "제미나이": ["제미니", "Gemini"],
    "구글": ["Google"],
    "딥마인드": ["DeepMind"],
    "메타": ["Meta"],
    "마이크로소프트": ["Microsoft"],
    "엔비디아": ["앤비디아", "NVIDIA", "Nvidia"],
    "애플": ["Apple"],
    "아마존": ["Amazon"],
    "딥시크": ["딥식", "DeepSeek", "Deepseek"],
    "샘 올트먼": ["샘 알트만", "샘 올트만", "샘 알트먼", "Sam Altman"],
    "일론 머스크": ["엘론 머스크", "Elon Musk"],
}

# 일반인에게 어려운 단어: [단어 → 이렇게 바꿔 쓰라고 AI에게 알려줌]
HARD_WORDS = {
    "에이전트": "AI 비서",
    "범용": "여러 일을 두루 하는",
    "면책": "책임을 피하다",
    "파라미터": "빼기",
    "벤치마크": "성능 시험",
    "멀티모달": "글·사진·소리를 함께 이해하는",
    "오픈소스": "누구나 무료로 쓸 수 있게 공개한",
    "자바스크립트": "빼기",
    "LLM": "AI",
    "대규모 언어 모델": "AI",
    "API": "빼거나 '연결 기능'",
    "토큰": "빼기",
}

BANNED = ["더라고요", "거든요", "ㅋㅋ", "!!", "대박", "충격", "19금"]

EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-↪]")
# "16만 7천", "3분의 1", "5명 중 1명"처럼 붙어 있는 숫자 표현은 하나로 센다
NUMBER = re.compile(r"\d[\d,.]*(?:\s*(?:[만천억조]|분의|명\s*중)\s*\d*[\d,.]*)*")
# 숫자 바로 뒤에 붙은 외국 돈만 잡는다 ("이유로"의 '유로'는 안 잡힘)
FOREIGN_MONEY = re.compile(r"\d[\d,.]*\s*[만천억조]?\s*(?:\d[\d,.]*\s*[만천억조]?\s*)*(달러|유로|파운드|위안)")
MAX_LINE = 24
MAX_NUMBERS = 2  # 슬라이드 1장에 숫자 표현 최대 개수 (비교할 때만 2개)


def names_rule() -> str:
    """AI 지시문에 넣을 '정해진 이름 표기' 목록."""
    return ", ".join(NAMES)


def easy_rule() -> str:
    """AI 지시문에 넣을 '쉬운 말로 바꾸기' 목록."""
    return "\n".join(f"  - {w} → {e}" for w, e in HARD_WORDS.items())


def _fix_text(text: str) -> str:
    for right, wrongs in NAMES.items():
        for wrong in wrongs:
            text = text.replace(wrong, right)
    return text


def fix_names(card: dict) -> dict:
    """이름 표기를 정해진 표기로 바로 고친다 (AI 없이, 확실하게)."""
    card = dict(card)
    for key in ("hook_title", "subtitle", "takeaway", "caption", "action_tip"):
        if key in card:
            card[key] = _fix_text(card[key])
    if "title_options" in card:
        card["title_options"] = [_fix_text(t) for t in card["title_options"]]
    card["slides"] = [{"heading": _fix_text(s["heading"]), "body": _fix_text(s["body"])} for s in card["slides"]]
    card["hashtags"] = [_fix_text(h).replace(" ", "") for h in card["hashtags"]]
    return card


def find_problems(card: dict) -> list[str]:
    """규칙을 어긴 곳을 찾아서 사람이 읽을 수 있는 문장으로 돌려준다."""
    problems = []

    title = EMOJI.sub("", card["hook_title"]).strip()
    if len(title) > 22:
        problems.append(f"표지 제목이 너무 길어요({len(title)}자): 22자 이내로 줄이기")
    if len(EMOJI.findall(card["hook_title"])) > 1:
        problems.append("표지 제목에 이모지가 2개 이상: 1개까지만")

    options = card.get("title_options", [])
    if len(options) != 3:
        problems.append(f"제목 후보가 {len(options)}개: 질문형·숫자형·반전형 정확히 3개로")
    for t in options:
        if len(EMOJI.sub("", t).strip()) > 22:
            problems.append(f"제목 후보가 너무 길어요: '{t}' → 22자 이내로")
    if len(card.get("action_tip", "")) > 32:
        problems.append("action_tip이 너무 길어요: 30자 이내로")
    if len(card.get("share_target", "")) > 12:
        problems.append("share_target이 너무 길어요: 12자 이내로")

    want = 5 if card.get("kind") == "tip" else 4  # 꿀팁은 공감 1 + 방법 3 + 마무리 1
    if len(card["slides"]) != want:
        problems.append(f"슬라이드가 {len(card['slides'])}장: 정확히 {want}장으로")

    for n, s in enumerate(card["slides"], 1):
        lines = [l for l in s["body"].split("\n") if l.strip()]
        if len(lines) != 3:
            problems.append(f"{n}번 슬라이드 본문이 {len(lines)}줄: 정확히 3줄로 나누기")
        for line in lines:
            if len(line) > MAX_LINE:
                problems.append(f"{n}번 슬라이드 줄이 너무 길어요({len(line)}자): '{line}' → {MAX_LINE}자 이내로")
        text = s["heading"] + " " + s["body"]
        numbers = [m.strip() for m in NUMBER.findall(text)]
        if len(numbers) > MAX_NUMBERS:
            problems.append(f"{n}번 슬라이드에 숫자가 {len(numbers)}개({', '.join(numbers)}): 가장 중요한 1개만 남기기")
        if len(EMOJI.findall(text)) > 1:
            problems.append(f"{n}번 슬라이드에 이모지가 2개 이상: 1개까지만")

    visible = " ".join(
        [card["hook_title"], card["subtitle"], card["takeaway"], card["caption"], card.get("action_tip", "")]
        + card.get("title_options", [])
        + [s["heading"] + " " + s["body"] for s in card["slides"]]
    )
    for word, easy in HARD_WORDS.items():
        if word in visible:
            problems.append(f"어려운 단어 '{word}' 사용: '{easy}'(으)로 쉽게 바꾸기")
    for word in BANNED:
        if word in visible:
            problems.append(f"쓰면 안 되는 표현 '{word}' 사용: 다른 표현으로 바꾸기")
    for money in sorted(set(FOREIGN_MONEY.findall(visible))):
        problems.append(f"외국 돈 '{money}' 사용: 원화(약 OO원)로 바꾸기")

    return problems
