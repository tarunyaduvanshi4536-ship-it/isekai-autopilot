"""Text-to-speech with edge-tts primary and gTTS fallback."""
import asyncio
from pathlib import Path

from .config import get_config
from .utils import get_logger, retry_with_backoff


logger = get_logger(__name__)


async def _edge_tts_async(text: str, path: Path, voice: str, rate: str) -> bool:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(path))
    return path.stat().st_size > 0


def synthesize_speech(text: str, output_path: Path) -> None:
    """Generate speech with retries and fallback."""
    cfg = get_config().tts
    output_path.parent.mkdir(exist_ok=True)

    # Primary: edge-tts (neural)
    async def try_edge_tts():
        for attempt in range(cfg.max_retries):
            try:
                if await _edge_tts_async(text, output_path, cfg.primary_voice, cfg.rate):
                    logger.info("TTS: edge-tts (neural) succeeded")
                    return True
            except Exception as e:
                logger.warning(f"edge-tts attempt {attempt + 1} failed: {e}")
                if attempt < cfg.max_retries - 1:
                    await asyncio.sleep(cfg.retry_backoff_base * (attempt + 1))
        return False

    if asyncio.run(try_edge_tts()):
        return

    # Fallback: gTTS
    if cfg.fallback_enabled:
        logger.info("TTS: falling back to gTTS")
        import gtts
        gtts.gTTS(text, lang="en", tld="com").save(str(output_path))
        logger.info("TTS: gTTS succeeded")
        return

    raise RuntimeError("All TTS methods failed")
