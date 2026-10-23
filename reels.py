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


# ---------- 움직이는 릴스: AI 사이트 모음 ----------
# 정지된 카드를 넘기는 대신, 사이트 화면이 실제로 스크롤되는 녹화 위에 큰 글씨를 얹는다.
# 첫 1초는 표지 문구(훅)를 크게, 그다음 사이트마다 짧게 → 10초 안팎

HOOK_SEC = 1.1      # 첫 화면: 표지 문구
SITE_SEC = 1.9      # 사이트 하나
PANEL_H = 600       # 위쪽 글씨 판 높이
VIDEO_H = 1180      # 가운데 사이트 녹화 높이
_FONT = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">'
_PANEL_CSS = """* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1080px; height:1920px; background:transparent; font-family:"Pretendard",sans-serif; color:#2B1D14;
  word-break:keep-all; }
.top { position:absolute; top:0; left:0; right:0; height:%dpx; background:#FFF7EC; padding:110px 72px 0; }
.num { font-size:44px; font-weight:800; color:#F2762E; }
.num small { font-size:30px; color:#8A6F5A; }
.dom { margin-left:14px; font-size:44px; font-weight:800; }
h1 { margin-top:26px; font-size:92px; line-height:1.18; font-weight:800; letter-spacing:-3px; }
.hl { color:#F2762E; }
.bottom { position:absolute; bottom:0; left:0; right:0; height:%dpx; background:#FFF7EC; display:flex;
  align-items:center; justify-content:space-between; padding:0 72px; font-size:34px; font-weight:700; color:#8A6F5A; }
.note { color:#2B1D14; }""" % (PANEL_H, 1920 - PANEL_H - VIDEO_H)


def _panel_html(index: int, total: int, domain: str, heading: str, note: str) -> str:
    import render

    return f"""<!doctype html><html><head><meta charset="utf-8">{_FONT}<style>{_PANEL_CSS}</style></head><body>
<div class="top"><span class="num">{index:02d}<small>/{total:02d}</small></span><span class="dom">{render.escape(domain)}</span>
<h1>{render._lines(heading)}</h1></div>
<div class="bottom"><span class="note">{render.escape(note)}</span><span>@chipmunk.news.kr</span></div></body></html>"""


def _hook_html(title: str, tag: str) -> str:
    import render

    return f"""<!doctype html><html><head><meta charset="utf-8">{_FONT}<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:1080px; height:1920px; background:transparent; font-family:"Pretendard",sans-serif; word-break:keep-all; }}
.dim {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(20,12,6,.55), rgba(20,12,6,.82)); }}
.box {{ position:absolute; left:72px; right:72px; top:640px; }}
.tag {{ display:inline-block; background:#FFD24A; color:#2B1D14; font-size:40px; font-weight:800; padding:14px 26px; border-radius:16px; }}
h1 {{ margin-top:34px; color:#fff; font-size:118px; line-height:1.16; font-weight:900; letter-spacing:-4px;
  text-shadow:0 6px 30px rgba(0,0,0,.4); }}
</style></head><body><div class="dim"></div><div class="box"><span class="tag">{render.escape(tag)}</span>
<h1>{render.escape(title)}</h1></div></body></html>"""


def make_tools_reel(card: dict, card_dir: Path, out: Path | None = None, bgm: Path | None = None) -> Path:
    """AI 사이트 모음용 움직이는 릴스 (사이트 스크롤 녹화 + 큰 글씨)."""
    import json

    import render

    out = out or card_dir / "reels.mp4"
    work = card_dir / "motion"
    work.mkdir(exist_ok=True)
    slides = card["slides"]
    total = len(slides)

    # 1) 사이트마다 스크롤 녹화 (한 번 녹화한 건 재사용)
    clips = []
    for i, s in enumerate(slides, 1):
        meta = work / f"site_{i}.json"
        if meta.exists() and Path(json.loads(meta.read_text())["video"]).exists():
            info = json.loads(meta.read_text())
        else:
            print(f"   🎥 {s['domain']} 화면 녹화 중...")
            video, offset = render.record_site(s["url"], work / f"rec_{i}", 1080, VIDEO_H, SITE_SEC + 0.3)
            info = {"video": str(video), "offset": offset}
            meta.write_text(json.dumps(info))
        clips.append(info)

    # 2) 글씨 판 (위: 번호·주소·큰 글씨, 아래: 작은 글씨·계정) + 첫 화면 훅
    for i, s in enumerate(slides, 1):
        render.shoot_png(_panel_html(i, total, s["domain"], s["heading"], s["body"]), work / f"panel_{i}.png", 1080, 1920)
    title = checker_plain(card["hook_title"])
    render.shoot_png(_hook_html(title, "🔖 저장해두세요"), work / "hook.png", 1080, 1920)

    # 3) 장면마다 mp4로 만든 뒤 이어 붙인다
    def seg(path: Path, clip: dict, panel: Path, sec: float, start: float = 0.0, blur: bool = False) -> None:
        vid = (f"[0:v]trim=start={clip['offset'] + start:.2f}:duration={sec:.2f},setpts=PTS-STARTPTS,"
               f"scale=1080:{VIDEO_H},fps=30")
        if blur:  # 첫 화면: 사이트가 움직이는 게 비치도록 흐리게만
            vid += f",scale=1080:1920,boxblur=18:2[v];color=c=0x140C06:s=1080x1920:d={sec:.2f}[bg];[bg][v]overlay=0:0[b]"
        else:
            vid += f"[v];color=c=0xFFF7EC:s=1080x1920:d={sec:.2f}[bg];[bg][v]overlay=0:{PANEL_H}[b]"
        filt = vid + ";[1:v]format=rgba,fade=t=in:st=0:d=0.15:alpha=1[p];[b][p]overlay=0:0,format=yuv420p[o]"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", clip["video"], "-loop", "1", "-t", f"{sec:.2f}",
                        "-i", str(panel), "-filter_complex", filt, "-map", "[o]", "-t", f"{sec:.2f}", "-r", "30",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(path)],
                       check=True)

    parts = [work / "seg_0.mp4"]
    seg(parts[0], clips[0], work / "hook.png", HOOK_SEC, blur=True)
    for i, clip in enumerate(clips, 1):
        p = work / f"seg_{i}.mp4"
        seg(p, clip, work / f"panel_{i}.png", SITE_SEC)
        parts.append(p)
    listing = work / "parts.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    length = HOOK_SEC + SITE_SEC * len(clips)

    # 4) 배경음악 (기존 릴스와 같은 방식)
    bgms = sorted(BGM_DIR.glob("*.mp3")) if BGM_DIR.exists() else []
    args = [FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing)]
    if bgms:
        bgm = bgm or random.choice(bgms)
        args += ["-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
                 f"[1:a]atrim=0:{length:.2f},afade=t=in:d=0.3,afade=t=out:st={length - 0.8:.2f}:d=0.8,"
                 "loudnorm=I=-15:TP=-1.5:LRA=11,aresample=44100[a]",
                 "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        print(f"   🎵 배경음악: {bgm.name}")
    args += ["-c:v", "copy", "-t", f"{length:.2f}", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    print(f"   🎬 {out} ({length:.1f}초, 움직이는 릴스)")
    return out


def checker_plain(text: str) -> str:
    import checker

    return checker.EMOJI.sub("", checker.plain(text)).strip()


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
