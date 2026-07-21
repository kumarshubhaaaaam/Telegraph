"""
Utilities for extracting valid HTTP/HTTPS URLs from free-form text,
including text pulled from forwarded messages.
"""
import re
from urllib.parse import urlparse

# Matches http:// or https:// URLs up to the next whitespace character.
_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def _is_valid(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def extract_urls(text: str) -> list[str]:
    """
    Extract every valid HTTP/HTTPS URL from `text`, in the order they appear.
    Trailing punctuation commonly attached to URLs in prose (.,)]}>'" etc.)
    is stripped. Invalid/malformed matches are dropped. Duplicates are kept
    (the caller may intentionally repeat a link).
    """
    if not text:
        return []

    found = []
    for match in _URL_PATTERN.findall(text):
        cleaned = match.rstrip(").,]}>\"'")
        if _is_valid(cleaned):
            found.append(cleaned)
    return found
