"""
ConversationHandler states and callbacks implementing the guided flow:

  TITLE -> DESCRIPTION -> COLLECT_IMAGES -> COLLECT_LINKS -> (end)
"""
import logging

import aiohttp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

from config import Settings
from imgbb_client import upload_image_bytes
from telegraph_client import ensure_access_token, create_page
from session import get_session, clear_session
from url_utils import extract_urls

logger = logging.getLogger(__name__)

# Conversation states
TITLE, DESCRIPTION, COLLECT_IMAGES, COLLECT_LINKS = range(4)

DONE_CALLBACK_DATA = "done"
DONE_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Done ✅", callback_data=DONE_CALLBACK_DATA)]]
)


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        filled = 0
    else:
        filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)


# ──────────────────────────────────────────────────────────────────────
# Step 1: /start
# ──────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    clear_session(user_id)
    get_session(user_id)  # initialize fresh session

    await update.message.reply_text(
        "Welcome 👋\n\n"
        "Let's create a Telegraph Article.\n\n"
        "Please send the Article Title."
    )
    return TITLE


# ──────────────────────────────────────────────────────────────────────
# Step 2: Title -> Description
# ──────────────────────────────────────────────────────────────────────

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session(update.effective_user.id)
    session.title = update.message.text.strip()

    await update.message.reply_text(
        "Now send Description Text.\n\n"
        "This description will appear at the TOP of the Telegraph article in BOLD.\n\n"
        "Example:\n"
        "<b>Your Description Here</b>"
    )
    return DESCRIPTION


async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session(update.effective_user.id)
    session.description = update.message.text.strip()

    await update.message.reply_text(
        "Great. Now send your images.\n\n"
        "• Photos, image documents, forwards, and albums are all supported.\n"
        "• Send as many messages as you need.\n\n"
        "Press /done or the Done ✅ button when you've sent them all.",
        reply_markup=DONE_KEYBOARD,
    )
    return COLLECT_IMAGES


# ──────────────────────────────────────────────────────────────────────
# Step 3: Collecting images
# ──────────────────────────────────────────────────────────────────────

async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session(update.effective_user.id)
    message = update.message

    file_id = None
    if message.photo:
        # `photo` is a list of sizes; the last is the highest resolution.
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id

    if file_id is None:
        await message.reply_text(
            "That doesn't look like an image. Please send a photo or image file, "
            "or press /done if you're finished.",
            reply_markup=DONE_KEYBOARD,
        )
        return COLLECT_IMAGES

    added = session.add_file_id(file_id)

    if not added:
        # Duplicate file_id — silently ignore per spec, no extra message needed.
        return COLLECT_IMAGES

    media_group_id = message.media_group_id

    if media_group_id:
        # Avoid spamming one confirmation per photo in an album: only send
        # a fresh confirmation when we've moved on from the previous group.
        last_group = context.user_data.get("last_media_group_id")
        context.user_data["last_media_group_id"] = media_group_id
        if last_group == media_group_id:
            return COLLECT_IMAGES
    else:
        context.user_data["last_media_group_id"] = None

    count = len(session.file_ids)
    await message.reply_text(
        f"✅ {count} Image{'s' if count != 1 else ''} Received.\n\n"
        "Send more images or press /done.",
        reply_markup=DONE_KEYBOARD,
    )
    return COLLECT_IMAGES


async def images_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session(update.effective_user.id)

    status_message = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()

    if not session.file_ids:
        await status_message.reply_text("❌ Please send at least one image.")
        return COLLECT_IMAGES

    settings: Settings = context.bot_data["settings"]
    total = len(session.file_ids)

    progress_msg = await status_message.reply_text(
        f"Uploading Images...\n{_progress_bar(0, total)}\n0 / {total}"
    )

    image_urls: list[str] = []
    failed_count = 0

    async with aiohttp.ClientSession() as http_session:
        for index, file_id in enumerate(session.file_ids, start=1):
            try:
                tg_file = await context.bot.get_file(file_id)
                image_bytes = await tg_file.download_as_bytearray()
            except Exception as exc:  # Telegram API/network error fetching the file
                logger.warning("Failed to download file_id=%s: %s", file_id, exc)
                failed_count += 1
                continue

            result = await upload_image_bytes(
                http_session,
                api_key=settings.imgbb_api_key,
                image_bytes=bytes(image_bytes),
                max_retries=settings.max_upload_retries,
                timeout_seconds=settings.request_timeout_seconds,
            )

            if result.ok:
                image_urls.append(result.url)
            else:
                failed_count += 1
                logger.warning("Giving up on image %d after retries: %s", index, result.error)

            if index % 3 == 0 or index == total:
                try:
                    await progress_msg.edit_text(
                        f"Uploading Images...\n{_progress_bar(index, total)}\n{index} / {total}"
                    )
                except Exception:
                    pass  # Edit failures (e.g. identical content) are non-fatal.

    session.image_urls = image_urls

    if not image_urls:
        await status_message.reply_text(
            "❌ All image uploads failed. Please try /start again."
        )
        clear_session(update.effective_user.id)
        return ConversationHandler.END

    summary = f"Uploaded {len(image_urls)} / {total} images."
    if failed_count:
        summary += f" ({failed_count} skipped after retries.)"
    await status_message.reply_text(summary)

    await status_message.reply_text("Creating Telegraph Article...")

    async with aiohttp.ClientSession() as http_session:
        token = await ensure_access_token(
            http_session,
            author_name=settings.telegraph_author_name,
            existing_token=settings.telegraph_access_token,
        )
        page_result = await create_page(
            http_session,
            access_token=token,
            title=session.title,
            description=session.description,
            image_urls=session.image_urls,
            author_name=settings.telegraph_author_name,
            max_retries=settings.max_upload_retries,
            timeout_seconds=settings.request_timeout_seconds,
        )

    if not page_result.ok:
        await status_message.reply_text(
            f"❌ Failed to create Telegraph article: {page_result.error}\n"
            "Please try /start again."
        )
        clear_session(update.effective_user.id)
        return ConversationHandler.END

    context.user_data["telegraph_url"] = page_result.url

    await status_message.reply_text(
        "Please forward or send all your links.\n\n"
        "• Paste multiple links in one message.\n"
        "• Forward multiple messages.\n"
        "• Send links in several messages.\n\n"
        "Press /done or the Done ✅ button when finished.",
        reply_markup=DONE_KEYBOARD,
    )
    return COLLECT_LINKS


# ──────────────────────────────────────────────────────────────────────
# Step 7-8: Collecting links
# ──────────────────────────────────────────────────────────────────────

async def receive_link_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session(update.effective_user.id)
    message = update.message

    # Pull text from the message itself, and also from forwarded message
    # captions if present, so forwarded links are captured either way.
    text = message.text or message.caption or ""
    urls = extract_urls(text)

    if urls:
        session.links.extend(urls)

    return COLLECT_LINKS


async def links_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = get_session(update.effective_user.id)
    status_message = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()

    if not session.links:
        await status_message.reply_text("❌ No valid links detected.")
        return COLLECT_LINKS

    telegraph_url = context.user_data.get("telegraph_url", "")

    lines = [telegraph_url] + session.links
    final_text = "\n".join(lines)

    await status_message.reply_text("Generating Final Reply...")
    await status_message.reply_text(final_text, disable_web_page_preview=True)
    await status_message.reply_text("Completed ✅")

    clear_session(update.effective_user.id)
    context.user_data.clear()
    return ConversationHandler.END


# ──────────────────────────────────────────────────────────────────────
# Fallbacks
# ──────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    clear_session(update.effective_user.id)
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send /start to begin again.")
    return ConversationHandler.END



