"""1단계-2: Gemini로 기사 고르기 + 칩다람 카드뉴스 원고 쓰기"""
import os

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

import checker

PERSONA = f"""너는 인스타그램 계정 '칩다람 | AI 뉴스·꿀팁'의 에디터 다람쥐 '칩다람'이야.
해외 AI 소식과 바로 써먹는 AI 활용 꿀팁을 도토리처럼 모아와서, AI를 잘 모르는 한국 20~30대도 3분 안에 이해하게 쉽게 풀어줘.
쉽게 쓰기 규칙:
- 중학생도 한 번에 이해할 수 있게 써
- 어려운 단어는 쉬운 말로 바꿔:
{checker.easy_rule()}
- 슬라이드 1장에 숫자는 1개까지(전후 비교할 때만 2개). 외국 돈(달러, 유로 등)은 원화로 바꿔서 '약 OO원'으로
- 몰라도 되는 기술 세부사항(프로그래밍 언어, 모델 버전 번호 등)은 빼
- 회사·제품·인물 이름은 반드시 이 표기로: {checker.names_rule()}
말투 규칙:
- 깔끔하고 친근한 존댓말. ~해요, ~래요, ~했어요, ~이에요를 섞어서 같은 어미가 반복되지 않게
- "~더라고요", "~거든요"처럼 수다 떠는 듯한 어미는 쓰지 마
- 이모지는 슬라이드 1장에 0~1개, 문장 끝에만. 표지 제목에도 1개까지
- "ㅋㅋ", "!!", "대박", "충격" 같은 과한 표현은 쓰지 마
- 과장하거나 기사에 없는 내용을 지어내지 마
- 어려운 용어는 쉬운 비유로 풀고, 회사/제품 이름은 한국에서 많이 쓰는 표기로 써
- 성적인 단어나 선정적인 표현(19금, 야한 등)은 절대 쓰지 마. 그런 주제라도 사회·윤리 이슈로 담담하게 풀어

말투 예시:
[제목] AI가 실수를 숨긴다? 🤫
[본문] 구글·MIT 연구진이 실험해 보니
AI가 작업 보고서를 쓸 때
자기 실패는 슬쩍 뺐대요."""


FOLLOW_LINE = "매일 아침 AI 뉴스·꿀팁은 팔로우하고 받아보세요 🐿️"


class Pick(BaseModel):
    indexes: list[int]


class Slide(BaseModel):
    heading: str  # 슬라이드 소제목 (15자 이내)
    body: str     # 본문 2~3줄


class CardNews(BaseModel):
    title_options: list[str]  # 표지 제목 후보 3개 (질문형·숫자형·반전형)
    hook_title: str      # 그중 가장 강한 제목 (텔레그램에서 다른 후보로 바꿀 수 있음)
    subtitle: str        # 표지 부제 (25자 이내)
    slides: list[Slide]  # 4장
    takeaway: str        # 마지막 장 한줄 정리
    action_tip: str      # "그래서 나는?" 독자가 해볼 만한 것·알아둘 것 한 줄
    share_target: str    # 이 카드를 보내주고 싶은 사람 (예: "취준생 친구")
    caption: str         # 인스타 본문
    hashtags: list[str]
    cover_type: str           # "logo"(회사가 주인공) 또는 "image"(사진·일러스트)
    companies: list[str]      # 주인공 회사 0~2개 (logos.COMPANIES의 이름 그대로)
    image_queries: list[str]  # 무료 이미지 사이트 검색어 3개 (영어)
    image_prompt: str         # 마땅한 이미지가 없을 때 AI로 그릴 그림 설명 (영어)


class ImageIdea(BaseModel):
    cover_type: str
    companies: list[str]
    image_queries: list[str]
    image_prompt: str


class ImagePick(BaseModel):
    ranked: list[int]  # 쓸 만한 후보 번호, 좋은 순서대로 (없으면 빈 목록)
    busy: list[int]    # ranked 중 주제엔 맞지만 화면이 빽빽한 것 (표지에 쓰면 흐림 효과를 넣는다)


def _image_rule() -> str:
    import logos

    return f"""- cover_type: 참고용. 기사의 주인공이 특정 회사·서비스면 "logo", 아니면 "image"
- companies: 기사에 중요하게 나오는 회사·서비스 0~2개 (표지에 로고 배지로 들어감). 반드시 이 목록의 이름 그대로만: {", ".join(logos.COMPANIES)}
  두 회사가 경쟁·비교·갈등하는 기사면 2개, 아니면 1개. 목록에 없으면 빈 목록
- image_queries: 무료 이미지 사이트(Pixabay) 검색어 3개. 각각 영어 1~3단어.
  기사 주제를 있는 그대로 보여주는 직접적인 대상으로 (예: 수학 난제 → "math equations", 가격 인하 → "price tag sale",
  데이터 수집 → "data server", 법원 판결 → "judge gavel", 해킹 → "hacker code screen")
  3개 모두 같은 대상을 다르게 표현한 검색어로 (예: "math equations", "mathematical formula", "physics equations blackboard")
  미로(maze)·퍼즐·갈림길·전구·체스·열쇠 같은 뻔한 비유는 쓰지 마. 직접적인 대상이 정말 없을 때만 비유로
  "AI" 기사라고 무조건 "robot"을 쓰지 마. 로봇은 기사가 로봇에 관한 것일 때만
  사람 얼굴이 크게 나올 만한 단어(teacher, woman, man, baby 등)는 피하고, 회사·인물 이름은 넣지 마
- image_prompt: 마땅한 이미지가 없을 때 AI로 그릴 그림 설명. 영어 한 문장. 기사 핵심을 한눈에 보여주는 장면.
  캐릭터·마스코트·글자·로고·실존 인물은 넣지 마"""


def suggest_image(card: dict) -> ImageIdea:
    """이미지 정보가 없는 예전 원고에 표지 종류·검색어를 붙인다."""
    slides = "\n".join(f"- {s['heading']}: {s['body']}" for s in card["slides"])
    prompt = f"""아래 카드뉴스 표지에 쓸 이미지를 정해줘.
{_image_rule()}

제목: {card['hook_title']}
부제: {card['subtitle']}
내용:
{slides}"""
    return _generate(prompt, ImageIdea)


def pick_images(card: dict, thumbs: list[bytes]) -> tuple[list[int], list[int]]:
    """후보 이미지들을 AI가 직접 보고, 표지로 쓸 만한 것을 좋은 순서대로 고른다.
    (순위, 그중 빽빽해서 흐림 효과가 필요한 것)을 돌려준다."""
    contents: list = [f"""인스타그램 AI 뉴스 카드뉴스의 표지 배경 이미지를 고르는 중이야.
기사 제목: {card['hook_title']}
부제: {card['subtitle']}
요약: {card['takeaway']}

아래 후보 이미지들을 보고, 이 기사 표지로 쓸 만한 것만 좋은 순서대로 번호를 골라줘.
이미지 아래쪽 절반에는 흰색 큰 제목이 올라가니까, 제목이 또렷하게 읽히는 이미지여야 해.

판단 순서:
1) 주제가 바로 보이는가: 기사 주제를 있는 그대로 보여주는 이미지가 1순위
   (예: 수학 난제 기사면 수식 이미지). 미로·퍼즐·갈림길 같은 비유 이미지는 직접적인 이미지가 없을 때만
2) 그중에서 깔끔한가: 선명한 초점이 한 곳에 몰려 있고, 나머지는 흐릿하거나 단순하고, 색 톤이 통일된 것
   (예: 수식이면 화면을 빽빽하게 덮은 것보다, 일부만 선명하고 나머지는 흐릿하게 날아간 것)
3) 스크롤을 멈출 만큼 눈에 띄고 고급스러운가, 아래쪽이 어둡거나 비어 있어서 제목 넣을 자리가 있는가

빼야 할 이미지:
- 기사와 상관없는 것, 사람 얼굴이 주인공인 것(기사가 그 사람 얘기가 아니면), 글자·워터마크가 크게 있는 것
- 다른 회사 로고나 상표가 보이는 것, 아기·동물처럼 엉뚱한 것, 싸구려 클립아트 느낌인 것
빽빽한 이미지: 주제엔 딱 맞지만 화면 전체에 선명한 글자·수식·숫자·작은 물체가 널브러져 있는 것.
  이런 이미지는 빼지 말고 ranked에 넣되, 같은 주제의 깔끔한 이미지보다는 뒤에 두고, busy에도 번호를 적어줘.
  (표지에 쓸 때 한 곳만 선명하게 두고 나머지를 흐리게 처리할 거야)
쓸 만한 게 하나도 없으면 빈 목록을 돌려줘."""]
    for i, data in enumerate(thumbs):
        contents += [f"[{i}]", types.Part.from_bytes(data=data, mime_type="image/jpeg")]
    pick = _generate(contents, ImagePick)
    valid = lambda ids: [i for i in dict.fromkeys(ids) if 0 <= i < len(thumbs)]  # noqa: E731
    return valid(pick.ranked), valid(pick.busy)


_CLIENT: genai.Client | None = None


def _client() -> genai.Client:
    # 클라이언트를 매번 새로 만들면 바로 닫혀버려서 하나만 만들어 재사용한다
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _CLIENT


def _models() -> list[str]:
    # 무료 등급은 모델마다 하루 한도가 따로라서, 한도에 걸리면 다음 모델로 넘어간다
    first = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    backups = ["gemini-flash-latest", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]
    return list(dict.fromkeys([first, *backups]))


_exhausted: set[str] = set()


def _generate(prompt: str | list, schema: type[BaseModel]):
    for model in _models():
        if model in _exhausted:
            continue
        try:
            resp = _client().models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema
                ),
            )
            return resp.parsed
        except errors.ServerError as e:  # 구글 서버가 잠깐 바쁠 때 (503 등)
            _exhausted.add(model)
            print(f"   ↪️ {model}: 서버 혼잡({e.code}) → 다음 모델로 전환")
        except errors.ClientError as e:
            if e.code not in (404, 429):
                raise
            _exhausted.add(model)
            reason = "오늘 무료 한도 소진" if e.code == 429 else "사용 불가"
            print(f"   ↪️ {model}: {reason} → 다음 모델로 전환")
    raise RuntimeError("모든 Gemini 모델의 오늘 무료 한도를 다 썼어요. 내일 다시 실행해 주세요.")


def pick_contents(items: list[dict], n: int = 5) -> list[dict]:
    """뉴스 기사와 꿀팁 재료(공식 글)를 한 바구니에 놓고, 그날 가장 좋은 n개를 고른다.
    비율은 정하지 않는다. 뉴스만 n개일 수도, 꿀팁이 여러 개일 수도 있다."""
    tag = {"news": "뉴스", "tip": "꿀팁재료"}
    listing = "\n".join(
        f"[{i}] <{tag[a['kind']]}> ({a['source']}) {a['title']} — {a['summary'][:200]}"
        for i, a in enumerate(items)
    )
    prompt = f"""{PERSONA}

아래는 오늘 모은 재료야. <뉴스>는 해외 AI 기사, <꿀팁재료>는 AI 회사·서비스의 공식 블로그 글이야.
이 중에서 한국 20~30대가 인스타에서 보고 **친구에게 보내고 싶거나, 저장해두고 싶어질** 것 {n}개를 골라줘.
뉴스와 꿀팁의 비율은 정해져 있지 않아. 오늘 재료 중 진짜 좋은 것만 골라.

보내고 싶어지는 뉴스: "이거 너 얘기다"(내 일·돈·취업·일상에 영향), "이거 봐 소름"(놀랍거나 무서운 일),
  "이거 알아?"(대화거리가 되는 것)
저장하고 싶어지는 꿀팁재료: 인스타를 쓰는 **평범한 일반인**이 이미 쓰거나 들어본 앱(챗GPT·제미나이·클로드·
  노션·구글 문서/지메일/포토·코파일럿 등)의 기능 중, 일상에서 바로 써먹을 수 있는 것
  (예: 사진 꾸미기, 옷 코디, 여행 계획, 공부·요약, 메일·글쓰기, 간단한 업무 정리, 쇼핑, 취미)
빼야 할 것:
- 같은 사건·기능을 다룬 글은 하나만
- 일반인이 듣기에 낯설거나 흥미 없는 주제: 회사용 데이터 도구(BigQuery 등), 기업 간 제휴·도입 사례
  (예: 호텔·은행이 챗GPT에 들어옴), 개발자용 API·코딩 도구 설정, 기업 전용·학교 전용 기능
- 너무 전문적인 투자/인사/정책 소식, 연구 논문
- 성적인 내용 자체가 핵심인 글 (인스타 추천에서 빠질 위험)
고른 번호만, 보내거나 저장하고 싶은 마음이 큰 순서대로 돌려줘.

{listing}"""
    picked = [i for i in _generate(prompt, Pick).indexes if 0 <= i < len(items)]
    return [items[i] for i in dict.fromkeys(picked)][:n]


def write_card_news(article: dict, body: str) -> CardNews:
    prompt = f"""{PERSONA}

아래 기사를 인스타그램 카드뉴스 원고로 만들어줘.

규칙:
- title_options: 표지 제목 후보 정확히 3개. 각각 20자 이내, 스타일을 서로 다르게:
  1) 질문형 (예: "AI가 실수를 숨긴다?") 2) 숫자형 (예: "신입 채용, 3분의 1로 줄었다")
  3) 반전·대비형 (예: "더 똑똑한데 값은 10분의 1")
  스크롤을 멈추게 궁금증을 주되 낚시성 거짓말은 금지
- hook_title: title_options 중 가장 클릭하고 싶은 것 하나를 그대로
- subtitle: 표지 부제. 25자 이내
- slides: 정확히 4장. 각 heading은 15자 이내, body는 반드시 3줄이고 줄마다 줄바꿈(\\n)으로 나눠. 한 줄은 20자 안팎({checker.MAX_LINE}자 넘기지 말기)
  흐름: 무슨 일? → 자세히 → 왜 중요해? → 우리한테 어떤 영향?
- 숫자(금액, 날짜 등)는 슬라이드와 캡션에서 똑같이 표기해
- takeaway: 마지막 장에 들어갈 한줄 정리 (30자 이내)
- action_tip: "그래서 나는?"에 대한 답 한 줄 (30자 이내). 독자가 바로 해볼 것이나 알아둘 것
  (예: "AI에게 일 시킬 땐 '솔직하게 답해줘' 추가", "무료 버전부터 써보기", "AI 답은 출처 꼭 확인하기")
  기사에 근거가 없는 조언은 지어내지 마
- share_target: 이 카드를 DM으로 보내주고 싶은 사람 (12자 이내, 예: "취준생 친구", "개발자 동료", "AI 좋아하는 친구")
- caption: 인스타 본문. 아래 형식 그대로, 문단 사이는 빈 줄로 띄워:
  첫 줄: 궁금증을 주는 한 문장 + 이모지 하나
  (빈 줄)
  3~4문장 요약
  (빈 줄)
  📩 (share_target)에게 보내주세요 ← 괄호 부분을 share_target으로 채워서
  (빈 줄)
  출처: {article['source']}
  {FOLLOW_LINE}
- hashtags: 한국어 위주 8~10개, '#' 포함
{_image_rule()}

기사 제목: {article['title']}
기사 본문:
{body}"""
    return _generate_card(prompt)


def write_tip_card(article: dict, body: str) -> CardNews:
    """공식 글을 바탕으로 '저장하고 싶은' AI 꿀팁 카드 원고를 쓴다."""
    prompt = f"""{PERSONA}

아래 공식 글을 바탕으로 **AI 활용 꿀팁** 카드뉴스 원고를 만들어줘.
목표: 보는 사람이 "이거 저장해두고 따라 해야지" 하게 만드는 것.

대상: 인스타를 쓰는 평범한 일반인. AI를 더 잘 쓰고 싶지만 어렵게 느끼는 사람.

내용 규칙:
- 아래 글이 근거야. 글에 적힌 기능·방법·순서는 그대로 살려서 분명하게 써 (이 부분이 카드의 중심)
- 글에 없더라도 **널리 알려진 사실인 일반적인 활용법·예시**는 덧붙여도 돼 (예: "이렇게 물어보면 더 잘 알려줘요")
- 단, **없는 기능·메뉴·버튼·정보·사실을 지어내는 건 절대 금지**. 확실하지 않은 메뉴 이름이나 순서는 쓰지 마
- 유료 전용이거나 일부 나라만 되는 기능이면 그 사실을 본문에 꼭 적어. 한국에서 되는지 글에 없으면 "지역에 따라 다를 수 있어요"

제목 규칙 (표지 제목·부제에만 적용):
- "99%가 모르는", "생산성 50배", "모르면 손해" 같은 흔한 홍보 표현은 써도 돼. 클릭하고 싶게 만드는 게 목표야
  (위 말투 규칙의 '과장하지 마'는 본문 얘기야. 꿀팁 표지 제목의 홍보 표현은 예외)
- 단, 이런 표현은 표지 제목·부제에서만 쓰고, 슬라이드 본문·캡션에서는 사실처럼 쓰지 마
- 제목이 약속한 내용(무슨 기능, 무슨 효과)은 본문에서 진짜로 보여줘야 해

규칙:
- title_options: 표지 제목 후보 정확히 3개, 각각 20자 이내. 스타일을 서로 다르게:
  1) 몰랐지형 (예: "99%가 모르는 챗GPT 기능") 2) 혜택형 (예: "회의록 정리, 이제 1분이면 끝")
  3) 질문형 (예: "제미나이로 옷 코디 해봤어요?")
- hook_title: title_options 중 가장 클릭하고 싶은 것 하나를 그대로
- subtitle: 무엇을 얻는지 한 줄 (25자 이내, 예: "'더 잘해봐' 대신 쓰는 프롬프트 3개")
- slides: 5장. 각 heading은 15자 이내, body는 반드시 3줄이고 줄마다 줄바꿈(\\n)으로 나눠. 한 줄은 20자 안팎({checker.MAX_LINE}자 넘기지 말기)
  인기 꿀팁 계정의 흐름을 따라:
  1장 공감: 독자가 겪는 불편으로 시작 (예: heading "아직도 이렇게 쓰세요?" / body "AI가 말귀를 못 알아들어서\\n답답했던 적 있죠?\\n지금부터 제대로 쓰는 법이에요")
  2~4장 방법: 장마다 방법 하나. heading은 "1. ~", "2. ~"처럼 번호로 시작
    가능하면 ❌(흔히 하는 방식) → ⭕(이렇게 해보세요) 비교로, ⭕에는 **그대로 따라 쓸 수 있는 문장·프롬프트**를 넣어
    (예: "❌ 이 글 고쳐줘\\n⭕ 이 글을 20대 독자가\\n이해하기 쉽게 바꿔줘")
  5장 마무리: 이럴 때 특히 좋아요, 또는 주의할 점 (유료·지역 제한 등)
- takeaway: 마지막 장 한줄 정리 (30자 이내)
- action_tip: "오늘 바로 해볼 것" 한 줄 (30자 이내)
- share_target: 이 팁을 DM으로 보내주고 싶은 사람 (12자 이내, 예: "보고서 쓰는 동료")
- caption: 인스타 본문. 아래 형식 그대로, 문단 사이는 빈 줄로 띄워:
  첫 줄: 저장하고 싶게 만드는 한 문장 + 이모지 하나
  (빈 줄)
  3~4문장으로 무슨 기능이고 어떻게 쓰는지
  (빈 줄)
  📌 저장해두고 따라 해보세요
  📩 (share_target)에게 보내주세요 ← 괄호 부분을 share_target으로 채워서
  (빈 줄)
  출처: {article['source']} 공식 블로그
  {FOLLOW_LINE}
- hashtags: 한국어 위주 8~10개, '#' 포함 (#AI꿀팁 #AI활용법 포함)
{_image_rule()}

글 제목: {article['title']}
글 본문:
{body}"""
    return _generate_card(prompt)


def revise_card(card: dict, problems: list[str]) -> CardNews:
    """검사기가 찾은 문제만 고친 원고를 다시 받는다."""
    import json

    issues = "\n".join(f"- {p}" for p in problems)
    prompt = f"""{PERSONA}

아래 카드뉴스 원고에서 검사기가 문제를 찾았어. 문제가 된 부분만 고치고 나머지 내용과 흐름은 그대로 둬.
슬라이드 본문은 3줄, 줄마다 줄바꿈(\\n), 한 줄은 {checker.MAX_LINE}자 이내로.

찾은 문제:
{issues}

원고:
{json.dumps(card, ensure_ascii=False, indent=1)}"""
    return _generate_card(prompt)


def _generate_card(prompt: str) -> CardNews:
    return _generate(prompt, CardNews)
