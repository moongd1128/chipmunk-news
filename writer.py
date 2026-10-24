"""1단계-2: Gemini로 기사 고르기 + 칩다람 카드뉴스 원고 쓰기"""
import os
import re
import time
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

import checker

PERSONA = f"""너는 인스타그램 계정 '칩다람 | AI 뉴스·꿀팁'의 에디터 다람쥐 '칩다람'이야.
독자: **AI를 더 잘 쓰고, 더 잘 활용하고 싶은 한국 20~40대.**
  예를 들면 업무를 더 잘하고 싶은 직장인, 더 좋은 콘텐츠로 수익을 내고 싶은 크리에이터,
  혼자서 효율과 성과를 끌어올리고 싶은 1인 사업자·프리랜서, 과제·취업 준비에 AI를 쓰는 대학생·취준생.
  (이건 예시일 뿐, 특정 직업 하나만 노리지 마. 'AI를 더 잘 쓰고 싶다'는 마음이 공통점이야)
챗GPT·제미나이·클로드는 써 봤지만 '더 잘 쓰는 법'은 모르는 사람이야.
목표는 새 소식 전달이 아니라, 독자가 겪는 불편을 해결할 **도구·방법을 쥐여 주는 것**.
보는 사람이 "이거 내 일에 지금 바로 쓴다" 하고 저장·공유하게 만들어.
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
- 번역투 금지: 영어 원문을 한 단어씩 옮기지 말고, 한국 사람이 실제로 쓰는 자연스러운 말로
  (예: "지우는 순서를 알려줘" → "지우는 방법 알려줘", "~을 활용하여" → "~로", "~하는 것이 가능해요" → "~할 수 있어요")
- 어려운 용어는 쉬운 비유로 풀고, 회사/제품 이름은 한국에서 많이 쓰는 표기로 써
- 성적인 단어나 선정적인 표현(19금, 야한 등)은 절대 쓰지 마. 그런 주제라도 사회·윤리 이슈로 담담하게 풀어

말투 예시:
[제목] AI가 실수를 숨긴다? 🤫
[본문] 구글·MIT 연구진이 실험해 보니
AI가 작업 보고서를 쓸 때
자기 실패는 슬쩍 뺐대요."""


FOLLOW_LINE = "✔️ AI 더 잘 쓰는 법 계속 받고 싶다면 팔로우 @chipmunk.news.kr"

# 모범 사례(every._ai)의 설득 순서. 꿀팁·사이트 모음 원고는 이 순서로 쓴다 (checker.py가 캡션에서 일부를 검사)
FORMULA = """설득 순서 (꼭 이 순서로):
  ① 아픈 곳 + 약속: 독자가 AI를 쓰며(또는 일·콘텐츠·공부하며) 겪는 불편을 짚고, 얻을 결과를 약속
     (예: "보고서가 늘 뻔하다면, 이 3개만 바꿔봐요", "영상 하나 편집에 3시간 쓴다면", "자소서가 다 비슷해 보인다면")
  ② 탓 돌리기: "~해서가 아니라 ~가 없어서예요" (독자 실력 탓이 아니라고 짚고 해결책으로 연결)
     (예: "AI가 못해서가 아니라 기준을 안 줘서예요")
  ③ 핵심 한 줄: 왜 이 방법이어야 하는지 (예: "'알아서 해줘' 한 줄로는 안 돼요. 핵심은 역할을 정해 주는 거예요")
  ④ 번호 목록: 한 줄에 이득 하나, 구체적인 이름·문장으로
  ⑤ 믿을 근거: 공식 출처를 밝히기
  ⑥ 행동: 저장은 '언제 꺼내 볼지'(save_when), 공유는 '누구에게'(share_target)까지 구체적으로"""

# 캡션 끝 행동 문구 (좋아요·저장·공유·팔로우)
CTA_LINES = f"""  ✔️ 도움 됐다면 '좋아요'
  ✔️ (save_when) 꺼내 보게 '저장' ← 괄호를 save_when으로 채워서
  ✔️ (share_target)에게 '공유' ← 괄호를 share_target으로 채워서
  {FOLLOW_LINE}"""

# 표지 제목 말투 (뉴스·꿀팁 공통)
TITLE_WORDING = """  제목은 '이 게시물에 뭐가 들었는지'가 아니라 **보는 사람이 갖고 싶은 것, 또는 지금 겪는 '내' 문제**를 말해야 해.
  (2026-10-23 사용자 피드백: 내용을 설명하는 제목은 단조롭고 재미없어서 아무도 안 멈춘다)
    ❌ 내용 설명: "야근 줄여주는 AI 직원 6명", "앤트로픽이 밝힌 'AI 티 나는 디자인' 5가지", "엑셀 몰라도 되는 AI 문장 5개"
    ⭕ 갖고 싶은 결과·내 문제: "AI로 칼퇴하는 법", "나 대신 AI 야근시키는 법", "내 결과물이 AI 티 나는 이유",
       "앤트로픽이 밝힌 AI 티 안 나게 하는 법", "엑셀 하나도 몰라도 고수 되는 AI 문장 5개"
  사람을 멈추게 하는 장치 (후보마다 다른 장치를 써. 그대로 베끼지 말고 느낌을 살려):
    1) 누구나 탐내는 결과 한 단어: 칼퇴·퇴근·고수·인정·연봉 → "AI로 칼퇴하는 법"
    2) 역할 뒤집기·재밌는 장면: "나 대신 AI 야근시키는 법"
    3) 신분 변화(0 → 고수): "엑셀 하나도 몰라도 고수 되는 법"
    4) 내 문제 진단(~하는 이유): "내 결과물이 AI 티 나는 이유", "내 보고서만 늘 반려되는 이유"
    5) 콕 집어 부르기: "수식 검색에만 30분 쓰는 당신을 위한 AI 문장 5개"
    6) 큰 숫자 약속: "업무 효율 50배 올리는 법", "엑셀 100% 쓰는 법"
    7) 권위·비밀: "앤트로픽이 밝힌 ~", "일 잘하는 사람만 몰래 쓰는 ~"
    8) 뒤처지는 느낌: "아직도 ~ 손으로 해?", "모르면 나만 손해인 ~"
  제목 말투: 반말 OK ("~하는 법", "~한다고?"). 실제로 쓰는 쉬운 말(칼퇴·야근·반려·조회수·과제·고수)로 짧게.
    유행어(밤티·까인 등)는 가끔만, 20~30대가 주로 볼 주제일 때만. 40대도 보는 계정이라 남발하지 마
    핵심 단어는 앞쪽 10자 안에. 기능 이름·업계 용어·딱딱한 말(기능 소개, 활용 방안, 지원)은 쓰지 마
  방법(답)은 제목에서 다 말하지 마. 결과만 약속하고 방법은 넘겨서 보게 해
    ❌ "옷 사기 전에 AI로 입어보기" (방법을 다 알려줌) → ⭕ "옷 고를 때 실패 안 하는 법"
  '무엇이 들었는지'(직원 6명, 문장 5개, 스킬 4개)는 부제가 맡아. 제목에 숫자를 넣는다면 결과·문제와 함께
  다듬기 (사용자가 직접 고친 예에서 배운 것):
    - "~ 방법"·억지 숫자(0%) 대신 말하듯이: "AI 느낌 0% 만드는 디자인 방법" → "AI 느낌 아예 안 나게 하는 법"
    - 결과를 바로 말하는 가장 짧은 말이 이긴다: "나 대신 AI 야근시키는 법" → "AI로 칼퇴하는 법"
    - 흐릿한 말(잡무·고생·효율) 대신 구체적인 아픈 말(야근·칼퇴·반려): "아직도 잡무 혼자 다 고생해?" →
      "아직도 야근해? AI로 칼퇴하는 법 알려줄게" (질문 + 약속을 친구처럼)
    - 내용 개수는 빼고 누가 하는지 분명하게: "내 업무 6가지 다 넘기는 법" → "내 업무 AI한테 다 넘기는 법"
    - 제목에는 이모지를 넣지 마
    - 줄어드는 시간·늘어나는 성과는 흐릿한 말(절반·확·많이) 대신 구체적인 숫자로: "일하는 시간 절반으로 줄이는 법" →
      "업무 시간 30분 단축하는 법", "회의록 50% 단축" (단, 'AI 느낌 0%'처럼 숫자가 억지스러운 곳엔 쓰지 마)
  이 계정은 'AI 잘 쓰는 법' 계정이야. 제목에 AI가 꼭 들어갈 필요는 없지만, **AI가 들어가면 더 좋은 주제·때가 많아**
    (AI로·AI한테·AI 티·챗GPT·제미나이 등). AI가 빠지면 그냥 발표 꿀팁·공부 꿀팁처럼 보이지 않는지 생각해 봐
    ❌ "내 맘에 쏙 드는 발표 자료 만드는 법" (흔한 발표 꿀팁처럼 보임) → ⭕ "AI 티 안 나게 발표 자료 잘 만드는 법"
  AI가 뭔가를 만들어 주는 주제(발표 자료·디자인·글·그림·영상·자소서)는 **'AI 티 안 나게'가 강한 각도**야 (사용자가 좋아함). 후보에 넣어 봐
  **제목만 보고 '누구의 무슨 일'인지 바로 떠올라야 해** (2026-10-24 사용자 피드백):
    확실한 타깃(대학생·직장인·유튜버·자영업자·취준생) 또는 구체적인 물건·아픔 키워드(시험 공부·수업 노트·보고서·
    회의록·PPT·엑셀·자소서·썸네일·상세페이지)를 꼭 하나 넣어. '자료·정리·업무·작업·콘텐츠' 같은 막연한 말만으로는 안 돼
    방법·기능 이름(채팅 한 줄, @ 기호, 메뉴, 노트 기능)은 제목에 넣지 마. 그건 넘겨서 보는 것
    ❌ "채팅 한 줄로 자료 1초 만에 정리하는 법" (누구의 무슨 자료? 방법만 보임)
    ⭕ "시험 기간에 수업 노트 1초 만에 찾는 법", "대학생이 몰래 쓰는 제미나이 공부법" 처럼"""


# 2번째 장 = 두 번째 표지 (뉴스·꿀팁 공통)
# 인스타는 첫 장만 보고 지나간 사람에게 캐러셀 2번째 장을 다시 보여준다. 그래서 2번째 장도 그것만으로 멈추게 해야 한다
SECOND_HOOK = """- slides의 첫 장(카드 전체로는 2번째 장)은 **두 번째 표지**야.
  인스타는 표지만 보고 지나간 사람에게 이 장을 다시 보여줘. 이 장만 봐도 손가락이 멈춰야 해
  이 장의 heading: **이 소식에서 가장 의외인 점**(누가? 왜 하필? 이게 된다고?)을 살린 두 번째 제목. 18자 이내, 말하듯이
    표지 제목과 다른 말로, 다른 각도에서
    ❌ "차에서 말로 길 찾기, 이제 돼요" (원래 되던 당연한 기능 → 재미없음)
    ❌ "애플 차에서 구글 AI 사용" (밋밋한 설명, 명사로 끝남)
    ⭕ "애플 차 화면에 구글 AI가 떴다", "아이폰 유저도 차에서 구글 AI 써요" (경쟁사 AI가 애플 화면에 → 의외성)
    원문에 없는 해석·과장은 금지 (예: 원문에 없는데 "애플이 자리를 내줬다")"""

# 슬라이드 공통 말투·강조
SLIDE_STYLE = """- 모든 heading은 말하듯이 끝내. "~ 사용", "~ 출시", "~ 탑재", "~ 공개"처럼 명사로 뚝 끊지 마
  (❌ "가격 인상 발표" → ⭕ "값이 또 오른대요")
- body(설명 문장)에서 **가장 중요한 단어 1~2개만** 별표 두 개로 감싸 (예: "**구글 지도**에 제미나이가 들어왔어요")
  카드에서 색으로 강조돼서 대충 넘겨봐도 핵심이 보여. 한 줄 안에서만, 문장 전체를 감싸지 말고 단어·짧은 구절만
  heading·bad·good·caption 등 body 말고는 별표를 쓰지 마"""


class Pick(BaseModel):
    indexes: list[int]


class Slide(BaseModel):
    heading: str    # 슬라이드 소제목 (15자 이내, 첫 장은 두 번째 표지라 18자 이내)
    body: str       # 본문 3줄, 핵심 단어 1~2개는 **강조** (❌/⭕ 비교 슬라이드면 짧은 설명 1줄 또는 빈칸)
    bad: str = ""   # 꿀팁 비교용: 흔히 하는 방식 (❌ 박스). 비교가 아니면 빈칸
    good: str = ""  # 꿀팁 비교용: 그대로 따라 쓸 수 있는 좋은 방식 (⭕ 박스). 비교가 아니면 빈칸


class CardNews(BaseModel):
    title_options: list[str]  # 표지 제목 후보 3개 (질문형·숫자형·반전형)
    hook_title: str      # 그중 가장 강한 제목 (텔레그램에서 다른 후보로 바꿀 수 있음)
    subtitle: str        # 표지 부제 (25자 이내)
    slides: list[Slide]  # 4장
    takeaway: str        # 마지막 장 한줄 정리
    action_tip: str      # "그래서 나는?" 독자가 해볼 만한 것·알아둘 것 한 줄
    share_target: str    # 이 카드를 보내주고 싶은 사람 (예: "보고서 쓰는 동료")
    save_when: str = ""  # 저장해 두고 꺼내 볼 상황 (예: "보고서 쓸 때")
    caption: str         # 인스타 본문
    hashtags: list[str]
    cover_type: str           # "logo"(회사가 주인공) 또는 "image"(사진·일러스트)
    companies: list[str]      # 주인공 회사 0~2개 (logos.COMPANIES의 이름 그대로)
    rivalry: bool = False     # 두 회사가 경쟁·대결하는 기사면 True (표지에 VS), 협력이면 False (표지에 ×)
    image_queries: list[str]  # 무료 이미지 사이트 검색어 3개 (영어)
    image_prompt: str         # 마땅한 이미지가 없을 때 AI로 그릴 그림 설명 (영어)


class ToolItem(BaseModel):
    site: int     # 아래 사이트 목록의 번호
    name: str     # 사이트 이름 (영어 그대로, 예: "Poe")
    heading: str  # 이 사이트로 얻는 것 (2줄, 줄바꿈 \n, 핵심 단어 1개 **강조**)
    note: str     # 솔직한 한 줄 (무료 범위·제한 등, 사이트 글에 근거가 있는 것만)


class ToolsCard(BaseModel):
    title_options: list[str]
    hook_title: str
    subtitle: str
    items: list[ToolItem]  # 정확히 5개, 가장 놀라운 사이트부터
    takeaway: str
    share_target: str
    save_when: str = ""
    caption: str
    hashtags: list[str]
    image_queries: list[str]
    image_prompt: str


class ToolPick(BaseModel):
    theme: str          # 고른 도구들을 묶는 하나의 일 상황 (예: "발표 자료 만들 때")
    indexes: list[int]


class ImageIdea(BaseModel):
    cover_type: str
    companies: list[str]
    rivalry: bool = False
    image_queries: list[str]
    image_prompt: str


class ImagePick(BaseModel):
    ranked: list[int]  # 쓸 만한 후보 번호, 좋은 순서대로 (없으면 빈 목록)
    busy: list[int]    # ranked 중 주제엔 맞지만 화면이 빽빽한 것 (표지에 쓰면 흐림 효과를 넣는다)


def _image_rule() -> str:
    import logos

    return f"""- cover_type: 참고용. 기사의 주인공이 특정 회사·서비스면 "logo", 아니면 "image"
- companies: 기사에 중요하게 나오는 회사·서비스 0~2개 (표지에 로고 배지로 들어감). 반드시 이 목록의 이름 그대로만: {", ".join(logos.COMPANIES)}
  서로 다른 두 회사가 함께 주인공인 기사면 2개, 아니면 1개. 목록에 없으면 빈 목록
  회사와 그 회사의 제품(오픈AI와 챗GPT, 구글과 제미나이 등)은 같은 쪽이니 둘 다 넣지 말고 제품 하나만
- rivalry: companies가 2개이고 두 회사가 **경쟁·대결·갈등**하는 기사면 true (표지에 VS로 나옴).
  협력·제휴·인수처럼 같은 편이면 false. 회사가 1개 이하면 false
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
        # 요청 하나에 최대 2분: 구글 서버가 멈춘 듯 느릴 때 하염없이 기다리지 않고 다음 모델로 넘어간다
        _CLIENT = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                               http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
    return _CLIENT


REQUEST_TIMEOUT_MS = 120_000


def _models() -> list[str]:
    # 무료 등급은 모델마다 하루 한도가 따로라서, 한도에 걸리면 다음 모델로 넘어간다
    first = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    backups = ["gemini-flash-latest", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]
    return list(dict.fromkeys([first, *backups]))


_exhausted: set[str] = set()


def _generate(prompt: str | list, schema: type[BaseModel], think: bool = False):
    """think=False면 AI가 답하기 전에 '생각'하는 시간을 줄인다 (고르기·검사처럼 단순한 일은 2배 빨라짐).
    원고 쓰기처럼 품질이 중요한 일만 think=True."""
    extra = {} if think else {"thinking_config": types.ThinkingConfig(thinking_level="low")}
    for model in _models():
        if model in _exhausted:
            continue
        started = time.time()
        try:
            resp = _client().models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema, **extra
                ),
            )
            print(f"   ⏱️ AI 응답 {time.time() - started:.0f}초 ({model})")
            return resp.parsed
        except (errors.ServerError, httpx.TimeoutException) as e:  # 구글 서버가 바쁘거나 2분 넘게 답이 없을 때
            # 혼잡은 잠깐인 경우가 많아서, 이번 요청만 다음 모델로 넘기고 다음 요청 땐 좋은 모델부터 다시 시도한다
            # (한도 소진(429)과 달리 영구 제외하지 않음 → 하루 종일 가벼운 모델로만 쓰는 일 방지)
            why = f"서버 혼잡({e.code})" if isinstance(e, errors.ServerError) else "2분 넘게 응답 없음"
            print(f"   ↪️ {model}: {why} → 이번만 다음 모델로")
        except errors.ClientError as e:
            if e.code not in (404, 429):
                raise
            _exhausted.add(model)
            reason = "오늘 무료 한도 소진" if e.code == 429 else "사용 불가"
            print(f"   ↪️ {model}: {reason} → 다음 모델로 전환")
    raise RuntimeError("모든 Gemini 모델의 오늘 무료 한도를 다 썼어요. 내일 다시 실행해 주세요.")


MAX_NEWS = 1  # 하루에 뉴스는 이만큼만 (타깃: AI로 일 잘하고 싶은 사람 → 꿀팁·도구 중심)


def pick_contents(items: list[dict], n: int = 10) -> list[dict]:
    """뉴스 기사와 꿀팁 재료(공식 글)를 한 바구니에 놓고, 그날 가장 좋은 n개를 고른다.
    비율은 정하지 않는다. 뉴스만 n개일 수도, 꿀팁이 여러 개일 수도 있다."""
    tag = {"news": "뉴스", "tip": "꿀팁재료"}
    listing = "\n".join(
        f"[{i}] <{tag[a['kind']]}> ({a['source']}) {a['title']} — {a['summary'][:200]}"
        for i, a in enumerate(items)
    )
    prompt = f"""{PERSONA}

아래는 오늘 모은 재료야. <뉴스>는 해외 AI 기사, <꿀팁재료>는 AI 회사·서비스의 공식 블로그 글이야.
이 중에서 독자가 보고 **"이거 지금 바로 써먹는다" 하며 저장하거나 친구·동료에게 보내고 싶어질** 것을 **최대 {n}개** 골라줘.
보통 3~5개면 충분해. 하지만 **정말 흥미롭고 좋은 게 쏟아지는 날엔 {n}개까지 다 골라** — 좋은 주제를 버리는 게 더 손해야.
반대로 **좋은 게 없으면 적게 골라도 돼 (0개도 괜찮아).** 개수나 뉴스·꿀팁 비율을 채우려고 재미없는 걸 넣지 마.
독자는 새 소식보다 AI를 더 잘 쓰는 방법을 원해.

저장하고 싶어지는 꿀팁재료: 챗GPT·제미나이·클로드·노션·구글 문서/지메일/시트·코파일럿 등의 기능 중
  일·콘텐츠 만들기·사업·공부·취업 준비에 바로 써먹을 수 있는 것
뉴스는 **AI를 쓰는 사람에게 바로 영향이 있거나, 바로 쓸 새 기능**일 때만 (하루 {MAX_NEWS}개까지만 남겨요)
빼야 할 것:
- 같은 사건·기능을 다룬 글은 하나만
- 독자와 상관없는 소식: 기업 간 제휴·투자·인사·정책·소송·연구 논문, 대기업 관리자용 설정
- 개발자만 쓰는 API·서버 설정 (비개발자도 따라 할 수 있는 클로드 코드·자동화 이야기는 가끔 OK)
- 성적인 내용 자체가 핵심인 글 (인스타 추천에서 빠질 위험)
고른 번호만, 보내거나 저장하고 싶은 마음이 큰 순서대로 돌려줘.

{listing}"""
    picked = [items[i] for i in dict.fromkeys(_generate(prompt, Pick).indexes) if 0 <= i < len(items)]
    # 뉴스는 하루 MAX_NEWS개까지만 (AI가 뉴스를 여러 개 고르는 일이 잦아서 코드로)
    out, news_n = [], 0
    for a in picked:
        if a["kind"] == "news":
            if news_n >= MAX_NEWS:
                continue
            news_n += 1
        out.append(a)
    return out[:n]


def write_card_news(article: dict, body: str) -> CardNews:
    prompt = f"""{PERSONA}

아래 기사를 인스타그램 카드뉴스 원고로 만들어줘.

규칙:
- title_options: 표지 제목 후보 정확히 3개. 각각 20자 이내, 스타일을 서로 다르게:
  1) 질문형 (예: "AI가 실수를 숨긴다?") 2) 숫자형 (예: "신입 채용, 3분의 1로 줄었다")
  3) 반전·대비형 (예: "더 똑똑한데 값은 10분의 1")
  스크롤을 멈추게 궁금증을 주되 낚시성 거짓말은 금지
{TITLE_WORDING}
- hook_title: title_options 중 가장 클릭하고 싶은 것 하나를 그대로
- subtitle: 표지 부제. 25자 이내
- slides: 정확히 4장. 각 heading은 15자 이내, body는 반드시 3줄이고 줄마다 줄바꿈(\\n)으로 나눠. 한 줄은 20자 안팎({checker.MAX_LINE}자 넘기지 말기)
  흐름: 무슨 일?(두 번째 표지) → 자세히 → 왜 중요해? → 우리한테 어떤 영향?
{SECOND_HOOK}
{SLIDE_STYLE}
- 숫자(금액, 날짜 등)는 슬라이드와 캡션에서 똑같이 표기해
- takeaway: 마지막 장에 들어갈 한줄 정리 (30자 이내)
- action_tip: "그래서 나는?"에 대한 답 한 줄 (30자 이내). 독자가 바로 해볼 것이나 알아둘 것
  (예: "AI에게 일 시킬 땐 '솔직하게 답해줘' 추가", "무료 버전부터 써보기", "AI 답은 출처 꼭 확인하기")
  기사에 근거가 없는 조언은 지어내지 마
- share_target: 이 카드를 보내주고 싶은 사람 (12자 이내, 예: "같은 팀 동료", "마케터 친구")
- save_when: 저장해 두고 꺼내 볼 상황 (12자 이내, 예: "AI 도입 고민할 때")
- caption: 인스타 본문. 아래 형식 그대로, 문단 사이는 빈 줄로 띄워:
  첫 줄: 궁금증을 주는 한 문장 + 이모지 하나
  (빈 줄)
  3~4문장 요약. 마지막 문장은 '내 일에 어떤 영향인지'
  (빈 줄)
  💛 출처: {article['source']} (원문 링크는 프로필에 🔗)
  (빈 줄)
{CTA_LINES}
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

대상: AI를 더 잘 쓰고 싶은 사람 (직장인·크리에이터·1인 사업자·프리랜서·대학생·취준생 등). 그 사람이 겪는 불편이 출발점이야.

{FORMULA}

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
  1) 아픈 곳+약속형 (예: "보고서가 늘 뻔하다면, 이 3개", "회의록 1시간 → 5분 만드는 법")
  2) 몰랐지형 (예: "일 잘하는 사람만 아는 챗GPT 설정")
  3) 질문형 (예: "AI한테 맡겨도 결과가 별로야?")
{TITLE_WORDING}
- hook_title: title_options 중 가장 클릭하고 싶은 것 하나를 그대로
- subtitle: 무엇을 얻는지 한 줄 (25자 이내, 예: "'더 잘해봐' 대신 쓰는 프롬프트 3개")
- **모든 방법 장은 표지 제목이 약속한 것 하나를 지켜야 해.** 글에 기능이 여러 개 섞여 있어도
  약속과 상관없는 기능은 넣지 마 (2026-10-24: "인터넷 쇼핑 실패 줄이는 법"에 '재킷 색 바꾸기'·'옷 얼룩 지우기'를
  넣었더니 보던 사람이 그 장에서 다 나갔어). 약속에 맞는 방법이 2개뿐이면 2개만 써
- slides: 4~5장 (공감 1 + 방법 2~3 + 마무리 1). 각 heading은 15자 이내. 한 줄은 20자 안팎({checker.MAX_LINE}자 넘기지 말기)
  인기 꿀팁 계정의 흐름을 따라:
  1장 공감(① + ②): 독자가 겪는 불편 2줄 + "~해서가 아니라 ~가 없어서예요" 1줄. body 3줄(줄마다 \\n). bad·good은 빈칸
    (예: heading "보고서가 늘 밋밋하다면" / body "AI한테 맡겨도\\n결과가 뻔하게 나오죠\\nAI가 아니라 기준이 없어서예요")
  방법 장(2~3개): 장마다 방법 하나, 모두 같은 약속을 지키는 방법. heading은 "1. ~", "2. ~"처럼 번호로 시작
    ❌/⭕ 비교로 보여줄 수 있으면 bad와 good을 채워 (화면에 ❌ 회색 박스, ⭕ 주황 박스로 나뉘어 나와요):
      bad: 사람들이 흔히 하는 방식 한 문장 (따옴표 없이, 30자 이내)
      good: **그대로 복사해서 쓸 수 있는** 문장·프롬프트 (따옴표 없이, 2~3줄, 줄마다 \\n, 한 줄 {checker.MAX_LINE}자 이내)
        한국 사람이 AI한테 실제로 말하듯 자연스럽게 (번역투 X)
      body: 왜 좋은지 짧게 1줄, 또는 빈칸
      (예: heading "1. 대상을 정해주기" / bad "이 글 고쳐줘" / good "이 글을 20대 독자가\\n이해하기 쉽게\\n바꿔줘" / body "누구에게 쓰는지 알면 훨씬 정확해요")
    비교가 어색한 방법이면 bad·good은 빈칸으로 두고 body를 3줄로 (줄마다 \\n)
  5장 마무리(③): 핵심 한 줄 + 이럴 때 특히 좋아요 또는 주의할 점 (유료·지역 제한 등). body 3줄, bad·good은 빈칸
{SECOND_HOOK}
    꿀팁은 1장(공감) heading이 두 번째 표지야. 독자가 "어 내 얘기네" 하고 뜨끔하게 (예: "AI한테 물어봐도 엉뚱한 답만 와?")
{SLIDE_STYLE}
- takeaway: 마지막 장 한줄 정리 (30자 이내)
- action_tip: "오늘 바로 해볼 것" 한 줄 (30자 이내)
- share_target: 이 팁을 보내주고 싶은 사람 (12자 이내, 예: "보고서 쓰는 동료")
- save_when: 저장해 두고 꺼내 볼 상황 (12자 이내, 예: "보고서 쓸 때", "회의 끝나고")
- caption: 인스타 본문. 아래 형식 그대로 (설득 순서 ①~⑥):
  첫 줄: ① 아픈 곳 + 약속 + 이모지 하나 (40자 이내)
  (빈 줄)
  독자가 겪는 불편 2~3줄 (한 줄씩 짧게)
  (빈 줄)
  ② "~해서가 아니라 ~가 없어서예요." 한 문장
  ③ 핵심 한 줄
  (빈 줄)
  1️⃣ 방법 한 줄 (얻는 것 위주)
  2️⃣ …
  3️⃣ …
  (빈 줄)
  💛 근거: {article['source']} 공식 블로그 (원문 링크는 프로필에 🔗)
  (빈 줄)
{CTA_LINES}
- hashtags: 한국어 위주 8~10개, '#' 포함 (#AI꿀팁 #AI활용법 포함)
{_image_rule()}

글 제목: {article['title']}
글 본문:
{body}"""
    return _generate_card(prompt)


def revise_card(card: dict, problems: list[str]) -> CardNews | ToolsCard:
    """검사기가 찾은 문제만 고친 원고를 다시 받는다."""
    import json

    issues = "\n".join(f"- {p}" for p in problems)
    if card.get("kind") == "tools":
        import tools

        shown = {k: card[k] for k in ToolsCard.model_fields if k in card and k != "items"}
        shown["items"] = tools.model_items(card)
        sites = "\n\n".join(f"[{i}] {s['name']} ({s['domain']})\n{s['page_text'][:1500]}"
                             for i, s in enumerate(card["sites"]))
        prompt = f"""{PERSONA}

아래 'AI 사이트 모음' 카드 원고에서 검사기가 문제를 찾았어. 문제가 된 부분만 고치고 나머지는 그대로 둬.
사이트 글에 없는 내용(무료, 가입 없이, 한국어 지원 등)은 쓰지 마.

찾은 문제:
{issues}

원고:
{json.dumps(shown, ensure_ascii=False, indent=1)}

사이트 글:
{sites}"""
        return _generate(prompt, ToolsCard)
    prompt = f"""{PERSONA}

아래 카드뉴스 원고에서 검사기가 문제를 찾았어. 문제가 된 부분만 고치고 나머지 내용과 흐름은 그대로 둬.
슬라이드 본문은 3줄, 줄마다 줄바꿈(\\n), 한 줄은 {checker.MAX_LINE}자 이내로.

찾은 문제:
{issues}

원고:
{json.dumps(card, ensure_ascii=False, indent=1)}"""
    return _generate_card(prompt, think=False)  # 지적받은 곳만 고치는 일이라 빠르게


def pick_tools(cands: list[dict], n: int) -> tuple[str, list[int]]:
    """Product Hunt 신상 AI 도구 중, 독자가 겪는 **하나의 일 상황**으로 묶이는 것을 고른다.
    ('새로 나온 도구 아무거나 5개'보다 '발표 자료 만들 때 쓰는 AI 5개'가 저장·공유가 훨씬 잘 돼서)"""
    listing = "\n".join(f"[{i}] {c['name']} — {c['tagline']}" for i, c in enumerate(cands))
    prompt = f"""{PERSONA}

아래는 최근 나온 AI 도구 목록이야. 먼저 독자가 자주 겪는 **상황 하나**를 정하고
(예: "발표 자료 만들 때", "영상 편집할 때", "회의록 정리할 때", "마케팅 글 쓸 때", "혼자 사업할 때",
 "과제·논문 읽을 때", "자소서·포트폴리오 만들 때", "말로 앱 만들어 볼 때"),
그 상황에 쓸 수 있는 도구를 {n}개까지 골라줘. 그 상황에 맞는 도구가 가장 많은 상황으로 정해.

좋은 도구: 그 상황에서 결과가 눈에 보이는 것, 무료로 써볼 수 있어 보이는 것, 설명만 봐도 뭔지 아는 것
빼야 할 것: 개발자만 쓰는 것(서버·API·코드 리뷰), 대기업 관리자용, 투자·코인, 성인용
(비개발자도 말로 쓸 수 있는 코딩·자동화 도구는 OK)
theme에는 그 상황(예: "발표 자료 만들 때"), indexes에는 고른 번호를 좋은 순서대로.

{listing}"""
    pick = _generate(prompt, ToolPick)
    picked = [i for i in dict.fromkeys(pick.indexes) if 0 <= i < len(cands)]
    return pick.theme, picked[:n]


def write_tools_card(sites: list[dict], theme: str = "") -> ToolsCard:
    """확인한 사이트 5개로 'AI 사이트 모음' 카드 원고를 쓴다. 사이트 글이 유일한 근거."""
    listing = "\n\n".join(f"[{i}] {s['name']} ({s['domain']}) — {s['tagline']}\n사이트 글:\n{s['page_text'][:1500]}"
                           for i, s in enumerate(sites))
    prompt = f"""{PERSONA}

아래 AI 사이트 5개로 **'AI 사이트 모음'** 카드뉴스 원고를 만들어줘.
목표: 보는 사람이 끝까지 넘겨보고 "저장해두고 하나씩 써봐야지" 하게 만드는 것.
오늘의 일 상황: **{theme or "일할 때"}** — 표지 제목·캡션 첫 줄은 이 상황의 아픈 곳에서 시작해.

{FORMULA}

카드 모양: 표지 → 사이트 1장에 하나씩 5장(위에 사이트 주소, 가운데 사이트 화면 캡처, 아래 큰 글씨 2줄 + 작은 글씨 1줄) → 정리

내용 규칙 (가장 중요):
- 각 사이트 설명의 근거는 아래 '사이트 글'뿐이야. 사이트 글에 없는 기능·가격·조건은 절대 쓰지 마
- "무료", "가입 없이", "로그인 없이", "한국어 지원", "광고 없음" 같은 말은 사이트 글에 그렇게 적혀 있을 때만
- 무료라도 제한(횟수·용량 등)이 사이트 글에 있으면 note에 솔직하게 적어

규칙:
- title_options: 표지 제목 후보 정확히 3개, 각각 20자 이내. 일 상황 + 숫자 5개를 약속하는 목록형, 스타일은 서로 다르게
  (예: "발표 자료 밤티 난다면, 이 5개", "PPT 1시간 줄여주는 AI 5개", "이거 불법 아냐? 싶은 발표 AI 5개")
  "불법 아냐?", "99%가 모르는" 같은 홍보 표현은 표지 제목·부제에서만 OK. 본문·캡션에선 사실처럼 쓰지 마
{TITLE_WORDING}
- hook_title: title_options 중 가장 강한 것 하나를 그대로
- subtitle: 25자 이내 (예: "전부 무료로 시작할 수 있는 사이트")
- items: 정확히 5개. **가장 놀라운 사이트를 첫 번째로** (첫 사이트 장이 두 번째 표지 역할을 해)
  - site: 위 목록 번호 그대로, name: 사이트 이름 (영어 그대로, 짧게)
  - heading: 이 사이트로 **얻는 것**을 2줄로 (줄바꿈 \\n, 한 줄 12자 안팎, 전체 22자 이내). 기능 이름 말고 결과로
    핵심 단어 1개만 **별표 두 개**로 감싸 (카드에서 주황색으로 강조돼)
    말하듯이 끝내. "~ 지원", "~ 제공"처럼 명사로 끊지 마
    (예: "쓸 만한 **도구**가\\n한곳에 모였다", "유명 **AI 모델**을\\n한곳에서 써보기", "올린 자료가\\n**퀴즈**로 바뀐다")
  - note: 솔직한 한 줄 (30자 이내). 무료 범위·제한·필요한 것 (예: "무료 플랜은 하루 사용량 제한이 있어요", "로그인·가입 없이 바로 써요")
- takeaway: 마지막 장 한줄 정리 (30자 이내, 예: "저장해두고 필요할 때 하나씩 꺼내 쓰세요")
- share_target: 이걸 보내주고 싶은 사람 (12자 이내, 예: "발표 준비하는 동료")
- save_when: 저장해 두고 꺼내 볼 상황 (12자 이내, 예: "발표 준비할 때")
- caption: 인스타 본문. 아래 형식 그대로 (설득 순서 ①~⑥):
  첫 줄: ① 일 상황의 아픈 곳 + 약속 + 이모지 하나 (40자 이내)
  (빈 줄)
  ② "~해서가 아니라 ~가 없어서인데, 이 5개만 있으면 ~" 한두 문장 👇
  (빈 줄)
  1️⃣ 이름 (주소) — 무엇을 해주는지 한 줄 (사이트 글에 있는 것만, 제한이 있으면 적기)
  (5개 모두 이 형식, 한 줄씩)
  (빈 줄)
  💛 다섯 개 모두 공식 사이트에서 확인한 정보예요
  🔗 사이트 링크는 프로필 링크에 모아뒀어요
  (빈 줄)
{CTA_LINES}
- hashtags: 한국어 위주 8~10개, '#' 포함 (#AI사이트 #AI추천 #무료AI 포함, 단 '무료'는 정말 무료로 시작할 수 있을 때만)
- image_queries: 표지 배경 사진 검색어 3개 (영어 1~3단어). 스크롤을 멈추게 하는 강한 장면
  (예: "hacker hood dark", "secret door light", "laptop night neon"). 사람 얼굴이 크게 나오는 건 피하기
- image_prompt: 마땅한 사진이 없을 때 AI로 그릴 그림 설명 (영어 한 문장, 글자·로고·실존 인물 없이)

사이트 목록:
{listing}"""
    return _generate(prompt, ToolsCard, think=True)


class ScenePick(BaseModel):
    picks: list[int]    # 사이트마다 고른 구간 번호, 순서대로
    reasons: list[str]  # 짧은 이유


def pick_scenes(slides: list[dict], tiles: list[list[Path]]) -> list[int]:
    """사이트마다 위→아래로 찍은 구간 화면을 AI가 직접 보고, 기능이 가장 직관적으로 보이는 구간을 고른다.
    (맨 위는 분위기 그림·영어 문장뿐이고 실제 앱 화면은 아래쪽에 있는 사이트가 많아서)"""
    contents: list = ["""인스타 릴스 'AI 사이트 모음'에서 사이트마다 2초씩 화면을 보여줄 거야.
보는 사람은 영어를 잘 못 읽는 평범한 한국 20~30대이고, 화면을 1~2초만 봐.
사이트마다 위에서 아래로 찍은 구간 화면들이 있어. 각 사이트에서 **이 사이트가 뭘 해주는지 한눈에 보이는 구간** 하나를 골라줘.

좋은 구간: 실제 앱·사이트 실행 화면이 크게 보이는 곳, 결과물 예시(전후 비교, 만들어진 영상·그림·문서),
  채팅·메시지가 오가는 장면, 데모 영상, 카드 문구가 말하는 기능이 그대로 보이는 곳
나쁜 구간: 분위기 그림·추상 이미지, 큰 영어 문장만 있는 곳, 요금표, 회사 로고 모음, 후기, 질문 모음, 맨 아래 메뉴
어느 구간도 좋지 않으면 그나마 가장 나은 것을 골라."""]
    for i, (s, ts) in enumerate(zip(slides, tiles)):
        contents.append(f"\n=== 사이트 [{i}] {s['domain']} — 카드 문구: {s['heading'].replace(chr(10), ' ')}")
        for j, t in enumerate(ts):
            contents += [f"[{i}-{j}]", types.Part.from_bytes(data=t.read_bytes(), mime_type="image/jpeg")]
    result = _generate(contents, ScenePick)
    picks = []
    for i, ts in enumerate(tiles):
        j = result.picks[i] if i < len(result.picks) and 0 <= result.picks[i] < len(ts) else 0
        why = result.reasons[i] if i < len(result.reasons) else ""
        print(f"   👀 {slides[i]['domain']}: 구간 {j + 1}/{len(ts)} ({why})")
        picks.append(j)
    return picks


class TitleIdea(BaseModel):
    text: str       # 제목 (checker.MAX_TITLE자 이내)
    device: str     # 쓴 장치 번호와 이름 (예: "1 탐내는 결과")
    hook_word: str  # 제목 속 확실한 타깃이나 구체적인 키워드 (예: "대학생", "시험 공부", "보고서")


class TitleIdeas(BaseModel):
    ideas: list[TitleIdea]


class TitleRank(BaseModel):
    order: list[int]   # 멈추고 싶은 순서대로 후보 번호
    broken: list[int]  # 내용이 약속을 다 못 지키는 제목 번호 (보다가 나가게 만듦)


TITLE_CANDIDATES = 8  # 한 번에 뽑는 제목 후보 수
# AI가 결과물을 만들어 주는 주제 → 'AI 티 안 나게' 각도 후보가 꼭 있어야
MAKES_THINGS = re.compile(r"발표|PPT|슬라이드|디자인|그림|이미지|영상|썸네일|자소서|글쓰기|블로그|상세페이지|포스터|로고")
# 제목의 '확실한 타깃·구체적 키워드'로 인정하지 않는 막연한 말 (이것만 있으면 누구의 무슨 일인지 안 떠오름)
VAGUE_WORDS = {"자료", "정리", "업무", "작업", "일", "콘텐츠", "효율", "생산성", "방법", "기능", "도구", "AI", "인공지능",
               "결과물", "시간", "채팅", "노트"}
TITLE_KEEP = 5        # 텔레그램 [✏️ 다른 제목]으로 넘겨 볼 후보 수


def _brief(card: dict) -> str:
    """제목을 지을 때 AI에게 보여줄 원고 요약."""
    slides = "\n".join(f"- {checker.plain(s['heading'])}: {checker.plain(s['body']).replace(chr(10), ' ')}"
                       + (f" (⭕ {s['good'].replace(chr(10), ' ')})" if s.get("good") else "")
                       for s in card["slides"])
    return (f"종류: {({'tip': '꿀팁', 'tools': 'AI 사이트 모음', 'news': '뉴스'}).get(card.get('kind'), '뉴스')}\n"
            f"부제: {card.get('subtitle', '')}\n누가 저장할까: {card.get('save_when', '')} / "
            f"누구에게 보낼까: {card.get('share_target', '')}\n캡션 첫 줄: {card.get('caption', '').split(chr(10))[0]}\n"
            f"내용:\n{slides}")


def make_titles(card: dict) -> list[str]:
    """표지 제목만 따로 공들여 짓는다: 장치가 다른 후보 8개 → 독자 입장의 AI가 순위 → 장치가 겹치지 않게 5개.
    (원고와 같이 지으면 내용을 설명하는 밋밋한 제목이 나오기 쉬워서 따로 뽑는다)"""
    ideas = _generate(f"""{PERSONA}

아래 카드뉴스의 **표지 제목 후보 {TITLE_CANDIDATES}개**를 지어줘. 각 후보는 {checker.MAX_TITLE}자 이내(짧을수록 좋아), 서로 다른 장치를 써.
{TITLE_WORDING}
device에는 쓴 장치 번호와 이름을 적어 (예: "4 내 문제 진단").
hook_word에는 제목에 들어간 **확실한 타깃이나 구체적인 키워드**를 그대로 적어 (예: "대학생", "시험 공부", "보고서").
원고에 없는 효과·숫자는 지어내지 마. 숫자를 쓰면 원고에 있는 개수와 맞춰.
**제목이 약속하는 건 내용의 모든 방법(사이트)이 지켜야 해.** 첫 번째 방법 하나에만 맞는 제목은 금지
(보던 사람이 약속과 다른 장에서 바로 나가).

{_brief(card)}""", TitleIdeas, think=True).ideas
    seen, ok = set(), []
    for i in ideas:  # 너무 길거나 겹치는 건 코드로 뺀다
        t = checker.plain(i.text).strip()
        t = checker.EMOJI.sub("", t).replace("️", "").strip()  # 제목엔 이모지 X (사용자가 직접 뺌)
        if t.endswith("방법"):  # "~ 디자인 방법"처럼 딱딱한 끝맺음은 버린다 ("~하는 법"으로)
            continue
        hook = (i.hook_word or "").strip()
        if not hook or hook in VAGUE_WORDS or hook not in t:  # 누구의 무슨 일인지 안 보이는 제목은 버린다
            continue
        if 4 <= len(t) <= checker.MAX_TITLE and t not in seen:
            seen.add(t)
            ok.append(TitleIdea(text=t, device=i.device, hook_word=hook))
    # AI가 결과물을 만들어 주는 주제인데 'AI 티' 각도 후보가 하나도 없으면, 그 각도 후보를 더 받아 와서 같이 겨루게 한다
    # (뽑힐지는 독자 입장 순위가 정함. 억지로 1등 시키지 않음)
    if MAKES_THINGS.search(_brief(card)) and not any("티" in i.text for i in ok):
        more = _generate(f"""{PERSONA}

아래 카드뉴스의 표지 제목을 **'AI 티 안 나게' / '내 ~가 AI 티 나는 이유'** 각도로만 3개 지어줘.
{checker.MAX_TITLE}자 이내, 이모지 없이. 예: "AI 티 안 나게 발표 자료 잘 만드는 법", "내 PPT만 AI 티 나는 이유".
hook_word에는 제목 속 구체적인 키워드(예: "발표 자료", "PPT")를 그대로.

{_brief(card)}""", TitleIdeas).ideas
        for i in more:
            t = checker.EMOJI.sub("", checker.plain(i.text)).replace("️", "").strip()
            if "티" in t and 4 <= len(t) <= checker.MAX_TITLE and t not in seen:
                seen.add(t)
                ok.append(TitleIdea(text=t, device="9 AI 티", hook_word=i.hook_word or ""))
    if not ok:
        return []
    listing = "\n".join(f"[{k}] {i.text}" for k, i in enumerate(ok))
    rank = _generate(f"""너는 인스타 피드를 휙휙 넘기는 한국 20~40대야. AI를 더 잘 쓰고 싶어 하는 직장인·크리에이터·
프리랜서·대학생 중 이 카드를 볼 법한 사람의 마음으로 골라.
아래 제목 중에서 **0.5초 만에 손가락이 멈추고 눌러 보고 싶은 순서대로** 번호를 줄 세워줘.
기준: 내 얘기 같은가, 결과가 탐나는가, 궁금해서 못 참겠는가, 안 보면 나만 손해 같은가.
설명 같거나 뻔하거나 딱딱한 제목은 뒤로.
결과를 가장 짧고 바로 말하는 제목, 친구가 말하듯 자연스러운 제목을 앞으로 (예: "AI로 칼퇴하는 법").
이건 'AI 잘 쓰는 법' 계정이야. 흔한 생활·업무 꿀팁처럼 보이는 제목보다 AI를 더 잘 쓰는 느낌이 드는 제목이 보통 더 끌려.

그리고 아래 내용을 보고, broken에 번호를 적어줘:
- 제목을 보고 들어온 사람이 내용의 어느 장에서 "이거 아닌데?" 하고 나갈 제목 (제목의 약속을 모든 방법이 지켜야 해)
- 제목만 봐서는 누구의 무슨 일인지 안 떠오르는 막연한 제목

제목 후보:
{listing}

내용:
{_brief(card)}""", TitleRank)
    broken = {k for k in rank.broken if 0 <= k < len(ok)}
    if len(broken) < len(ok):  # 약속을 못 지키는 제목은 버린다 (전부 걸리면 그대로 두고 순위만)
        ok = [i if k not in broken else None for k, i in enumerate(ok)]
    ranked = [ok[k] for k in dict.fromkeys(rank.order) if 0 <= k < len(ok) and ok[k]]
    ok = [i for i in ok if i]
    ranked += [i for i in ok if i not in ranked]
    top, used = [], set()
    for i in ranked:  # 위에서부터, 장치가 겹치지 않게 먼저 고르고
        if i.device.split()[0] not in used:
            top.append(i)
            used.add(i.device.split()[0])
    top += [i for i in ranked if i not in top]  # 모자라면 나머지 순위대로
    return [i.text for i in top[:TITLE_KEEP]]


def apply_titles(card: dict) -> dict:
    """make_titles 결과를 원고에 넣는다. 실패하면 원래 제목 그대로."""
    try:
        titles = make_titles(card)
    except Exception as e:  # noqa: BLE001 - 제목 다듬기가 안 돼도 원고는 살린다
        print(f"   ⚠️ 제목 다시 짓기 실패: {e}")
        return card
    if titles:
        print(f"   🏷️ 제목: {' / '.join(titles)}")
        return {**card, "title_options": titles, "hook_title": titles[0]}
    return card


def _generate_card(prompt: str, think: bool = True) -> CardNews:
    return _generate(prompt, CardNews, think=think)
