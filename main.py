
import os
import json
import subprocess
import datetime
import asyncio
from pathlib import Path

import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

# Pillow 10+ removed Image.ANTIALIAS, but MoviePy 1.0.3 still references it.
# Map it to its modern equivalent so resize() works with any Pillow version.
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

# ---------------- CONFIG ----------------
UNSPLASH_KEY   = os.environ["UNSPLASH_KEY"]
YT_CLIENT_ID     = os.environ["YT_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YT_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YT_REFRESH_TOKEN"]
VOICE = "en-US-GuyNeural"          # free neural voice via edge-tts
WORK = Path("work"); WORK.mkdir(exist_ok=True)

# pick one video per day, rotating through the list, never repeating
START_DATE = datetime.date(2026, 11, 1)

# ---------------- STEP 1: SCRIPT ----------------
def load_video():
    videos = json.load(open("scripts.json"))["videos"]
    idx = (datetime.date.today() - START_DATE).days % len(videos)
    return videos[idx]

# ---------------- STEP 2: IMAGES (Unsplash) ----------------
def fetch_image(keyword, path):
    r = requests.get(
        "https://api.unsplash.com/photos/random",
        params={"query": keyword, "orientation": "landscape"},
        headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
        timeout=30,
    )
    r.raise_for_status()
    url = r.json()["urls"]["raw"] + "&w=1920&h=1080&fit=crop"
    img = requests.get(url, timeout=60).content
    Path(path).write_bytes(img)
    return path

# ---------------- STEP 3: VOICEOVER ----------------
# edge-tts (best quality) blocks GitHub Actions IPs with 403 intermittently,
# so we retry it, then fall back to gTTS so a video is ALWAYS produced.
async def _edge_tts(text, path):
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, VOICE, rate="+5%").save(path)
            return os.path.getsize(path) > 1000
        except Exception as e:
            print(f"edge-tts attempt {attempt+1} failed: {e}")
            await asyncio.sleep(6 * (attempt + 1))
    return False

def tts(text, path):
    if asyncio.run(_edge_tts(text, path)):
        print("voice: edge-tts (neural)")
        return
    print("voice: falling back to gTTS")
    import gtts
    gtts.gTTS(text, lang="en", tld="com").save(path)

# ---------------- STEP 4: BUILD ----------------
def build_srt(segments, durations):
    lines, t = [], 0.0
    for seg, dur in zip(segments, durations):
        end = t + dur
        lines.append(f"{len(lines)+1}\n{fmt(t)} --> {fmt(end)}\n{seg['caption']}\n")
        t = end
    Path("work/subs.srt").write_text("\n".join(lines))
    return t

def fmt(s):
    h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60
    return f"{h:02d}:{m:02d}:{int(sec):02d},{int((sec%1)*1000):03d}"

def make_video(video):
    segments = ([{"text": video["intro"], "caption": "", "keyword": video["keyword"]}]
                + video["entries"]
                + [{"text": video["outro"], "caption": "", "keyword": video["keyword"]}])

    durations, clips = [], []
    for i, seg in enumerate(segments):
        img = fetch_image(seg["keyword"], f"work/img{i}.jpg")
        mp3 = f"work/seg{i}.mp3"
        tts(seg["text"], mp3)
        dur = AudioFileClip(mp3).duration + 0.4
        durations.append(dur)
        clips.append(
            ImageClip(img)
            .set_duration(dur)
            .resize(lambda t, d=dur: 1 + 0.12 * t / d)   # Ken Burns zoom
            .set_audio(AudioFileClip(mp3))
            .crossfadein(0.4)
        )

    total = build_srt(segments, durations)
    print(f"Video length: {total:.0f}s")
    concatenate_videoclips(clips, padding=-0.4).write_videofile(
        "work/temp.mp4", fps=24, codec="libx264", audio_codec="aac", threads=4)

    subprocess.run(["ffmpeg", "-y", "-i", "work/temp.mp4",
                    "-vf", "subtitles=work/subs.srt",
                    "-c:a", "copy", "work/final.mp4"], check=True)
    return "work/final.mp4"

# ---------------- STEP 5: THUMBNAIL ----------------
def make_thumbnail(video, out="work/thumb.jpg"):
    fetch_image(video["keyword"], "work/thumb_src.jpg")
    img = Image.open("work/thumb_src.jpg").resize((1280, 720))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 78)
    words, lines, cur = video["thumb_text"].split(), [], ""
    for w in words:
        if draw.textlength((cur + " " + w).strip(), font=font) < 1150:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    lines.append(cur)
    y = 720 - 90 * len(lines) - 40
    for line in lines:
        x = (1280 - draw.textlength(line, font=font)) / 2
        draw.text((x+4, y+4), line, font=font, fill=(0,0,0))
        draw.text((x, y), line, font=font, fill=(255,220,40))
        y += 90
    img.convert("RGB").save(out, quality=90)
    return out

# ---------------- STEP 6: UPLOAD ----------------
def upload(video_path, thumb_path, video):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        None, refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": video["title"][:100],
            "description": video["description"],
            "tags": video["tags"],
            "categoryId": "1",   # Film & Animation
        },
        "status": {"privacyStatus": "public",
                   "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=8*1024*1024, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    print("Uploaded:", vid)

    yt.thumbnails().set(videoId=vid,
        media_body=MediaFileUpload(thumb_path)).execute()
    print("Thumbnail set.")

if __name__ == "__main__":
    video = load_video()
    print("Today's video:", video["title"])
    mp4 = make_video(video)
    thumb = make_thumbnail(video)
    upload(mp4, thumb, video)
