"""Telegram transport client and message formatter.

Provides stateless HTTP API operations for sending, editing, and deleting Telegram messages,
along with robust markdown-preserving message splitting for long agent responses.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from ..base import SendResult

logger = logging.getLogger("cogniwork.connectors.telegram")

_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_MAX_RETRY_AFTER = 30.0
_CODE_BLOCK_RE = re.compile(r"^```([a-zA-Z0-9_\-+]*)\s*$", re.MULTILINE)


def split_telegram_message(
    text: str, max_length: int | None = None
) -> list[str]:
    """Split a message into chunks that fit within Telegram's character limits.

    Ensures Markdown code blocks (```...```) that cross chunk boundaries are cleanly
    closed in the current chunk and re-opened in the subsequent chunk.
    """
    if max_length is None:
        try:
            max_length = int(
                os.environ.get("TELEGRAM_MESSAGE_MAX_CHARS", "4000")
            )
        except ValueError:
            max_length = 4000

    if not text:
        return [""]

    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text
    open_fence_lang: str | None = None

    while remaining:
        # If prefixing an open fence from previous chunk, account for it
        prefix = f"```{open_fence_lang}\n" if open_fence_lang is not None else ""
        avail_len = max_length - len(prefix) - (4 if open_fence_lang is not None else 0)
        if avail_len <= 100:
            avail_len = max_length

        if len(remaining) <= avail_len:
            chunk = prefix + remaining
            chunks.append(chunk)
            break

        # Find best split point in remaining[:avail_len]
        candidate = remaining[:avail_len]
        split_idx = -1

        # Prefer paragraph breaks
        split_idx = candidate.rfind("\n\n")
        if split_idx > avail_len // 3:
            split_len = split_idx + 2
        else:
            # Fall back to single newline
            split_idx = candidate.rfind("\n")
            if split_idx > avail_len // 3:
                split_len = split_idx + 1
            else:
                # Fall back to word boundary
                split_idx = candidate.rfind(" ")
                if split_idx > avail_len // 3:
                    split_len = split_idx + 1
                else:
                    split_len = avail_len

        chunk_raw = remaining[:split_len]
        remaining = remaining[split_len:]

        # Determine if we entered/exited code fences in chunk_raw
        in_code_block = open_fence_lang is not None
        current_lang = open_fence_lang

        for match in re.finditer(r"```([a-zA-Z0-9_\-+]*)(?:\n|$)", chunk_raw):
            if in_code_block:
                in_code_block = False
                current_lang = None
            else:
                in_code_block = True
                current_lang = match.group(1) or ""

        chunk_out = prefix + chunk_raw
        if in_code_block:
            chunk_out = chunk_out.rstrip() + "\n```"
            open_fence_lang = current_lang or ""
        else:
            open_fence_lang = None

        chunks.append(chunk_out)

    return chunks


class TelegramClient:
    """Stateless HTTP client for Telegram Bot API operations."""

    def __init__(
        self,
        token: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        base_url: str | None = None,
    ) -> None:
        self.token = token
        self.timeout = timeout
        self.base_url = (
            base_url
            or os.environ.get(
                "TELEGRAM_API_BASE_URL", "https://api.telegram.org"
            )
        ).rstrip("/")

    def _url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    def _post(
        self,
        method: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Perform an HTTP POST to Telegram Bot API with 429 rate limit backoff."""
        import time
        import httpx

        url = self._url(method)
        req_timeout = timeout or self.timeout

        for attempt in range(_MAX_RETRIES + 1):
            if files and isinstance(files, dict):
                for f_entry in files.values():
                    if isinstance(f_entry, tuple) and len(f_entry) >= 2:
                        fh = f_entry[1]
                        if hasattr(fh, "seek") and callable(fh.seek):
                            try:
                                fh.seek(0)
                            except Exception:
                                pass

            resp = httpx.post(
                url,
                json=json,
                data=data,
                files=files,
                timeout=req_timeout,
            )
            try:
                res_data = resp.json()
            except Exception:
                resp.raise_for_status()
                res_data = {"ok": resp.status_code == 200}

            # Check for 429 Rate Limit
            is_429 = resp.status_code == 429 or (
                not res_data.get("ok") and res_data.get("error_code") == 429
            )
            if is_429 and attempt < _MAX_RETRIES:
                retry_after = res_data.get("parameters", {}).get("retry_after")
                if retry_after is None:
                    desc = str(res_data.get("description") or "")
                    m = re.search(r"retry after (\d+)", desc, re.IGNORECASE)
                    if m:
                        retry_after = int(m.group(1))
                delay = (
                    min(max(float(retry_after), 0.1), _MAX_RETRY_AFTER)
                    if retry_after is not None
                    else min(1.0 * (attempt + 1), _MAX_RETRY_AFTER)
                )
                logger.warning(
                    "Telegram API rate limited (429) on %s, retrying after %.1fs (attempt %d/%d)",
                    method,
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            return res_data

        return res_data

    def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        thread_id: str | int | None = None,
        reply_to_message_id: str | int | None = None,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> SendResult:
        payload: dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if thread_id and str(thread_id) != "1":
            try:
                payload["message_thread_id"] = int(thread_id)
            except ValueError:
                pass
        if reply_to_message_id:
            try:
                payload["reply_to_message_id"] = int(reply_to_message_id)
            except ValueError:
                pass
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            data = self._post("sendMessage", json=payload, timeout=self.timeout)
        except Exception as exc:
            logger.warning("Telegram sendMessage error: %s", exc)
            return SendResult(False, error=str(exc))

        if data.get("ok"):
            msg_id = str(data.get("result", {}).get("message_id", ""))
            return SendResult(True, message_id=msg_id)

        err_desc = data.get("description") or "telegram send failed"
        logger.warning("Telegram sendMessage rejected: %s", err_desc)
        return SendResult(False, error=err_desc)

    def edit_message_text(
        self,
        chat_id: str | int,
        message_id: str | int,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> SendResult:
        try:
            msg_id_int = int(message_id)
        except ValueError:
            return SendResult(False, error=f"invalid message_id: {message_id}")

        payload: dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": msg_id_int,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            data = self._post("editMessageText", json=payload, timeout=self.timeout)
        except Exception as exc:
            logger.warning("Telegram editMessageText error: %s", exc)
            return SendResult(False, error=str(exc))

        if data.get("ok"):
            return SendResult(True, message_id=str(message_id))

        err_desc = str(data.get("description") or "")
        # Telegram returns 400 with "message is not modified" if content is identical
        if "message is not modified" in err_desc.lower():
            return SendResult(True, message_id=str(message_id))

        logger.debug(
            "Telegram editMessageText failed for %s:%s: %s",
            chat_id,
            message_id,
            err_desc,
        )
        return SendResult(False, error=err_desc or "telegram edit failed")

    def delete_message(
        self, chat_id: str | int, message_id: str | int
    ) -> bool:
        try:
            msg_id_int = int(message_id)
        except ValueError:
            return False

        payload = {"chat_id": str(chat_id), "message_id": msg_id_int}
        try:
            data = self._post("deleteMessage", json=payload, timeout=self.timeout)
            return bool(data.get("ok"))
        except Exception:
            return False

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        *,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int | None = None,
    ) -> bool:
        """Acknowledge a Telegram callback_query from an inline keyboard button."""
        payload: dict[str, Any] = {"callback_query_id": str(callback_query_id)}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        if url:
            payload["url"] = url
        if cache_time is not None:
            payload["cache_time"] = int(cache_time)

        try:
            data = self._post("answerCallbackQuery", json=payload, timeout=self.timeout)
            return bool(data.get("ok"))
        except Exception as exc:
            logger.warning("Telegram answerCallbackQuery error: %s", exc)
            return False

    def send_document(
        self,
        chat_id: str | int,
        document: Any,
        filename: str,
        *,
        caption: str | None = None,
        thread_id: str | int | None = None,
        mime_type: str | None = None,
    ) -> SendResult:
        """Upload and send a document to Telegram using multipart/form-data.

        `document` can be raw bytes, a file-like stream, or a path-like string.
        """
        payload: dict[str, Any] = {"chat_id": str(chat_id)}
        if thread_id and str(thread_id) != "1":
            try:
                payload["message_thread_id"] = int(thread_id)
            except ValueError:
                pass
        if caption:
            payload["caption"] = caption[:1024]

        content_type = mime_type or "application/octet-stream"
        opened_file = None

        try:
            if isinstance(document, (bytes, bytearray)):
                files = {"document": (filename, bytes(document), content_type)}
            elif hasattr(document, "read"):
                files = {"document": (filename, document, content_type)}
            elif isinstance(document, (str, os.PathLike)) and os.path.isfile(str(document)):
                opened_file = open(str(document), "rb")
                files = {"document": (filename, opened_file, content_type)}
            elif isinstance(document, str):
                files = {"document": (filename, document.encode("utf-8"), content_type)}
            else:
                return SendResult(False, error="invalid document object")

            try:
                data = self._post(
                    "sendDocument",
                    data=payload,
                    files=files,
                    timeout=max(self.timeout, 60.0),
                )
            except Exception as exc:
                logger.warning("Telegram sendDocument error: %s", exc)
                return SendResult(False, error=str(exc))
            finally:
                if opened_file:
                    try:
                        opened_file.close()
                    except Exception:
                        pass

            if data.get("ok"):
                msg_id = str(data.get("result", {}).get("message_id", ""))
                return SendResult(True, message_id=msg_id)

            err_desc = data.get("description") or "telegram sendDocument failed"
            logger.warning("Telegram sendDocument rejected: %s", err_desc)
            return SendResult(False, error=err_desc)
        except Exception as exc:
            if opened_file:
                try:
                    opened_file.close()
                except Exception:
                    pass
            logger.warning("Telegram sendDocument unexpected error: %s", exc)
            return SendResult(False, error=str(exc))

