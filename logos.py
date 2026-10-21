"""회사 로고 관리: 자주 나오는 회사 로고를 assets/logos에 미리 받아두고 표지에 쓴다.

새 회사를 추가하려면 COMPANIES에 한 줄 넣고 `python logos.py`를 한 번 실행하면 된다.
로고 파일이 없는 회사는 회사 이름을 크게 쓴 글자 로고로 대신한다.
"""
import re
from pathlib import Path

import requests

LOGO_DIR = Path("assets/logos")
LOBE = "https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.95.1/icons/{}.svg"
SIMPLE = "https://cdn.jsdelivr.net/npm/simple-icons@15/icons/{}.svg"

# 이름(정해진 표기): (아이콘 주소, 배경색, 글씨가 어두워야 하는 밝은 배경인지)
COMPANIES = {
    "오픈AI":       (LOBE.format("openai"), "#111111", False),
    "챗GPT":        (LOBE.format("openai"), "#10A37F", False),
    "앤트로픽":     (LOBE.format("anthropic"), "#C96442", False),
    "클로드":       (LOBE.format("claude"), "#D97757", False),
    "구글":         (LOBE.format("google"), "#1A73E8", False),
    "제미나이":     (LOBE.format("gemini"), "#3B6CF6", False),
    "딥마인드":     (LOBE.format("deepmind"), "#1B5FD9", False),
    "메타":         (LOBE.format("meta"), "#0866FF", False),
    "딥시크":       (LOBE.format("deepseek"), "#4D6BFE", False),
    "엔비디아":     (LOBE.format("nvidia"), "#5E9400", False),
    "마이크로소프트": (LOBE.format("microsoft"), "#0067B8", False),
    "코파일럿":     (LOBE.format("copilot"), "#0F6CBD", False),
    "애플":         (LOBE.format("apple"), "#1D1D1F", False),
    "아마존":       (LOBE.format("aws"), "#232F3E", False),
    "xAI":          (LOBE.format("xai"), "#000000", False),
    "그록":         (LOBE.format("grok"), "#000000", False),
    "미스트랄":     (LOBE.format("mistral"), "#FA520F", False),
    "퍼플렉시티":   (LOBE.format("perplexity"), "#1F8A99", False),
    "허깅페이스":   (LOBE.format("huggingface"), "#FFD21E", True),
    "알리바바":     (LOBE.format("alibaba"), "#FF6A00", False),
    "큐원":         (LOBE.format("qwen"), "#615CED", False),
    "바이트댄스":   (LOBE.format("bytedance"), "#3C8CFF", False),
    "텐센트":       (LOBE.format("tencent"), "#0052D9", False),
    "바이두":       (LOBE.format("baidu"), "#2932E1", False),
    "깃허브":       (LOBE.format("github"), "#181717", False),
    "레플릿":       (LOBE.format("replit"), "#F26207", False),
    "커서":         (LOBE.format("cursor"), "#000000", False),
    "미드저니":     (LOBE.format("midjourney"), "#000000", False),
    "런웨이":       (LOBE.format("runway"), "#000000", False),
    "수노":         (LOBE.format("suno"), "#000000", False),
    "어도비":       (LOBE.format("adobe"), "#EB1000", False),
    "삼성":         (SIMPLE.format("samsung"), "#1428A0", False),
    "네이버":       (SIMPLE.format("naver"), "#03C75A", False),
    "카카오":       (SIMPLE.format("kakao"), "#FFCD00", True),
    "테슬라":       (SIMPLE.format("tesla"), "#CC0000", False),
    "인텔":         (SIMPLE.format("intel"), "#0071C5", False),
    "AMD":          (SIMPLE.format("amd"), "#ED1C24", False),
    "퀄컴":         (SIMPLE.format("qualcomm"), "#3253DC", False),
    "유튜브":       (SIMPLE.format("youtube"), "#FF0000", False),
    "인스타그램":   (SIMPLE.format("instagram"), "#E4405F", False),
    "틱톡":         (SIMPLE.format("tiktok"), "#000000", False),
    "넷플릭스":     (SIMPLE.format("netflix"), "#E50914", False),
    "X(트위터)":    (SIMPLE.format("x"), "#000000", False),
}


def _file(name: str) -> Path:
    return LOGO_DIR / f"{re.sub(r'[^0-9A-Za-z가-힣]', '_', name)}.svg"


def download_all() -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    for name, (url, _, _) in COMPANIES.items():
        path = _file(name)
        if path.exists():
            continue
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            path.write_text(resp.text, encoding="utf-8")
            print(f"  ✔ {name}")
        except requests.RequestException:
            print(f"  ✖ {name}: 못 받음 → 글자 로고로 대신해요")


def get(name: str) -> dict | None:
    """표지에 쓸 로고 정보. 모르는 회사면 None."""
    if name not in COMPANIES:
        return None
    _, color, light_bg = COMPANIES[name]
    path = _file(name)
    svg = None
    if path.exists():
        svg = path.read_text(encoding="utf-8")
        # 로고를 글씨색 하나로 칠하기 위해 크기·색 지정을 지운다
        svg = re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)
        svg = re.sub(r'fill="(?!none)[^"]*"', 'fill="currentColor"', svg)
        svg = re.sub(r"<title>.*?</title>", "", svg)
    return {"name": name, "svg": svg, "color": color, "dark_text": light_bg}


if __name__ == "__main__":
    print("🏷️ 회사 로고 받는 중...")
    download_all()
    print(f"✅ {len(list(LOGO_DIR.glob('*.svg')))}개 준비됨: {LOGO_DIR}")
