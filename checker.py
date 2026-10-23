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
MAX_TITLE = 26  # 표지 제목 ("아직도 야근해? AI로 칼퇴하는 법 알려줄게" 같은 질문+약속형이 들어가게)
MAX_HOOK2 = 18  # 2번째 장(두 번째 표지) 제목 길이
MAX_HIGHLIGHTS = 2  # 본문 한 장에 **강조** 최대 개수
HIGHLIGHT = re.compile(r"\*\*(.+?)\*\*", re.S)
# 소제목이 이런 명사로 뚝 끝나면 딱딱해요 ("애플 차에서 구글 AI 사용" → 말하듯이)
# AI 사이트 모음: 이런 말은 사이트 글에 근거가 있을 때만 쓸 수 있다 (AI가 그럴듯하게 지어내기 쉬운 것)
CLAIMS = {
    "무료": re.compile(r"free|무료|\$0|no cost", re.I),
    "가입 없이": re.compile(r"no sign.?up|without (an )?(account|sign)|no account|no registration|가입 없이|no login", re.I),
    "로그인 없이": re.compile(r"no login|no sign.?in|without (logging|sign)|no account|로그인 없이", re.I),
    "한국어": re.compile(r"korean|한국어", re.I),
    "광고 없": re.compile(r"no ads|ad.?free|광고 없", re.I),
    "무제한": re.compile(r"unlimited|무제한", re.I),
}
TOOL_HEADING_MAX = 24  # 사이트 장 큰 글씨 (2줄 합쳐서)
TOOL_NOTE_MAX = 32
NOUN_ENDINGS = ("사용", "출시", "도입", "발표", "탑재", "공개", "확대", "추가", "지원", "등장", "개발", "강화", "예정", "가능")
MAX_NUMBERS = 2  # 슬라이드 1장에 숫자 표현 최대 개수 (비교할 때만 2개)


def names_rule() -> str:
    """AI 지시문에 넣을 '정해진 이름 표기' 목록."""
    return ", ".join(NAMES)


def easy_rule() -> str:
    """AI 지시문에 넣을 '쉬운 말로 바꾸기' 목록."""
    return "\n".join(f"  - {w} → {e}" for w, e in HARD_WORDS.items())


def plain(text: str) -> str:
    """**강조** 표시를 뺀, 화면에 실제로 보이는 글자."""
    return text.replace("**", "")


def _fix_text(text: str) -> str:
    for right, wrongs in NAMES.items():
        for wrong in wrongs:
            text = text.replace(wrong, right)
    return text


def fix_names(card: dict) -> dict:
    """이름 표기를 정해진 표기로 바로 고친다 (AI 없이, 확실하게)."""
    card = dict(card)
    # **강조**는 본문(body)에만 쓴다. 다른 칸에 잘못 붙은 별표는 AI에게 다시 시키지 않고 바로 지운다
    for key in ("hook_title", "subtitle", "takeaway", "caption", "action_tip"):
        if key in card:
            card[key] = plain(_fix_text(card[key]))
    if "title_options" in card:
        card["title_options"] = [plain(_fix_text(t)) for t in card["title_options"]]
    # AI 사이트 모음은 큰 글씨(heading)가 본문 역할이라 거기 강조를 쓰고, 작은 글씨(body)엔 안 쓴다
    tools = card.get("kind") == "tools"
    head, body = (_fix_text, lambda t: plain(_fix_text(t))) if tools else (lambda t: plain(_fix_text(t)), _fix_text)
    card["slides"] = [{**s, "heading": head(s["heading"]), "body": body(s["body"]),
                       "bad": plain(_fix_text(s.get("bad", ""))), "good": plain(_fix_text(s.get("good", "")))}
                      for s in card["slides"]]
    card["hashtags"] = [_fix_text(h).replace(" ", "") for h in card["hashtags"]]
    return card


def _tool_problems(n: int, s: dict, card: dict) -> list[str]:
    """AI 사이트 모음의 사이트 장 하나: 길이·강조·명사 끝맺음 + '무료' 같은 말의 근거."""
    out = []
    lines = [plain(l).strip() for l in s["heading"].split("\n") if l.strip()]
    if len(lines) > 2:
        out.append(f"{n}번 사이트 큰 글씨가 {len(lines)}줄: 2줄 이내로")
    if len("".join(lines)) > TOOL_HEADING_MAX:
        out.append(f"{n}번 사이트 큰 글씨가 너무 길어요: 두 줄 합쳐 {TOOL_HEADING_MAX}자 이내로")
    marks = s["heading"].count("**")
    if marks % 2 or marks // 2 > MAX_HIGHLIGHTS:
        out.append(f"{n}번 사이트 큰 글씨의 강조(**)는 핵심 단어 1개만, 앞뒤 짝 맞추기")
    if lines and EMOJI.sub("", lines[-1]).strip(" ?!.~").endswith(NOUN_ENDINGS + ("제공",)):
        out.append(f"{n}번 사이트 큰 글씨가 명사로 끝나요: 말하듯이 (예: '퀴즈 생성 지원' → '자료가 퀴즈로 바뀐다')")
    if len(s["body"]) > TOOL_NOTE_MAX or "\n" in s["body"].strip():
        out.append(f"{n}번 사이트 작은 글씨는 한 줄 {TOOL_NOTE_MAX - 2}자 이내로")
    sites = card.get("sites", [])
    k = s.get("site_index", -1)
    page = sites[k]["page_text"] if 0 <= k < len(sites) else ""
    said = plain(s["heading"]) + " " + s["body"]
    for word, evidence in CLAIMS.items():
        if word in said and not evidence.search(page):
            out.append(f"{n}번 사이트({s.get('site')})에 '{word}'라고 썼는데 사이트 글에 근거가 없어요: 빼거나 사실대로 바꾸기")
    return out


def _caption_problems(card: dict) -> list[str]:
    """모범 사례(every._ai) 설득 순서 중 빠지기 쉬운 것: 탓 돌리기·상황별 저장·대상별 공유·첫 줄 길이."""
    out = []
    caption = card.get("caption", "")
    first = EMOJI.sub("", caption.strip().split("\n")[0]).strip()
    if len(first) > 45:
        out.append(f"캡션 첫 줄이 너무 길어요({len(first)}자): 아픈 곳+약속을 40자 이내로")
    if "'저장'" not in caption or "'공유'" not in caption:
        out.append("캡션 끝에 ✔️ '좋아요' / ✔️ (언제) 꺼내 보게 '저장' / ✔️ (누구)에게 '공유' 줄이 빠졌어요")
    if not card.get("save_when") or len(card.get("save_when", "")) > 14:
        out.append("save_when(저장해 두고 꺼내 볼 상황)을 12자 이내로 (예: '보고서 쓸 때')")
    if card.get("kind") in ("tip", "tools") and "아니라" not in caption:
        out.append("캡션에 '~해서가 아니라 ~가 없어서예요' 한 문장이 빠졌어요 (독자 탓이 아니라고 짚고 해결책으로)")
    if card.get("kind") in ("tip", "tools") and "1️⃣" not in caption:
        out.append("캡션에 1️⃣ 2️⃣ 3️⃣ 번호 목록이 빠졌어요")
    return out


def find_problems(card: dict) -> list[str]:
    """규칙을 어긴 곳을 찾아서 사람이 읽을 수 있는 문장으로 돌려준다."""
    problems = []

    title = EMOJI.sub("", card["hook_title"]).strip()
    if len(title) > MAX_TITLE:
        problems.append(f"표지 제목이 너무 길어요({len(title)}자): {MAX_TITLE}자 이내로 줄이기")
    if len(EMOJI.findall(card["hook_title"])) > 1:
        problems.append("표지 제목에 이모지가 2개 이상: 1개까지만")

    options = card.get("title_options", [])
    if not 3 <= len(options) <= 5:
        problems.append(f"제목 후보가 {len(options)}개: 3~5개로")
    for t in options:
        if len(EMOJI.sub("", t).strip()) > MAX_TITLE:
            problems.append(f"제목 후보가 너무 길어요: '{t}' → {MAX_TITLE}자 이내로")
    if len(card.get("action_tip", "")) > 32:
        problems.append("action_tip이 너무 길어요: 30자 이내로")
    if len(card.get("share_target", "")) > 12:
        problems.append("share_target이 너무 길어요: 12자 이내로")

    # 꿀팁은 공감 1 + 방법 3 + 마무리 1, AI 사이트 모음은 사이트 5개
    want = {"tip": (4, 5), "tools": (5, 5)}.get(card.get("kind"), (4, 4))  # 꿀팁은 약속에 맞는 방법만 2~3개
    if not want[0] <= len(card["slides"]) <= want[1]:
        problems.append(f"슬라이드가 {len(card['slides'])}장: {want[0]}~{want[1]}장으로")

    for n, s in enumerate(card["slides"], 1):
        if card.get("kind") == "tools":
            problems += _tool_problems(n, s, card)
            continue
        heading = EMOJI.sub("", s["heading"]).strip(" ?!.~")
        if n == 1:  # 두 번째 표지
            if len(heading) > MAX_HOOK2:
                problems.append(f"1번 슬라이드(두 번째 표지) 제목이 너무 길어요({len(heading)}자): {MAX_HOOK2}자 이내로")
            if heading == EMOJI.sub("", card["hook_title"]).strip(" ?!.~"):
                problems.append("1번 슬라이드 제목이 표지 제목과 같아요: 이 소식에서 가장 의외인 점을 살려 다른 말로")
        if heading.endswith(NOUN_ENDINGS):
            problems.append(f"{n}번 슬라이드 제목 '{s['heading']}'이 명사로 끝나요: 말하듯이 바꾸기"
                            " (예: '구글 AI 탑재' → '구글 AI가 떴다', '가격 인상 발표' → '값이 또 오른대요')")
        marks = s["body"].count("**")
        if marks % 2:
            problems.append(f"{n}번 슬라이드 강조 표시(**)의 짝이 안 맞아요: 단어를 **이렇게** 앞뒤로 감싸기")
        elif marks // 2 > MAX_HIGHLIGHTS:
            problems.append(f"{n}번 슬라이드에 강조가 {marks // 2}개: 가장 중요한 {MAX_HIGHLIGHTS}개까지만")
        elif any(len(h) > 12 or "\n" in h for h in HIGHLIGHT.findall(s["body"])):
            problems.append(f"{n}번 슬라이드 강조가 너무 길어요: 한 줄 안의 단어·짧은 구절만 감싸기")
        lines = [plain(l) for l in s["body"].split("\n") if l.strip()]
        bad, good = s.get("bad", "").strip(), s.get("good", "").strip()
        if bool(bad) != bool(good):
            problems.append(f"{n}번 슬라이드: ❌(bad)와 ⭕(good)는 둘 다 채우거나 둘 다 비우기")
        if bad and good:  # ❌/⭕ 비교 슬라이드: 설명은 0~1줄, ⭕ 문장은 2~3줄
            if len(lines) > 1:
                problems.append(f"{n}번 슬라이드(비교): 설명(body)은 1줄 이내로")
            if len(bad) > 30:
                problems.append(f"{n}번 슬라이드 ❌ 문장이 너무 길어요({len(bad)}자): 30자 이내로")
            good_lines = [l for l in good.split("\n") if l.strip()]
            if len(good_lines) > 3:
                problems.append(f"{n}번 슬라이드 ⭕ 문장이 {len(good_lines)}줄: 3줄 이내로")
            lines = lines + good_lines
        elif len(lines) != 3:
            problems.append(f"{n}번 슬라이드 본문이 {len(lines)}줄: 정확히 3줄로 나누기")
        for line in lines:
            if len(line) > MAX_LINE:
                problems.append(f"{n}번 슬라이드 줄이 너무 길어요({len(line)}자): '{line}' → {MAX_LINE}자 이내로")
        text = s["heading"] + " " + s["body"] + " " + bad + " " + good
        numbers = [m.strip() for m in NUMBER.findall(text)]
        if len(numbers) > MAX_NUMBERS:
            problems.append(f"{n}번 슬라이드에 숫자가 {len(numbers)}개({', '.join(numbers)}): 가장 중요한 1개만 남기기")
        if len(EMOJI.findall(text)) > 1:
            problems.append(f"{n}번 슬라이드에 이모지가 2개 이상: 1개까지만")

    problems += _caption_problems(card)

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
