"""Telegram Progress Adapter — streams normalized execution events to Telegram.

Supports live message editing with rate limiting, error fallbacks, and multi-message
splitting for final responses.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from .client import TelegramClient, split_telegram_message
from .events import AgentProgressEvent

logger = logging.getLogger("cogniwork.connectors.telegram")

_DEFAULT_UPDATE_INTERVAL = 1.5


class TelegramProgressAdapter:
    """Consumes normalized AgentProgressEvents and updates Telegram via live message editing."""

    def __init__(
        self,
        client: TelegramClient,
        chat_id: str | int,
        *,
        thread_id: str | int | None = None,
        update_interval: float | None = None,
        mode: str | None = None,
        initial_message_id: str | None = None,
    ) -> None:
        self.client = client
        self.chat_id = str(chat_id)
        self.thread_id = str(thread_id) if thread_id is not None else None

        if update_interval is None:
            try:
                update_interval = float(
                    os.environ.get(
                        "TELEGRAM_PROGRESS_UPDATE_INTERVAL",
                        str(_DEFAULT_UPDATE_INTERVAL),
                    )
                )
            except ValueError:
                update_interval = _DEFAULT_UPDATE_INTERVAL
        self.update_interval = max(0.01, update_interval)

        self.mode = (
            mode or os.environ.get("TELEGRAM_PROGRESS_MODE", "edit")
        ).lower()
        self.progress_message_id: str | None = initial_message_id
        self.last_edit_time: float = 0.0
        self.latest_text: str = ""
        self._last_sent_text: str = ""
        self._pending_flush: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def start(
        self, initial_text: str = "🟢 CogniOS session started"
    ) -> str | None:
        """Send the initial progress message and retain its message_id for live editing."""
        if self.progress_message_id is not None:
            return self.progress_message_id

        async with self._lock:
            res = await asyncio.to_thread(
                self.client.send_message,
                self.chat_id,
                initial_text,
                thread_id=self.thread_id,
            )
            if res.ok and res.message_id:
                self.progress_message_id = res.message_id
                self.last_edit_time = time.time()
                self._last_sent_text = initial_text
                self.latest_text = initial_text
                return res.message_id
            return None

    async def on_progress_event(self, event: AgentProgressEvent) -> None:
        """Process a progress event and update Telegram."""
        if self._closed:
            return

        text = event.summary
        if not text or text == self._last_sent_text:
            return

        self.latest_text = text

        if self.mode == "message":
            # Direct message mode: send each distinct event as a new message
            await self._send_new_update(text)
            return

        # Live edit mode
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_edit_time
            if elapsed >= self.update_interval:
                await self._flush_edit_locked()
            else:
                self._schedule_trailing_flush(self.update_interval - elapsed)

    def _schedule_trailing_flush(self, delay: float) -> None:
        if self._pending_flush is not None and not self._pending_flush.done():
            return

        delay = max(0.001, delay)

        async def _delayed():
            try:
                await asyncio.sleep(delay)
                async with self._lock:
                    if not self._closed and self.latest_text != self._last_sent_text:
                        await self._flush_edit_locked()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Delayed progress flush error: %s", exc)

        self._pending_flush = asyncio.create_task(_delayed())

    async def _flush_edit_locked(self) -> None:
        if self._pending_flush is not None and not self._pending_flush.done():
            self._pending_flush.cancel()
            self._pending_flush = None

        text = self.latest_text
        if not text or text == self._last_sent_text:
            return

        if self.progress_message_id is None:
            # No message yet to edit -> create one
            res = await asyncio.to_thread(
                self.client.send_message,
                self.chat_id,
                text,
                thread_id=self.thread_id,
            )
            if res.ok and res.message_id:
                self.progress_message_id = res.message_id
                self._last_sent_text = text
                self.last_edit_time = time.time()
            return

        # Attempt edit
        res = await asyncio.to_thread(
            self.client.edit_message_text,
            self.chat_id,
            self.progress_message_id,
            text,
        )
        if res.ok:
            self._last_sent_text = text
            self.last_edit_time = time.time()
            return

        # Edit failed (message deleted, too old, or Telegram rejection) -> fallback to sending new message
        logger.debug(
            "Progress edit failed (%s), falling back to new message", res.error
        )
        res_new = await asyncio.to_thread(
            self.client.send_message,
            self.chat_id,
            text,
            thread_id=self.thread_id,
        )
        if res_new.ok and res_new.message_id:
            self.progress_message_id = res_new.message_id
            self._last_sent_text = text
            self.last_edit_time = time.time()

    async def _send_new_update(self, text: str) -> None:
        async with self._lock:
            res = await asyncio.to_thread(
                self.client.send_message,
                self.chat_id,
                text,
                thread_id=self.thread_id,
            )
            if res.ok and res.message_id:
                self._last_sent_text = text
                self.last_edit_time = time.time()

    async def finish(
        self,
        *,
        status: str = "completed",
        final_answer: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Conclude progress streaming and deliver the final answer or error notice."""
        self._closed = True
        if self._pending_flush is not None and not self._pending_flush.done():
            self._pending_flush.cancel()
            self._pending_flush = None

        # Final progress status edit
        if status == "completed":
            self.latest_text = "✅ Task completed"
        elif status == "stopped":
            self.latest_text = "⏹️ Session stopped."
        elif status == "failed":
            self.latest_text = f"❌ Task failed: {error_message or 'unknown error'}"

        async with self._lock:
            await self._flush_edit_locked()

        # Send final answer as separate message(s) if provided
        if final_answer and status == "completed":
            chunks = split_telegram_message(final_answer)
            for chunk in chunks:
                if chunk.strip():
                    await asyncio.to_thread(
                        self.client.send_message,
                        self.chat_id,
                        chunk,
                        thread_id=self.thread_id,
                    )
