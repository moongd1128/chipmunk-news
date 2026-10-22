"""4단계: 카드 6장 → 릴스 영상 (1080x1920, 9:16 mp4)

사용법:
  python reels.py 2026-10-18       # 그날 카드 전부
  python reels.py 2026-10-18 3     # 3번 카드만

- 카드(4:5)는 가운데에 놓고, 위아래는 표지면 흐린 표지로, 본문이면 카드 배경색으로 채운다
- 장 넘어갈 때 부드럽게 전환
- assets/bgm 폴더에 mp3를 넣어두면 그중 하나를 골라 배경음악으로 깐다 (없으면 음악 없이)
"""
import random
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
BGM_DIR = Path("assets/bgm")
COVER_SEC = 2.2  # 표지는 짧게 (첫 3초 안에 본문이 시작되도록)
SLIDE_SEC = 3.8  # 본문 한 장 (빨리 보고 싶은 사람은 인스타 2배속을 쓰니 넉넉하게)
END_SEC = 3.4    # 마지막 장 (정리·공유 문구를 읽을 시간)
FADE_SEC = 0.4   # 장 사이 전환 시간
W, H = 1080, 1920
CARD_BG = "0xFFF7EC"  # 카드 배경색 (templates/card.html의 --bg)

# 영상마다 하나씩 무작위로 골라서, 매일 봐도 같은 영상처럼 느껴지지 않게
TRANSITIONS = ["fade", "smoothleft", "smoothup", "slideleft", "wipeleft", "fadeblack"]


def make_reel(card_dir: Path, out: Path | None = None, bgm: Path | None = None) -> Path:
    slides = sorted(card_dir.glob("0*.jpg"))
    if not slides:
        raise FileNotFoundError(f"카드 이미지가 없어요: {card_dir}")
    out = out or card_dir / "reels.mp4"
    n = len(slides)
    durations = [COVER_SEC] + [SLIDE_SEC] * (n - 2) + [END_SEC]
    total = sum(durations) - (n - 1) * FADE_SEC
    transition = random.choice(TRANSITIONS)
    print(f"   🎞️ 전환: {transition}")

    args = [FFMPEG, "-y", "-loglevel", "error"]
    for s, d in zip(slides, durations):
        args += ["-loop", "1", "-t", f"{d}", "-framerate", "30", "-i", str(s)]

    # 표지: 흐리게 키운 표지를 배경으로 깔고, 카드(1080x1350)는 가운데에 가만히 (확대/축소 효과는 사용자 요청으로 뺌)
    # 본문·마지막 장: 카드 배경색과 같은 크림색으로 위아래를 채운다 (흐리게 하면 얼룩처럼 보여서)
    parts = [
        "[0:v]split[a0][b0];"
        f"[a0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        "boxblur=40:2,eq=brightness=-0.12[bg0];"
        f"[b0]scale={W}:-2[fg0];"
        "[bg0][fg0]overlay=(W-w)/2:(H-h)/2,format=yuv420p,setsar=1[v0]"
    ]
    for i in range(1, n):
        parts.append(
            f"[{i}:v]scale={W}:-2,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={CARD_BG},"
            f"format=yuv420p,setsar=1[v{i}]"
        )
    # 장 사이 이어 붙이기
    last, elapsed = "v0", 0.0
    for i in range(1, n):
        elapsed += durations[i - 1] - FADE_SEC
        parts.append(f"[{last}][v{i}]xfade=transition={transition}:duration={FADE_SEC}:offset={elapsed:.2f}[x{i}]")
        last = f"x{i}"
    # 인스타 권장 색 형식(yuv420p, 일반 밝기 범위)으로 맞추기
    parts.append(f"[{last}]scale=out_range=tv,format=yuv420p[vout]")
    last = "vout"
    filters = ";".join(parts)

    bgms = sorted(BGM_DIR.glob("*.mp3")) if BGM_DIR.exists() else []
    if bgms:
        bgm = bgm or random.choice(bgms)
        args += ["-stream_loop", "-1", "-i", str(bgm)]
        filters += (f";[{n}:a]atrim=0:{total:.2f},afade=t=in:d=0.5,"
                    # 곡마다 다른 소리 크기를 인스타 권장 수준(-14 LUFS 근처)으로 맞춘다
                    f"afade=t=out:st={total - 1.2:.2f}:d=1.2,loudnorm=I=-15:TP=-1.5:LRA=11,"
                    "aresample=44100[aout]")
        maps = ["-map", f"[{last}]", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
        print(f"   🎵 배경음악: {bgm.name}")
    else:
        maps = ["-map", f"[{last}]"]
        print("   🔇 assets/bgm에 mp3가 없어서 음악 없이 만들어요")

    args += ["-filter_complex", filters, *maps,
             "-t", f"{total:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    print(f"   🎬 {out} ({total:.1f}초)")
    return out


def make_story_image(card_dir: Path) -> Path:
    """스토리용 세로 사진(1080x1920): 릴스 첫 장면처럼 흐린 표지를 배경에 깔고 카드를 가운데에."""
    cover = card_dir / "01.jpg"
    out = card_dir / "story.jpg"
    filters = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
               f"boxblur=40:2,eq=brightness=-0.12[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(cover), "-filter_complex", filters,
                    "-frames:v", "1", "-q:v", "2", str(out)], check=True)
    return out


def make_all(day: str, only: int | None = None) -> list[Path]:
    day_dir = Path("output") / day
    # 같은 날 영상끼리 곡이 겹치지 않게 섞어서 차례로 쓴다
    playlist = sorted(BGM_DIR.glob("*.mp3")) if BGM_DIR.exists() else []
    random.shuffle(playlist)
    made = []
    for k, card_dir in enumerate(sorted(day_dir.glob("card_*"))):
        n = int(card_dir.name.split("_")[1])
        if only and n != only:
            continue
        print(f"🎬 [{n}] 릴스 만드는 중...")
        made.append(make_reel(card_dir, bgm=playlist[k % len(playlist)] if playlist else None))
    return made


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        raise SystemExit("사용법: python reels.py 2026-10-18 [카드번호]")
    make_all(args[0], int(args[1]) if len(args) > 1 else None)
