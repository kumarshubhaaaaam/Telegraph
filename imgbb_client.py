"""
Async ImgBB upload client with automatic retries.
"""
import asyncio
import base64
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"


@dataclass
class UploadResult:
    ok: bool
    url: str | None = None
    error: str | None = None


async def upload_image_bytes(
    session: aiohttp.ClientSession,
    api_key: str,
    image_bytes: bytes,
    max_retries: int = 3,
    timeout_seconds: int = 30,
) -> UploadResult:
    """
    Upload raw image bytes to ImgBB, retrying on failure up to `max_retries` times.
    Returns an UploadResult with the direct image URL on success.
    """
    encoded = base64.b64encode(image_bytes).decode("ascii")
    # NOTE: the value here must be a str, not bytes. Passing raw bytes in an
    # aiohttp dict payload makes aiohttp send it as a binary file part, which
    # ImgBB then tries to decode as an image file directly (not as base64),
    # failing with "Unsupported or unrecognized file format" every time.
    data = {"key": api_key, "image": encoded}

    last_error = "unknown error"
    for attempt in range(1, max_retries + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.post(IMGBB_UPLOAD_URL, data=data, timeout=timeout) as resp:
                payload = await resp.json(content_type=None)
                if resp.status == 200 and payload.get("success"):
                    url = payload["data"]["url"]
                    return UploadResult(ok=True, url=url)
                last_error = payload.get("error", {}).get("message", f"HTTP {resp.status}")
                logger.warning("ImgBB upload attempt %d/%d failed: %s", attempt, max_retries, last_error)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = str(exc)
            logger.warning("ImgBB upload attempt %d/%d raised: %s", attempt, max_retries, last_error)

        if attempt < max_retries:
            # Small exponential backoff between retries.
            await asyncio.sleep(min(2 ** attempt, 8))

    return UploadResult(ok=False, error=last_error)
