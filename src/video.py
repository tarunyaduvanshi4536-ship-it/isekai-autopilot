"""Video rendering pipeline using ffmpeg."""
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any

from .config import get_config
from .utils import get_logger, run_cmd, retry_with_backoff
from .tts import synthesize_speech
from .images import fetch_image


logger = get_logger(__name__)


class VideoSegment:
    def __init__(self, index: int, text: str, keyword: str, caption: str):
        self.index = index
        self.text = text
        self.keyword = keyword
        self.caption = caption
        self.duration: float = 0.0
        self.img_path: Path = None
        self.aud_path: Path = None
        self.vid_path: Path = None


class VideoBuilder:
    def __init__(self, work_dir: Path):
        self.cfg = get_config().video
        self.work_dir = work_dir
        self.work_dir.mkdir(exist_ok=True)
        self.segments: List[VideoSegment] = []

    def add_segment(self, text: str, keyword: str, caption: str) -> VideoSegment:
        seg = VideoSegment(len(self.segments), text, keyword, caption)
        self.segments.append(seg)
        return seg

    def build_all(self) -> Path:
        """Render all segments, concat, burn captions, return final video path."""
        logger.info(f"Building video with {len(self.segments)} segments")

        # 1. Generate assets for each segment (images, audio, video)
        for seg in self.segments:
            self._render_segment(seg)

        # 2. Concatenate segments
        concat_path = self._concat_segments()

        # 3. Burn captions
        final_path = self._burn_captions(concat_path)

        logger.info(f"Final video: {final_path}")
        return final_path

    def _render_segment(self, seg: VideoSegment) -> None:
        cfg = self.cfg

        # Image
        seg.img_path = self.work_dir / f"img_{seg.index}.jpg"
        fetch_image(seg.keyword, seg.img_path)

        # Audio
        seg.aud_path = self.work_dir / f"seg_{seg.index}.mp3"
        synthesize_speech(seg.text, seg.aud_path)

        # Duration
        seg.duration = self._get_audio_duration(seg.aud_path)

        # Video segment with Ken Burns
        seg.vid_path = self.work_dir / f"seg_{seg.index}.mp4"
        self._render_ken_burns(seg)

    def _get_audio_duration(self, path: Path) -> float:
        out = run_cmd([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)
        ], capture=True)
        return float(out.stdout.strip())

    def _render_ken_burns(self, seg: VideoSegment) -> None:
        cfg = self.cfg
        frames = max(int(round(seg.duration * cfg.fps)), cfg.fps)
        zoom_in = seg.index % 2 == 0

        if zoom_in:
            z_expr = f"z='min(zoom+{cfg.zoom_speed},{cfg.zoom_max})'"
        else:
            z_expr = f"z='if(eq(on,0),{cfg.zoom_max},max(zoom-{cfg.zoom_speed},1.0))'"

        fade_out_start = max(seg.duration - cfg.segment_crossfade, 0)
        vf = (
            f"scale={self.cfg.width}:{self.cfg.height},"
            f"zoompan={z_expr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={cfg.width}x{cfg.height}:fps={cfg.fps},"
            f"fade=t=in:st=0:d={cfg.segment_crossfade},"
            f"fade=t=out:st={fade_out_start:.2f}:d={cfg.segment_crossfade}"
        )

        run_cmd([
            "ffmpeg", "-y", "-v", "error",
            "-loop", "1", "-i", str(seg.img_path), "-i", str(seg.aud_path),
            "-vf", vf, "-t", f"{seg.duration:.2f}", "-r", str(cfg.fps),
            "-c:v", "libx264", "-crf", str(cfg.crf), "-preset", cfg.preset,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", cfg.audio_bitrate, "-shortest",
            str(seg.vid_path)
        ])

    def _concat_segments(self) -> Path:
        """Concatenate segment videos using ffmpeg concat demuxer."""
        concat_txt = self.work_dir / "concat.txt"

        # FIX: Use only filenames since concat.txt and segments are in same dir
        lines = [f"file '{seg.vid_path.name}'" for seg in self.segments]
        concat_txt.write_text("\n".join(lines) + "\n")

        temp_path = self.work_dir / "temp.mp4"
        run_cmd([
            "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", str(concat_txt), "-c", "copy", str(temp_path)
        ])
        return temp_path

    def _burn_captions(self, input_path: Path) -> Path:
        """Burn SRT subtitles into video."""
        cfg = self.cfg

        # Write SRT
        srt_path = self.work_dir / "subs.srt"
        self._write_srt(srt_path)

        # Style for subtitles
        style = (
            f"FontName={cfg.caption_font},FontSize={cfg.caption_size},"
            f"PrimaryColour=&H{cfg.caption_color[1:]},"
            f"OutlineColour=&H{cfg.caption_outline[1:]},"
            f"BorderStyle=1,Outline={cfg.caption_outline_width},"
            f"Shadow=0,MarginV={cfg.caption_margin_v}"
        )

        final_path = self.work_dir / "final.mp4"
        run_cmd([
            "ffmpeg", "-y", "-v", "error", "-i", str(input_path),
            "-vf", f"subtitles={srt_path}:force_style='{style}'",
            "-c:v", "libx264", "-crf", str(cfg.crf), "-preset", cfg.preset,
            "-c:a", "copy", str(final_path)
        ])
        return final_path

    def _write_srt(self, path: Path) -> None:
        def fmt(sec: float) -> str:
            ms = int(round(sec * 1000))
            h, ms = divmod(ms, 3600000)
            m, ms = divmod(ms, 60000)
            s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        lines, t = [], 0.0
        for i, seg in enumerate(self.segments, 1):
            start = t + 0.2
            end = t + seg.duration - 0.2
            lines.append(f"{i}\n{fmt(start)} --> {fmt(end)}\n{seg.caption}\n")
            t += seg.duration
        path.write_text("\n".join(lines))

    def make_thumbnail(self, title: str) -> Path:
        """Generate thumbnail from first segment image."""
        from PIL import Image, ImageDraw, ImageFont

        cfg = get_config().thumbnail
        src = self.work_dir / "img_0.jpg"
        out = self.work_dir / "thumb.jpg"

        im = Image.open(src).convert("RGB").resize((cfg.width, cfg.height), Image.LANCZOS)
        draw = ImageDraw.Draw(im)

        # Dark overlay on bottom half
        overlay = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(cfg.height // 2, cfg.height):
            alpha = int(cfg.overlay_opacity_max * (y - cfg.height / 2) / (cfg.height / 2))
            od.line([(0, y), (cfg.width, y)], fill=(0, 0, 0, alpha))
        im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(im)

        # Font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", cfg.title_font_size)
        except OSError:
            font = ImageFont.load_default()

        # Word wrap
        words, lines, line = title.split(), [], ""
        for w in words:
            if draw.textlength(line + " " + w, font=font) <= cfg.width - 120:
                line = (line + " " + w).strip()
            else:
                lines.append(line)
                line = w
        lines.append(line)

        # Draw bottom-up
        y = cfg.height - 60 - 86 * len(lines)
        for ln in lines:
            x = (cfg.width - draw.textlength(ln, font=font)) / 2
            draw.text((x, y), ln, font=font, fill=cfg.title_color,
                      stroke_width=cfg.title_stroke_width, stroke_fill=cfg.title_stroke_color)
            y += 86

        im.save(out, quality=92)
        return out
