"""Shared utilities: logging, subprocess, retries."""
import logging
import subprocess
import time
import functools
from pathlib import Path
from typing import Callable, Any, TypeVar
from datetime import datetime, timedelta

from .config import get_config


T = TypeVar("T")

_logger_cache: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """Get configured logger."""
    if name in _logger_cache:
        return _logger_cache[name]

    cfg = get_config().logging
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, cfg.level.upper()))

    if not logger.handlers:
        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(cfg.format))
        logger.addHandler(ch)

        # File handler with rotation
        log_dir = Path(cfg.get("log_dir", "logs"))
        log_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(log_dir / f"{datetime.now():%Y-%m-%d}.log")
        fh.setFormatter(logging.Formatter(cfg.format))
        logger.addHandler(fh)

    _logger_cache[name] = logger
    return logger


def run_cmd(cmd: list, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    """Run command with logging."""
    logger = get_logger("cmd")
    logger.debug(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(
        [str(c) for c in cmd],
        capture_output=capture,
        text=capture,
        check=check
    )
    if capture and result.stdout:
        logger.debug(result.stdout.strip())
    return result


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """Decorator for retry with exponential backoff."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger = get_logger(func.__module__)
                        logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s")
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


def cleanup_old_logs(retention_days: int = 7) -> None:
    """Delete log files older than retention_days."""
    log_dir = Path("logs")
    if not log_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=retention_days)
    for log_file in log_dir.glob("*.log"):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                log_file.unlink()
        except Exception:
            pass
