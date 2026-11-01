"""Configuration management with validation and local overrides."""
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field, validator


class YouTubeConfig(BaseModel):
    category_id: str = "1"
    privacy_status: str = "public"
    tags: list[str] = Field(default_factory=list)
    max_uploads_per_day: int = 1
    quota_limit_per_day: int = 10000
    upload_cost: int = 1600


class VideoConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 18
    preset: str = "fast"
    audio_bitrate: str = "192k"
    segment_crossfade: float = 0.4
    zoom_max: float = 1.15
    zoom_speed: float = 0.0012
    caption_font: str = "DejaVu Sans"
    caption_size: int = 22
    caption_color: str = "#FFFFFF"
    caption_outline: str = "#000000"
    caption_outline_width: int = 2
    caption_margin_v: int = 40


class UnsplashConfig(BaseModel):
    orientation: str = "landscape"
    width: int = 2560
    height: int = 1440
    quality: int = 90
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_backoff_base: int = 5


class TTSConfig(BaseModel):
    primary_voice: str = "en-US-GuyNeural"
    rate: str = "+5%"
    max_retries: int = 3
    retry_backoff_base: int = 5
    fallback_enabled: bool = True


class ThumbnailConfig(BaseModel):
    width: int = 1280
    height: int = 720
    title_font_size: int = 68
    title_color: str = "#FFD600"
    title_stroke_width: int = 4
    title_stroke_color: str = "#000000"
    overlay_opacity_max: int = 200


class ScheduleConfig(BaseModel):
    timezone: str = "UTC"
    hour: int = 10
    minute: int = 0


class PathsConfig(BaseModel):
    work_dir: str = "work"
    scripts_file: str = "scripts.json"
    log_dir: str = "logs"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    file_retention_days: int = 7


class AppConfig(BaseModel):
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    unsplash: UnsplashConfig = Field(default_factory=UnsplashConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    thumbnail: ThumbnailConfig = Field(default_factory=ThumbnailConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @validator("youtube")
    def validate_youtube(cls, v):
        if v.max_uploads_per_day > 6:
            raise ValueError("max_uploads_per_day cannot exceed 6 (API quota)")
        return v


_config: Optional[AppConfig] = None


def load_config(config_path: str = "config.yaml", local_path: str = "config.local.yaml") -> AppConfig:
    """Load config from YAML with optional local override."""
    global _config
    if _config:
        return _config

    data: Dict[str, Any] = {}

    # Base config
    if Path(config_path).exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    # Local override (for secrets, not committed)
    if Path(local_path).exists():
        with open(local_path) as f:
            local = yaml.safe_load(f) or {}
            _deep_merge(data, local)

    # Env var overrides for secrets
    _apply_env_overrides(data)

    _config = AppConfig(**data)
    return _config


def get_config() -> AppConfig:
    if _config is None:
        return load_config()
    return _config


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _apply_env_overrides(data: dict) -> None:
    """Apply environment variable overrides for sensitive values."""
    env_mapping = {
        "UNSPLASH_KEY": ("unsplash", "access_key"),
        "YT_CLIENT_ID": ("youtube", "client_id"),
        "YT_CLIENT_SECRET": ("youtube", "client_secret"),
        "YT_REFRESH_TOKEN": ("youtube", "refresh_token"),
    }
    for env_key, (section, key) in env_mapping.items():
        if val := os.environ.get(env_key):
            data.setdefault(section, {})[key] = val
