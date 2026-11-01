#!/usr/bin/env python3
"""
Isekai Autopilot — Professional Edition
Daily automated faceless YouTube channel.
"""
import json
import sys
from pathlib import Path
from datetime import date

from src.config import load_config, get_config
from src.utils import get_logger, cleanup_old_logs
from src.video import VideoBuilder
from src.youtube import YouTubeUploader, QuotaExceeded


logger = get_logger(__name__)


def main() -> int:
    try:
        # Load config (with local override support)
        load_config()

        # Cleanup old logs
        cleanup_old_logs(get_config().logging.file_retention_days)

        # Load scripts
        scripts_file = Path(get_config().paths.scripts_file)
        data = json.loads(scripts_file.read_text())

        # Select today's video (rotating by date)
        start = date.fromisoformat(data["start_date"])
        idx = (date.today() - start).days % len(data["videos"])
        video = data["videos"][idx]
        logger.info(f"Today's video: {video['title']}")

        # Build video
        work_dir = Path(get_config().paths.work_dir)
        builder = VideoBuilder(work_dir)

        # Intro
        builder.add_segment(video["intro"], video["keyword"], video["title"])

        # Entries
        for entry in video["entries"]:
            builder.add_segment(
                f"{entry['heading']}. {entry['script']}",
                entry["keyword"],
                entry["heading"]
            )

        # Outro
        builder.add_segment(video["outro"], video["keyword"], "Subscribe for more isekai picks!")

        # Render pipeline
        final_video = builder.build_all()
        thumbnail = builder.make_thumbnail(video["title"])

        # Upload with quota check
        uploader = YouTubeUploader()
        try:
            video_id = uploader.upload_video(
                final_video,
                thumbnail,
                title=video["title"],
                description=video["desc"] + "\n\nBackground photos: Unsplash",
                tags=video.get("tags", [])
            )
            logger.info(f"Success! Video ID: {video_id}")
        except QuotaExceeded:
            logger.error("Upload skipped: daily quota exceeded")
            return 2  # Special exit code for quota

        return 0

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
