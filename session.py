"""
Per-user in-memory session state for the guided conversation.
"""
from dataclasses import dataclass, field


@dataclass
class UserSession:
    title: str | None = None
    description: str | None = None
    # Ordered list of Telegram file_ids collected during the image step.
    file_ids: list[str] = field(default_factory=list)
    # Guards against uploading the same Telegram file_id twice.
    seen_file_ids: set = field(default_factory=set)
    # Ordered list of ImgBB URLs (parallel to file_ids, filled after DONE).
    image_urls: list[str] = field(default_factory=list)
    # Ordered list of links collected during the link-collection step.
    links: list[str] = field(default_factory=list)

    def add_file_id(self, file_id: str) -> bool:
        """Add a file_id if not already seen. Returns True if it was added."""
        if file_id in self.seen_file_ids:
            return False
        self.seen_file_ids.add(file_id)
        self.file_ids.append(file_id)
        return True

    def reset(self) -> None:
        self.title = None
        self.description = None
        self.file_ids.clear()
        self.seen_file_ids.clear()
        self.image_urls.clear()
        self.links.clear()


# Module-level store keyed by Telegram user id.
# Simple in-memory dict is sufficient for a single-process bot; swap for
# Redis or a DB-backed store if you need multi-process/horizontal scaling.
_SESSIONS: dict[int, UserSession] = {}


def get_session(user_id: int) -> UserSession:
    if user_id not in _SESSIONS:
        _SESSIONS[user_id] = UserSession()
    return _SESSIONS[user_id]


def clear_session(user_id: int) -> None:
    _SESSIONS.pop(user_id, None)
