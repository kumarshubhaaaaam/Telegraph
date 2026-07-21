"""
Configuration and environment variable loading.
"""
import os
import logging
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is optional; env vars can also be set directly.
    pass


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    imgbb_api_key: str
    telegraph_access_token: str | None
    telegraph_author_name: str
    max_upload_retries: int
    request_timeout_seconds: int


def load_settings() -> Settings:
    """
    Load and validate required settings from environment variables.
    Raises RuntimeError if a required variable is missing.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    imgbb_key = os.getenv("IMGBB_API_KEY")

    missing = []
    if not token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not imgbb_key:
        missing.append("IMGBB_API_KEY")

    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set them in your environment or a .env file."
        )

    return Settings(
        telegram_bot_token=token,
        imgbb_api_key=imgbb_key,
        telegraph_access_token=os.getenv("TELEGRAPH_ACCESS_TOKEN"),  # optional
        telegraph_author_name=os.getenv("TELEGRAPH_AUTHOR_NAME", "Telegraph Bot"),
        max_upload_retries=int(os.getenv("MAX_UPLOAD_RETRIES", "3")),
        request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
    )


def configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    # Quiet down noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
