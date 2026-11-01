import requests
from pathlib import Path
from PIL import Image, ImageDraw

from .config import get_config
from .utils import get_logger, retry_with_backoff


logger = get_logger(__name__)


def fetch_image(keyword: str, output_path: Path) -> Path:
    """Download from Unsplash or generate gradient fallback."""
    cfg = get_config().unsplash
    output_path.parent.mkdir(exist_ok=True)

    url = "https://api.unsplash.com/photos/random"
    params = {
        "query": keyword,
        "orientation": cfg.orientation,
    }
    headers = {"Authorization": f"Client-ID {_get_access_key()}"}

    for attempt in range(cfg.max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=cfg.timeout_seconds)
            r.raise_for_status()
            photo_url = r.json()["urls"]["raw"]
            photo_url += f"&w={cfg.width}&h={cfg.height}&fit=crop&q={cfg.quality}"

            img_data = requests.get(photo_url, timeout=60).content
            output_path.write_bytes(img_data)
            logger.info(f"Image downloaded: {keyword}")
            return output_path
        except Exception as e:
            logger.warning(f"Unsplash attempt {attempt + 1} failed for '{keyword}': {e}")
            if attempt < cfg.max_retries - 1:
                import time
                time.sleep(cfg.retry_backoff_base * (attempt + 1))

    # Fallback: gradient
    logger.info(f"Using gradient fallback for: {keyword}")
    _generate_gradient(output_path, cfg.width, cfg.height)
    return output_path


def _get_access_key() -> str:
    """Get Unsplash key from env or config."""
    import os
    from .config import get_config
    return os.environ.get("UNSPLASH_KEY") or get_config().unsplash.get("access_key", "")


def _generate_gradient(path: Path, width: int, height: int) -> None:
    im = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(im)
    for y in range(height):
        r = 20 + y // 30
        g = 30 + y // 25
        b = 60 + y // 18
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    im.save(path)
