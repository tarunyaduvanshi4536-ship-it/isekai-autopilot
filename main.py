#!/usr/bin/env python3
"""
isekai-autopilot v5 - ffmpeg edition
Daily automated isekai anime commentary video:
Unsplash images -> edge-tts/gTTS voiceover -> ffmpeg zoompan slideshow
-> burned-in captions -> Pillow thumbnail -> YouTube upload.

v5 changes: MoviePy removed entirely. Video assembly uses ffmpeg's
zoompan filter (no more smeared/corrupted frames) and outputs 1080p
at CRF 18 for a sharp picture.
"""
import os
import json
import asyncio
import datetime
import subprocess
from pathlib import Path

import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont

# ---------- config ----------
UNSPLASH_KEY = os.environ["UNSPLASH_KEY"]
VOICE = "en-US-GuyNeural"
W, H = 1920, 1080          # output resolution
FPS = 30
WORK = Path("work")
WORK.mkdir(exist_ok=True)

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


# ---------- helpers ----------
def run(cmd):
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def fetch_image(keyword, path):
    """Unsplash landscape at 2560x1440 (headroom for zoom). Falls back to
    a generated gradient so the run never dies on an API hiccup."""
    try:
        r = requests.get(
            "https://api.unsplash.com/photos/random",
            params={"query": keyword, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
            timeout=30)
        url = r.json()["urls"]["raw"] + "&w=2560&h=1440&fit=crop&q=90"
        img = requests.get(url, timeout=60).content
        Path(path).write_bytes(img)
    except Exception as e:
        print(f"image: Unsplash failed ({e}), using gradient")
        im = Image.new("RGB", (2560, 1440))
        dr = ImageDraw.Draw(im)
        for y in range(1440):
            dr.line([(0, y), (2560, y)],
                    fill=(20 + y // 30, 30 + y // 25, 60 + y // 18))
        im.save(path)
    return path


async def _edge_tts(text, path):
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, VOICE, rate="+5%").save(path)
            return True
        except Exception as e:
            print(f"voice: edge-tts attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
    return False


def tts(text, path):
    if asyncio.run(_edge_tts(text, path)) and Path(path).stat().st_size > 0:
        print("voice: edge-tts (neural)")
        return
    print("voice: falling back to gTTS")
    import gtts
    gtts.gTTS(text, lang="en", tld="com").save(path)


def render_segment(img_path, aud_path, out_path, duration, zoom_in=True):
    """Ken Burns via ffmpeg zoompan, with short fades."""
    frames = max(int(round(duration * FPS)), FPS)
    if zoom_in:
        z = "z='min(zoom+0.0012,1.15)'"
    else:
        z = "z='if(eq(on,0),1.15,max(zoom-0.0012,1.0))'"
    fade_out_start = max(duration - 0.4, 0)
    vf = (f"scale=2560:1440,"
          f"zoompan={z}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d={frames}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out_start:.2f}:d=0.4")
    run(["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-i", img_path, "-i", aud_path,
         "-vf", vf, "-t", f"{duration:.2f}", "-r", str(FPS),
         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", out_path])


def srt_time(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments, path):
    lines, t = [], 0.0
    for i, seg in enumerate(segments, 1):
        start, end = t + 0.2, t + seg["duration"] - 0.2
        lines.append(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{seg['caption']}\n")
        t += seg["duration"]
    Path(path).write_text("\n".join(lines))


def make_thumbnail(img_path, title, out_path, size=(1280, 720)):
    im = Image.open(img_path).convert("RGB").resize(size, Image.LANCZOS)
    draw = ImageDraw.Draw(im)
    # darken bottom half for text contrast
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(size[1] // 2, size[1]):
        od.line([(0, y), (size[0], y)],
                fill=(0, 0, 0, int(200 * (y - size[1] / 2) / (size[1] / 2))))
    im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 68)
    except OSError:
        font = ImageFont.load_default()
    words, lines, line = title.split(), [], ""
    for w in words:
        if draw.textlength(line + " " + w, font=font) <= size[0] - 120:
            line = (line + " " + w).strip()
        else:
            lines.append(line)
            line = w
    lines.append(line)
    y = size[1] - 60 - 86 * len(lines)
    for ln in lines:
        x = (size[0] - draw.textlength(ln, font=font)) / 2
        draw.text((x, y), ln, font=font, fill=(255, 214, 0),
                  stroke_width=4, stroke_fill=(0, 0, 0))
        y += 86
    im.save(out_path, quality=92)


def upload(video_path, thumb_path, video):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token")
    yt = build("youtube", "v3", credentials=creds)
    req = yt.videos().insert(
        part="snippet,status",
        body={"snippet": {
            "title": video["title"],
            "description": video["desc"] + "\n\nBackground photos: Unsplash",
            "tags": video.get("tags", []),
            "categoryId": "1"},
            "status": {"privacyStatus": "public"}},
        media_body=MediaFileUpload(str(video_path),
                                   chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    print("Uploaded:", resp["id"])
    try:
        yt.thumbnails().set(
            videoId=resp["id"],
            media_body=MediaFileUpload(str(thumb_path))).execute()
        print("Thumbnail set.")
    except Exception as e:
        print(f"WARNING: thumbnail upload failed ({e}) - video is live anyway,")
        print("upload work/thumb.jpg manually from YouTube Studio.")


def main():
    data = json.loads(Path("scripts.json").read_text())
    start = datetime.date.fromisoformat(data["start_date"])
    idx = (datetime.date.today() - start).days % len(data["videos"])
    video = data["videos"][idx]
    print(f"Today\'s video: {video['title']}")

    # build segment list: intro -> entries -> outro
    segments = [{"text": video["intro"], "keyword": video["keyword"],
                 "caption": video["title"]}]
    for n, e in enumerate(video["entries"], 1):
        segments.append({"text": f"{e['heading']}. {e['script']}",
                         "keyword": e["keyword"], "caption": e["heading"]})
    segments.append({"text": video["outro"], "keyword": video["keyword"],
                     "caption": "Subscribe for more isekai picks!"})

    seg_files = []
    for i, seg in enumerate(segments):
        img = fetch_image(seg["keyword"], WORK / f"img_{i}.jpg")
        aud = WORK / f"seg_{i}.mp3"
        tts(seg["text"], aud)
        dur = audio_duration(aud)
        seg["duration"] = dur
        out = WORK / f"seg_{i}.mp4"
        render_segment(img, aud, out, dur, zoom_in=(i % 2 == 0))
        seg_files.append(out)

    # concat
    concat_txt = WORK / "concat.txt"
    concat_txt.write_text("".join(f"file '{f}'\n" for f in seg_files))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", concat_txt, "-c", "copy", WORK / "temp.mp4"])

    # burn captions
    write_srt(segments, WORK / "subs.srt")
    style = ("FontName=DejaVu Sans,FontSize=22,PrimaryColour=&HFFFFFF,"
             "OutlineColour=&H000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=40")
    run(["ffmpeg", "-y", "-v", "error", "-i", WORK / "temp.mp4",
         "-vf", f"subtitles={WORK / 'subs.srt'}:force_style='{style}'",
         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-c:a", "copy", WORK / "final.mp4"])

    make_thumbnail(WORK / "img_0.jpg", video["title"], WORK / "thumb.jpg")
    upload(WORK / "final.mp4", WORK / "thumb.jpg", video)
    print("Done.")


if __name__ == "__main__":
    main()
