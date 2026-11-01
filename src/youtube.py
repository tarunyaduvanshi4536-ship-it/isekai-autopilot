"""YouTube Data API wrapper with quota enforcement and retry logic."""
import os
import json
import time
from pathlib import Path
from typing import Optional
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from .config import get_config
from .utils import get_logger, retry_with_backoff


logger = get_logger(__name__)

QUOTA_FILE = Path("work/quota_usage.json")


class QuotaExceeded(Exception):
    """Raised when daily quota would be exceeded."""
    pass


class YouTubeUploader:
    def __init__(self):
        self.cfg = get_config().youtube
        self._service = None
        self._quota_used_today = 0
        self._load_quota()

    def _load_quota(self) -> None:
        """Load today's quota usage from disk."""
        if QUOTA_FILE.exists():
            try:
                data = json.loads(QUOTA_FILE.read_text())
                # Reset if it's a new day
                from datetime import date
                if data.get("date") == str(date.today()):
                    self._quota_used_today = data.get("used", 0)
            except Exception:
                pass

    def _save_quota(self) -> None:
        """Persist quota usage."""
        from datetime import date
        QUOTA_FILE.parent.mkdir(exist_ok=True)
        QUOTA_FILE.write_text(json.dumps({
            "date": str(date.today()),
            "used": self._quota_used_today
        }))

    def _get_service(self):
        if self._service:
            return self._service

        creds = Credentials(
            token=None,
            refresh_token=os.environ["YT_REFRESH_TOKEN"],
            client_id=os.environ["YT_CLIENT_ID"],
            client_secret=os.environ["YT_CLIENT_SECRET"],
            token_uri="https://oauth2.googleapis.com/token"
        )
        # Auto-refresh if needed
        if creds.expired:
            creds.refresh(Request())

        self._service = build("youtube", "v3", credentials=creds)
        return self._service

    def can_upload(self) -> bool:
        """Check if we have quota and daily limit for another upload."""
        if self._quota_used_today + self.cfg.upload_cost > self.cfg.quota_limit_per_day:
            logger.warning(f"Quota exhausted: {self._quota_used_today}/{self.cfg.quota_limit_per_day}")
            return False
        # Could also check upload count from YouTube API if needed
        return True

    def upload_video(
        self,
        video_path: Path,
        thumb_path: Path,
        title: str,
        description: str,
        tags: Optional[list[str]] = None
    ) -> str:
        """Upload video and set thumbnail. Returns video ID."""
        if not self.can_upload():
            raise QuotaExceeded("Daily upload quota exceeded")

        yt = self._get_service()

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags or self.cfg.tags,
                "categoryId": self.cfg.category_id,
            },
            "status": {"privacyStatus": self.cfg.privacy_status},
        }

        media = MediaFileUpload(
            str(video_path),
            chunksize=8 * 1024 * 1024,
            resumable=True,
            mimetype="video/mp4"
        )

        request = yt.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        logger.info(f"Starting upload: {title}")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response["id"]
        logger.info(f"Uploaded video: {video_id}")

        # Update quota
        self._quota_used_today += self.cfg.upload_cost
        self._save_quota()

        # Upload thumbnail
        try:
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumb_path))
            ).execute()
            logger.info("Thumbnail uploaded")
        except Exception as e:
            logger.warning(f"Thumbnail upload failed: {e} (video is live)")

        return video_id
