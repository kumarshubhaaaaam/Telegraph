"""
Async Telegraph API client: account creation + page creation, with retries.
"""
import asyncio
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

TELEGRAPH_API_BASE = "https://api.telegra.ph"


@dataclass
class TelegraphPageResult:
    ok: bool
    url: str | None = None
    error: str | None = None


async def ensure_access_token(
    session: aiohttp.ClientSession,
    author_name: str,
    existing_token: str | None = None,
) -> str:
    """
    Return an existing access token if provided, otherwise create a fresh
    Telegraph account and return its access_token.
    """
    if existing_token:
        return existing_token

    async with session.post(
        f"{TELEGRAPH_API_BASE}/createAccount",
        data={"short_name": author_name, "author_name": author_name},
    ) as resp:
        payload = await resp.json(content_type=None)
        if not payload.get("ok"):
            raise RuntimeError(f"Failed to create Telegraph account: {payload}")
        return payload["result"]["access_token"]


def build_telegraph_content(description: str, image_urls: list[str]) -> list[dict]:
    """
    Build the Telegraph "Node" content array:
    - A single bold paragraph for the description at the top.
    - One <img> node per image, in the exact order given.
    """
    content: list[dict] = []

    if description:
        content.append({
            "tag": "p",
            "children": [{"tag": "b", "children": [description]}],
        })

    for url in image_urls:
        content.append({"tag": "img", "attrs": {"src": url}})

    return content


async def create_page(
    session: aiohttp.ClientSession,
    access_token: str,
    title: str,
    description: str,
    image_urls: list[str],
    author_name: str,
    max_retries: int = 3,
    timeout_seconds: int = 30,
) -> TelegraphPageResult:
    """
    Create a Telegraph page with the given title and content, retrying on failure.
    """
    content = build_telegraph_content(description, image_urls)

    last_error = "unknown error"
    for attempt in range(1, max_retries + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.post(
                f"{TELEGRAPH_API_BASE}/createPage",
                json={
                    "access_token": access_token,
                    "title": title,
                    "author_name": author_name,
                    "content": content,
                    "return_content": False,
                },
                timeout=timeout,
            ) as resp:
                payload = await resp.json(content_type=None)
                if payload.get("ok"):
                    return TelegraphPageResult(ok=True, url=payload["result"]["url"])
                last_error = payload.get("error", f"HTTP {resp.status}")
                logger.warning("Telegraph createPage attempt %d/%d failed: %s", attempt, max_retries, last_error)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = str(exc)
            logger.warning("Telegraph createPage attempt %d/%d raised: %s", attempt, max_retries, last_error)

        if attempt < max_retries:
            await asyncio.sleep(min(2 ** attempt, 8))

    return TelegraphPageResult(ok=False, error=last_error)
