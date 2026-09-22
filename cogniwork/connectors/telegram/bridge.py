"""Telegram Agent Bridge — coordinates CogniOS remote agent sessions over Telegram.

Handles incoming Telegram messages, enforces security allowlists, manages asynchronous
session creation, streaming progress adaptation, interactive approval routing, and
graceful /stop cancellation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from typing import Any, Callable, TYPE_CHECKING

from ...conversations import title_from
from ...engine import ApprovalOutcome, PermissionRequest, TurnEngine
from ...events import Event, EventType
from ...providers.registry import get_descriptor
from ..base import InteractionEvent, MessageEvent, MessageSource, SendResult, SessionSource

if TYPE_CHECKING:
    from ...server.manager import SessionManager
from .artifacts import (
    SendArtifactRequest,
    TelegramArtifact,
    artifact_dedup_key,
    extract_turn_artifacts,
    parse_artifact_send_intent,
    resolve_requested_artifact,
)
from .client import TelegramClient, split_telegram_message
from .events import AgentProgressEvent, normalize_turn_event
from .progress_adapter import TelegramProgressAdapter
from .session_store import ModelSelection, TelegramSessionRecord, TelegramSessionStore

logger = logging.getLogger("cogniwork.connectors.telegram")


def _csv_set(value: str | None) -> set[str]:
    return {p.strip() for p in (value or "").split(",") if p.strip()}


def parse_telegram_command(text: str) -> tuple[str, str]:
    """Parse a Telegram message text into (command, args).

    Returns ('', '') if the text does not start with a command slash.
    Handles bot username mentions like '/model@CogniOS_bot' -> '/model'.
    """
    text = (text or "").strip()
    if not text.startswith("/"):
        return "", ""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]
    args = parts[1].strip() if len(parts) > 1 else ""
    return cmd, args


class TelegramAgentBridge:
    """Production-ready agent bridge between Telegram and CogniOS."""

    def __init__(
        self,
        manager: SessionManager,
        db_path: str | os.PathLike | None = None,
        *,
        client_factory: Callable[[str], TelegramClient] | None = None,
    ) -> None:
        self.manager = manager
        if db_path is None:
            db_path = getattr(manager, "_data_base", None)
            if db_path is not None:
                db_path = os.path.join(str(db_path), "cogniwork.db")
            else:
                db_path = ":memory:"

        self.store = TelegramSessionStore(db_path)
        self._client_factory = client_factory
        self._adapters: dict[str, TelegramProgressAdapter] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._pending_approvals: dict[str, asyncio.Future[ApprovalOutcome]] = {}
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._delivered_artifacts: dict[str, set[str]] = {}

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        """Get or create a per-chat asyncio.Lock for serialized turn/model operations."""
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    def get_client(self) -> TelegramClient | None:
        """Get TelegramClient instance using configured bot token."""
        token: str | None = None
        secret_rec = self.manager.secrets.get("telegram:default")
        if secret_rec and secret_rec.get("enabled", True):
            token = secret_rec.get("bot_token")

        if not token:
            token = os.environ.get("TELEGRAM_BOT_TOKEN")

        if self._client_factory:
            return self._client_factory(token or "test-token")

        if not token:
            return None

        return TelegramClient(token)

    def is_authorized(self, source: MessageSource | SessionSource) -> bool:
        """Enforce environment and secret allowlists for Telegram user/chat IDs."""
        env_allow_all = os.environ.get("TELEGRAM_ALLOW_ALL", "").lower() in ("1", "true", "yes")
        env_allowed_users = _csv_set(os.environ.get("TELEGRAM_ALLOWED_USERS"))
        env_allowed_chats = _csv_set(os.environ.get("TELEGRAM_ALLOWED_CHATS"))

        cfg = self.manager.secrets.get("telegram:default") or {}
        allow_all = bool(cfg.get("allow_all", False)) or env_allow_all
        cfg_allowed_users = set(cfg.get("allowed_users") or [])
        cfg_allowed_chats = set(cfg.get("allowed_chats") or [])

        if allow_all:
            return True

        allowed_users = env_allowed_users | cfg_allowed_users
        allowed_chats = env_allowed_chats | cfg_allowed_chats

        if not allowed_users and not allowed_chats:
            return True

        u_id = str(source.user_id) if source.user_id is not None else None
        c_id = str(source.chat_id) if source.chat_id is not None else None
        u_name = str(source.user_name) if getattr(source, "user_name", None) is not None else None

        candidates: set[str] = set()
        if u_id:
            candidates.add(u_id)
        if c_id:
            candidates.add(c_id)
        if u_name:
            candidates.add(u_name)
            candidates.add(u_name.lstrip("@"))
            candidates.add(f"@{u_name.lstrip('@')}")

        allowed_all = (
            allowed_users
            | allowed_chats
            | {u.lstrip("@") for u in allowed_users}
            | {f"@{u.lstrip('@')}" for u in allowed_users}
        )

        if any(c in allowed_all for c in candidates):
            return True

        logger.warning(
            "[Telegram] Access denied for user_id=%s chat_id=%s user_name=%s",
            u_id,
            c_id,
            u_name,
        )
        return False


    async def handle_inbound(self, event: MessageEvent) -> None:
        """Entry point for inbound messages from Telegram."""
        src = event.source
        chat_id = str(src.chat_id)
        user_id = str(src.user_id or "")
        user_name = src.user_name or user_id or "user"
        raw_text = (event.text or "").strip()

        logger.warning("[TG-TRACE] BRIDGE_ENTER text=%r", raw_text)
        logger.info(
            "[Telegram] BRIDGE_HANDLE_INBOUND chat_id=%s user_id=%s message=%r",
            chat_id,
            user_id,
            raw_text[:80],
        )

        client = self.get_client()
        if client is None:
            logger.warning("[Telegram] No Telegram client configured")
            return

        # 1. Check authorization
        if not self.is_authorized(src):
            logger.warning(
                "[Telegram] UNAUTHORIZED_ACCESS chat_id=%s user_id=%s",
                chat_id,
                user_id,
            )
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                "⛔ You are not authorized to use this CogniOS bot.",
                thread_id=src.thread_id,
            )
            return

        # 2. Strict Command & Callback Routing (PRIORITY: MUST intercept before ANY session creation)
        if raw_text.startswith("model_select:") or raw_text.startswith("model:"):
            logger.info("[TelegramBridge] CALLBACK_QUERY_INTERCEPTED data=%r", raw_text)
            await self.handle_callback_query(
                chat_id=chat_id,
                user_id=user_id,
                callback_data=raw_text,
                message_id=event.message_id,
                user_name=user_name,
                thread_id=src.thread_id,
            )
            return

        cmd, cmd_args = parse_telegram_command(raw_text)
        if cmd:
            logger.warning("[TG-TRACE] COMMAND=%r ARGS=%r", cmd, cmd_args)
            logger.info(
                "[TelegramBridge] COMMAND_RECEIVED command=%s args=%s",
                cmd,
                cmd_args,
            )
            if cmd == "/start":
                await self._handle_start_command(client, chat_id, src.thread_id)
                logger.info("[TelegramBridge] COMMAND_HANDLED command=%s", cmd)
                return
            elif cmd in ("/model", "/models"):
                logger.warning("[TG-TRACE] MODEL_COMMAND")
                await self._handle_model_command(
                    client, chat_id, user_id, src.thread_id, cmd_args
                )
                logger.info("[TelegramBridge] COMMAND_HANDLED command=%s", cmd)
                return
            elif cmd in ("/new", "/reset", "/clear"):
                await self._handle_new_command(
                    client, event, chat_id, user_id, user_name, src.thread_id, cmd_args
                )
                logger.info("[TelegramBridge] COMMAND_HANDLED command=%s", cmd)
                return
            elif cmd in ("/stop", "/cancel"):
                await self._handle_stop_command(client, chat_id, src.thread_id)
                logger.info("[TelegramBridge] COMMAND_HANDLED command=%s", cmd)
                return
            elif cmd == "/approve":
                await self._handle_approval_response(
                    client, chat_id, src.thread_id, outcome=ApprovalOutcome.ONCE
                )
                logger.info("[TelegramBridge] COMMAND_HANDLED command=%s", cmd)
                return
            elif cmd == "/deny":
                await self._handle_approval_response(
                    client, chat_id, src.thread_id, outcome=ApprovalOutcome.DENY
                )
                logger.info("[TelegramBridge] COMMAND_HANDLED command=%s", cmd)
                return

        # 3. Explicit file-send requests (e.g. "Send me the file", "send bubble_sort.c", "download report.pdf")
        is_send_intent, target_ref = parse_artifact_send_intent(raw_text)
        if is_send_intent:
            logger.info(
                "[TelegramBridge] EXPLICIT_SEND_INTENT_DETECTED chat_id=%s target_ref=%r",
                chat_id,
                target_ref,
            )
            await self._handle_explicit_artifact_send(
                client=client,
                event=event,
                chat_id=chat_id,
                user_id=user_id,
                user_name=user_name,
                raw_text=raw_text,
                target_ref=target_ref,
            )
            return

        # 4. Normal user message -> Start new CogniOS session
        logger.warning("[TG-TRACE] NORMAL_MESSAGE")
        logger.info(
            "[TelegramBridge] NORMAL_MESSAGE chat_id=%s user_id=%s",
            chat_id,
            user_id,
        )
        await self._handle_user_prompt(
            client=client,
            event=event,
            prompt=raw_text,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
        )

    async def _handle_explicit_artifact_send(
        self,
        client: TelegramClient,
        event: MessageEvent,
        chat_id: str,
        user_id: str,
        user_name: str,
        raw_text: str,
        target_ref: str | None,
    ) -> None:
        """Handle explicit 'send me the file' / 'send <filename>' request using originating chat_id."""
        logger.info(
            "[TelegramBridge] EXPLICIT_ARTIFACT_SEND_REQUEST chat_id=%s user_id=%s target_ref=%r",
            chat_id,
            user_id,
            target_ref,
        )

        async with self._get_chat_lock(chat_id):
            active_sess = self.manager.session_store.get_active_telegram_session(chat_id)
            rec = self.store.get(chat_id)
            session_id = active_sess.session_id if active_sess else (rec.session_id if rec else None)

            if not session_id:
                await asyncio.to_thread(
                    client.send_message,
                    chat_id,
                    "I couldn't find that file in this session.",
                    thread_id=event.source.thread_id,
                )
                return

            artifact, error_msg, candidates = resolve_requested_artifact(
                self.manager, session_id, target_ref
            )

            if error_msg:
                await asyncio.to_thread(
                    client.send_message,
                    chat_id,
                    error_msg,
                    thread_id=event.source.thread_id,
                )
                return

            if candidates:
                if len(candidates) == 2:
                    file_list = f"`{candidates[0]}` and `{candidates[1]}`"
                elif len(candidates) > 2:
                    file_list = f"{', '.join(f'`{c}`' for c in candidates[:-1])}, and `{candidates[-1]}`"
                else:
                    file_list = f"`{candidates[0]}`"
                ask_msg = f"I found multiple files: {file_list}. Which one should I send?"
                await asyncio.to_thread(
                    client.send_message,
                    chat_id,
                    ask_msg,
                    thread_id=event.source.thread_id,
                )
                return

            if artifact is None:
                await asyncio.to_thread(
                    client.send_message,
                    chat_id,
                    "I couldn't find that file in this session.",
                    thread_id=event.source.thread_id,
                )
                return

            # Destination is implicitly and unambiguously the current Telegram chat
            upload_res = await asyncio.to_thread(
                client.send_document,
                chat_id,
                artifact.resolved_path,
                artifact.filename,
                caption=artifact.filename,
                thread_id=event.source.thread_id,
                mime_type=artifact.mime_type,
            )

            if upload_res.ok:
                confirm_msg = f"📎 {artifact.filename} sent."
                await asyncio.to_thread(
                    client.send_message,
                    chat_id,
                    confirm_msg,
                    thread_id=event.source.thread_id,
                )
                # Mark as delivered in session delivered set
                dedup_key = artifact_dedup_key(session_id, artifact)
                self._delivered_artifacts.setdefault(session_id, set()).add(dedup_key)
                logger.info(
                    "[TelegramBridge] EXPLICIT_ARTIFACT_DELIVERED chat_id=%s session_id=%s filename=%s",
                    chat_id,
                    session_id,
                    artifact.filename,
                )
                try:
                    self.manager.session_store.touch_telegram_activity(
                        session_id,
                        last_message=confirm_msg,
                    )
                except Exception:
                    pass
            else:
                fail_msg = f"⚠️ `{artifact.filename}` was found, but Telegram upload failed."
                await asyncio.to_thread(
                    client.send_message,
                    chat_id,
                    fail_msg,
                    thread_id=event.source.thread_id,
                )
                logger.warning(
                    "[TelegramBridge] EXPLICIT_ARTIFACT_UPLOAD_FAILED chat_id=%s session_id=%s filename=%s error=%s",
                    chat_id,
                    session_id,
                    artifact.filename,
                    upload_res.error,
                )

    async def _handle_start_command(
        self, client: TelegramClient, chat_id: str, thread_id: str | None
    ) -> None:
        text = (
            "👋 Welcome to CogniOS!\n\n"
            "I am your remote AI assistant bridge. Send any task or question to start a new CogniOS session.\n\n"
            "Available commands:\n"
            "• /model — View or switch the active AI model\n"
            "• /models — Alias for /model\n"
            "• /new — Start a fresh session\n"
            "• /stop — Cancel the active task\n"
            "• /approve — Approve a pending tool action\n"
            "• /deny — Reject a pending tool action"
        )
        await asyncio.to_thread(
            client.send_message, chat_id, text, thread_id=thread_id
        )

    async def _handle_new_command(
        self,
        client: TelegramClient,
        event: MessageEvent,
        chat_id: str,
        user_id: str,
        user_name: str,
        thread_id: str | None,
        args: str = "",
    ) -> None:
        # 1. Stop any currently active task for this chat
        task = self._active_tasks.get(chat_id)
        if task and not task.done():
            task.cancel()
            self._active_tasks.pop(chat_id, None)

        old_active = self.store.get(chat_id)
        if old_active:
            engine = self.manager._engines.get(old_active.session_id)
            if engine is not None:
                engine.request_interrupt()

        # 2. Close current active Telegram session in DB
        self.manager.session_store.close_active_telegram_session(chat_id, status="completed")
        self.store.clear_session(chat_id)

        # 3. Create fresh active Telegram session in DB
        model_pref = self.store.get_model_preference(chat_id)
        model_to_use = model_pref.full_id if model_pref else "default"
        persona_id = (
            self.manager.personas.default_id()
            if hasattr(self.manager, "personas") and self.manager.personas
            else "cogniwork"
        )
        ws_dir = (
            str(self.manager.default_workspace)
            if getattr(self.manager, "default_workspace", None)
            else (str(self.manager.workspace) if getattr(self.manager, "workspace", None) else "")
        )
        new_sess = self.manager.session_store.create_telegram_session(
            chat_id=chat_id,
            user_name=user_name,
            model=model_to_use,
            agent=persona_id,
            workspace=ws_dir,
        )
        self.store.set_active_session(
            chat_id=chat_id,
            session_id=new_sess.session_id,
            user_id=user_id,
            user_name=user_name,
            status="IDLE",
        )
        logger.info(
            "[TelegramBridge] NEW_SESSION_CREATED chat_id=%s new_session_id=%s",
            chat_id,
            new_sess.session_id,
        )

        # 4. If prompt args provided, run turn immediately; else send confirmation
        prompt = (args or "").strip()
        if prompt:
            logger.info(
                "[TelegramBridge] NEW_COMMAND_WITH_PROMPT chat_id=%s prompt=%r",
                chat_id,
                prompt[:80],
            )
            await self._handle_user_prompt(
                client=client,
                event=event,
                prompt=prompt,
                chat_id=chat_id,
                user_id=user_id,
                user_name=user_name,
            )
        else:
            text = "✨ New session ready! Send me a task or question to get started."
            await asyncio.to_thread(
                client.send_message, chat_id, text, thread_id=thread_id
            )

    def _get_available_models_list(self) -> list[str]:
        """List of all available models across configured providers and Ollama."""
        models: list[str] = []
        if hasattr(self.manager, "get_settings"):
            try:
                settings = self.manager.get_settings() or {}
                models = list(settings.get("models") or [])
                curr = settings.get("model") or getattr(self.manager, "model", None)
                if curr and curr not in models:
                    models.insert(0, curr)
            except Exception:
                models = []
        if not models and hasattr(self.manager, "get_available_models"):
            try:
                models = list(self.manager.get_available_models() or [])
            except Exception:
                models = []
        if not models:
            models = [getattr(self.manager, "model", "gpt-5.6-sol")]
        return list(dict.fromkeys(models))

    def _format_model_display_name(
        self, model_id: str, labels: dict[str, str] | None = None
    ) -> str:
        """Format a model ID into a user-facing display label for keyboard buttons and messages."""
        if labels and model_id in labels:
            lbl = labels[model_id]
            if lbl:
                return lbl
        bare = model_id.split(":", 1)[-1] if ":" in model_id else model_id
        return bare

    def _encode_model_callback(self, idx: int, model_id: str) -> str:
        """Encode model selection into a compact callback data string (well within Telegram 64-byte limit)."""
        return f"model_select:{idx}"

    def _decode_model_callback(
        self, callback_data: str, models: list[str]
    ) -> str | None:
        """Decode callback data safely into a canonical model string."""
        cb = (callback_data or "").strip()
        if not cb:
            return None

        # Format 1: model_select:<index> or model_select:<key>
        if cb.startswith("model_select:"):
            key = cb[len("model_select:") :].strip()
            if key.isdigit():
                idx = int(key)
                if 0 <= idx < len(models):
                    return models[idx]
            # Match against full canonical IDs
            for m in models:
                if m == key or m.lower() == key.lower():
                    return m
            # Match against bare names or provider suffixes
            for m in models:
                bare = m.split(":", 1)[-1] if ":" in m else m
                if bare.lower() == key.lower() or m.lower().endswith(f":{key.lower()}"):
                    return m
            return None

        # Format 2: model:<provider>:<model_id> or model:<model_id>
        if cb.startswith("model:"):
            key = cb[len("model:") :].strip()
            for m in models:
                if m == key or m.lower() == key.lower():
                    return m
            for m in models:
                bare = m.split(":", 1)[-1] if ":" in m else m
                if bare.lower() == key.lower() or m.lower().endswith(f":{key.lower()}"):
                    return m
            return None

        # Format 3: Direct model name / bare name in callback data
        for m in models:
            if m == cb or m.lower() == cb.lower():
                return m
            bare = m.split(":", 1)[-1] if ":" in m else m
            if bare.lower() == cb.lower():
                return m

        return None

    def _is_same_model(self, m1: str | None, m2: str | None) -> bool:
        """Check whether two model references represent the same canonical model."""
        if not m1 or not m2:
            return False
        if m1 == m2 or m1.lower() == m2.lower():
            return True
        bare1 = m1.split(":", 1)[-1].lower() if ":" in m1 else m1.lower()
        bare2 = m2.split(":", 1)[-1].lower() if ":" in m2 else m2.lower()
        return bare1 == bare2

    def _build_model_keyboard(
        self,
        models: list[str],
        current_model: str,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build native Telegram InlineKeyboardMarkup with checkmark on active model."""
        inline_keyboard: list[list[dict[str, str]]] = []
        for idx, m in enumerate(models):
            disp = self._format_model_display_name(m, labels)
            is_active = self._is_same_model(m, current_model)
            button_text = f"{disp} ✓" if is_active else disp
            cb_data = self._encode_model_callback(idx, m)
            inline_keyboard.append([{"text": button_text, "callback_data": cb_data}])
        return {"inline_keyboard": inline_keyboard}

    def _switch_session_model(
        self, chat_id: str, user_id: str, selected_model_id: str
    ) -> tuple[bool, str, str, str]:
        """Transactional session-scoped model switch service.

        Mutates ONLY the active session model and chat preference.
        NEVER mutates manager.model or global configuration.
        Returns (success, old_model_id, new_model_id, error_message).
        """
        # 1. Resolve available models and validate
        available = self._get_available_models_list()
        matched_model: str | None = None
        for m in available:
            if m == selected_model_id or m.lower() == selected_model_id.lower():
                matched_model = m
                break
        if not matched_model:
            for m in available:
                bare = m.split(":", 1)[-1] if ":" in m else m
                if (
                    bare.lower() == selected_model_id.lower()
                    or m.lower().endswith(f":{selected_model_id.lower()}")
                    or m.lower() == f"ollama:{selected_model_id.lower()}"
                ):
                    matched_model = m
                    break

        if not matched_model:
            return False, "", selected_model_id, "model_not_found"

        canonical_new_model = matched_model

        # 2. Resolve provider
        sel_provider = (
            self.manager._model_provider(canonical_new_model)
            if hasattr(self.manager, "_model_provider")
            else ("ollama" if canonical_new_model.startswith("ollama:") else "openai")
        )

        # 3. Resolve active CogniOS session
        active_sess = self.manager.session_store.get_active_telegram_session(chat_id)
        model_pref = self.store.get_model_preference(chat_id)

        if active_sess:
            session_id = active_sess.session_id
            old_model = active_sess.model
        elif model_pref:
            session_id = None
            old_model = model_pref.full_id
        else:
            session_id = None
            settings = (
                self.manager.get_settings()
                if hasattr(self.manager, "get_settings")
                else {}
            )
            old_model = (
                settings.get("model")
                or getattr(self.manager, "model", "gpt-5.6-sol")
            )

        # 4. Perform session/runtime switch if active session exists
        if active_sess:
            # Rebind cached engine if present in manager._engines
            engine = self.manager._engines.get(session_id)
            if engine is not None:
                try:
                    engine.switch_model(canonical_new_model)
                    self.manager.save(session_id, engine)
                except Exception as exc:
                    logger.warning("[Telegram] Engine model switch failed: %s", exc)

            # Persist model in database sessions table
            if hasattr(self.manager.session_store, "update_session_model"):
                self.manager.session_store.update_session_model(
                    session_id, canonical_new_model
                )
            else:
                active_sess.model = canonical_new_model
                self.manager.session_store.save(active_sess)

        # 5. Persist chat preference in TelegramSessionStore
        self.store.set_model_preference(
            chat_id, user_id, sel_provider, canonical_new_model
        )
        rec = self.store.get(chat_id)
        if rec:
            rec.metadata["model"] = canonical_new_model
            rec.metadata["provider"] = sel_provider
            self.store.update_status(chat_id, rec.status, metadata=rec.metadata)

        logger.info(
            "[TelegramBridge] MODEL_SWITCH_SUCCESS chat_id=%s session_id=%s old_model=%s new_model=%s provider=%s",
            chat_id,
            session_id or "none",
            old_model,
            canonical_new_model,
            sel_provider,
        )

        return True, old_model, canonical_new_model, ""

    async def _handle_model_command(
        self,
        client: TelegramClient,
        chat_id: str,
        user_id: str,
        thread_id: str | None,
        args: str = "",
    ) -> None:
        args = (args or "").strip()
        settings = (
            self.manager.get_settings()
            if hasattr(self.manager, "get_settings")
            else {}
        )
        labels = settings.get("model_labels") or {}
        models = self._get_available_models_list()

        active_sess = self.manager.session_store.get_active_telegram_session(chat_id)
        model_pref = self.store.get_model_preference(chat_id)
        if active_sess:
            curr_model = active_sess.model
            sess_id = active_sess.session_id
        elif model_pref:
            curr_model = model_pref.full_id
            sess_id = None
        else:
            curr_model = (
                settings.get("model")
                or getattr(self.manager, "model", "gpt-5.6-sol")
            )
            sess_id = None

        # 1. /model current
        if args.lower() == "current":
            curr_provider = (
                self.manager._model_provider(curr_model)
                if hasattr(self.manager, "_model_provider")
                else ("ollama" if curr_model.startswith("ollama:") else "openai")
            )
            d = get_descriptor(curr_provider)
            p_title = d.title.split(" (")[0] if d else curr_provider.capitalize()
            disp = self._format_model_display_name(curr_model, labels)
            text = (
                f"🤖 Current Model\n\n"
                f"Model: {disp}\n"
                f"Provider: {p_title}\n"
                f"Session: {'active' if sess_id else 'idle'}"
            )
            await asyncio.to_thread(client.send_message, chat_id, text, thread_id=thread_id)
            return

        # 2. /model default or /model reset
        if args.lower() in ("default", "reset"):
            self.store.clear_model_preference(chat_id)
            def_model = settings.get("model") or getattr(self.manager, "model", "gpt-5.6-sol")
            if active_sess:
                async with self._get_chat_lock(chat_id):
                    self._switch_session_model(chat_id, user_id, def_model)
            disp = self._format_model_display_name(def_model, labels)
            text = (
                f"✅ Model reset to default\n\n"
                f"Active model: {disp}"
            )
            await asyncio.to_thread(client.send_message, chat_id, text, thread_id=thread_id)
            return

        # 3. Bare /model or /models -> Interactive inline picker
        if not args:
            keyboard = self._build_model_keyboard(models, curr_model, labels)
            curr_disp = self._format_model_display_name(curr_model, labels)
            text = (
                f"🤖 Select Model\n\n"
                f"Current model: {curr_disp}\n\n"
                f"Available models:\n\n"
                f"Tap a model to switch."
            )
            logger.info(
                "[TelegramBridge] MODEL_SELECTOR_OPENED chat_id=%s session_id=%s current_model=%s model_count=%d",
                chat_id,
                sess_id or "none",
                curr_model,
                len(models),
            )
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                text,
                reply_markup=keyboard,
                thread_id=thread_id,
            )
            return

        # 4. Direct /model <model>
        selected_full_id: str | None = None
        if args.isdigit():
            idx = int(args)
            if 1 <= idx <= len(models):
                selected_full_id = models[idx - 1]
        else:
            arg_lower = args.lower()
            for m in models:
                lbl = (labels.get(m) or "").lower()
                bare = m.split(":", 1)[-1] if ":" in m else m
                if (
                    m.lower() == arg_lower
                    or bare.lower() == arg_lower
                    or lbl == arg_lower
                    or arg_lower in lbl
                ):
                    selected_full_id = m
                    break
            if not selected_full_id:
                for m in models:
                    if (
                        m.lower().endswith(f":{arg_lower}")
                        or m.lower() == f"ollama:{arg_lower}"
                    ):
                        selected_full_id = m
                        break

        if not selected_full_id:
            text = (
                f"❌ Model not available\n\n"
                f"'{args}' is not available.\n\n"
                f"Use /model to choose from the available models."
            )
            await asyncio.to_thread(client.send_message, chat_id, text, thread_id=thread_id)
            return

        # Check running task protection
        active_rec = self.store.get_active_session(chat_id)
        if active_rec and active_rec.is_active():
            text = (
                f"⚠️ A CogniOS task is currently running.\n\n"
                f"The model cannot be changed for the active task.\n\n"
                f"The new model will be used for your next session."
            )
            await asyncio.to_thread(client.send_message, chat_id, text, thread_id=thread_id)
            return

        async with self._get_chat_lock(chat_id):
            success, old_m, new_m, err = self._switch_session_model(
                chat_id, user_id, selected_full_id
            )

        if not success:
            text = (
                f"❌ Unable to switch model\n\n"
                f"The requested model could not be activated.\n\n"
                f"Your current model remains:\n"
                f"{curr_model}"
            )
            await asyncio.to_thread(client.send_message, chat_id, text, thread_id=thread_id)
            return

        old_disp = self._format_model_display_name(old_m, labels)
        new_disp = self._format_model_display_name(new_m, labels)
        text = (
            f"✅ Model changed\n\n"
            f"{old_disp} → {new_disp}\n\n"
            f"This model is now active for this Telegram session."
        )
        await asyncio.to_thread(client.send_message, chat_id, text, thread_id=thread_id)

    async def handle_callback_query(
        self,
        chat_id: str | int,
        user_id: str | None,
        callback_data: str,
        *,
        message_id: str | int | None = None,
        callback_query_id: str | None = None,
        user_name: str | None = None,
        thread_id: str | None = None,
    ) -> bool:
        """Handle Telegram inline keyboard button callback queries."""
        chat_id_str = str(chat_id)
        user_id_str = str(user_id) if user_id else ""
        client = self.get_client()

        # 1. Authorization check
        src = SessionSource(
            platform="telegram",
            chat_id=chat_id_str,
            user_id=user_id_str if user_id else None,
            user_name=user_name,
            thread_id=str(thread_id) if thread_id else None,
        )
        if not self.is_authorized(src):
            logger.warning(
                "[Telegram] UNAUTHORIZED_CALLBACK chat_id=%s user_id=%s",
                chat_id_str,
                user_id_str,
            )
            if client and callback_query_id:
                await asyncio.to_thread(
                    client.answer_callback_query,
                    callback_query_id,
                    "⛔ You are not authorized to use this CogniOS bot.",
                    show_alert=True,
                )
            return False

        # 2. Immediate acknowledgment to dismiss loading spinner
        if client and callback_query_id:
            await asyncio.to_thread(client.answer_callback_query, callback_query_id)

        # 3. Parse and validate callback payload
        models = self._get_available_models_list()
        selected_model = self._decode_model_callback(callback_data, models)
        if not selected_model:
            logger.warning(
                "[Telegram] INVALID_CALLBACK_PAYLOAD chat_id=%s data=%r",
                chat_id_str,
                callback_data,
            )
            if client and callback_query_id:
                await asyncio.to_thread(
                    client.answer_callback_query,
                    callback_query_id,
                    "❌ Invalid model selection.",
                    show_alert=True,
                )
            return False

        # 4. Serialize via per-chat lock
        async with self._get_chat_lock(chat_id_str):
            settings = (
                self.manager.get_settings()
                if hasattr(self.manager, "get_settings")
                else {}
            )
            labels = settings.get("model_labels") or {}

            # Re-read active session and current model under lock
            active_sess = self.manager.session_store.get_active_telegram_session(
                chat_id_str
            )
            model_pref = self.store.get_model_preference(chat_id_str)
            if active_sess:
                curr_model = active_sess.model
                sess_id = active_sess.session_id
            elif model_pref:
                curr_model = model_pref.full_id
                sess_id = None
            else:
                curr_model = (
                    settings.get("model")
                    or getattr(self.manager, "model", "gpt-5.6-sol")
                )
                sess_id = None

            # Check idempotency: same model clicked
            if self._is_same_model(selected_model, curr_model):
                disp = self._format_model_display_name(selected_model, labels)
                logger.info(
                    "[Telegram] MODEL_SWITCH_ALREADY_ACTIVE chat_id=%s session_id=%s model=%s",
                    chat_id_str,
                    sess_id or "none",
                    selected_model,
                )
                if client and callback_query_id:
                    await asyncio.to_thread(
                        client.answer_callback_query,
                        callback_query_id,
                        f"✅ {disp} is already active.",
                    )
                return True

            # Check running task protection
            active_rec = self.store.get_active_session(chat_id_str)
            if active_rec and active_rec.is_active():
                if client and message_id:
                    text = (
                        "⚠️ A CogniOS task is currently running.\n\n"
                        "The model cannot be changed for the active task."
                    )
                    await asyncio.to_thread(
                        client.edit_message_text,
                        chat_id_str,
                        message_id,
                        text,
                    )
                return False

            # Perform model switch
            success, old_m, new_m, err = self._switch_session_model(
                chat_id_str, user_id_str, selected_model
            )

            if not success:
                logger.warning(
                    "[Telegram] MODEL_SWITCH_FAILED chat_id=%s session_id=%s requested=%s reason=%s",
                    chat_id_str,
                    sess_id or "none",
                    selected_model,
                    err,
                )
                if client and message_id:
                    curr_disp = self._format_model_display_name(curr_model, labels)
                    text = (
                        f"❌ Unable to switch model\n\n"
                        f"The requested model could not be activated.\n\n"
                        f"Your current model remains:\n"
                        f"{curr_disp}"
                    )
                    await asyncio.to_thread(
                        client.edit_message_text,
                        chat_id_str,
                        message_id,
                        text,
                    )
                return False

            # Successful switch: edit original message and refresh keyboard
            old_disp = self._format_model_display_name(old_m, labels)
            new_disp = self._format_model_display_name(new_m, labels)
            text = (
                f"✅ Model Changed\n\n"
                f"Previous:\n{old_disp}\n\n"
                f"Current:\n{new_disp}\n\n"
                f"Active for this Telegram session."
            )
            new_keyboard = self._build_model_keyboard(models, new_m, labels)

            if client and message_id:
                try:
                    await asyncio.to_thread(
                        client.edit_message_text,
                        chat_id_str,
                        message_id,
                        text,
                        reply_markup=new_keyboard,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Telegram] Failed to edit message after model switch: %s",
                        exc,
                    )

            return True

    async def handle_interaction(self, event: InteractionEvent) -> None:
        """Entry point for connector interaction events (e.g. button clicks)."""
        if getattr(event, "platform", None) != "telegram":
            return
        await self.handle_callback_query(
            chat_id=event.chat_id,
            user_id=event.user_id,
            callback_data=event.value,
            message_id=event.message_id,
            callback_query_id=event.response_url,
            user_name=event.user_name,
        )

    async def _handle_stop_command(
        self, client: TelegramClient, chat_id: str, thread_id: str | None
    ) -> None:
        rec = self.store.get(chat_id)
        if not rec:
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                "ℹ️ No active CogniOS session.",
                thread_id=thread_id,
            )
            return

        session_id = rec.session_id
        logger.info(
            "[TelegramBridge] STOP_REQUESTED chat_id=%s session_id=%s",
            chat_id,
            session_id,
        )

        # 1. Resolve pending approval if waiting
        fut = self._pending_approvals.get(chat_id)
        if fut and not fut.done():
            fut.set_result(ApprovalOutcome.DENY)

        # 2. Interrupt engine
        engine = self.manager._engines.get(session_id)
        if engine is not None:
            try:
                engine.request_interrupt()
            except Exception as exc:
                logger.debug("Engine interrupt exception: %s", exc)

        # 3. Await task cancellation / completion
        task = self._active_tasks.get(chat_id)
        if task and not task.done():
            task.cancel()
            self._active_tasks.pop(chat_id, None)

        # 4. Close the stopped session in DB and clear store
        self.manager.session_store.close_active_telegram_session(chat_id, status="stopped")
        self.manager.mark_idle(session_id)
        self.store.clear_session(chat_id)

        # 5. Create fresh active session for next prompt
        user_name = rec.user_name
        model_pref = self.store.get_model_preference(chat_id)
        model_to_use = model_pref.full_id if model_pref else "default"
        persona_id = (
            self.manager.personas.default_id()
            if hasattr(self.manager, "personas") and self.manager.personas
            else "cogniwork"
        )
        ws_dir = str(self.manager.workspace) if getattr(self.manager, "workspace", None) else ""
        fresh_sess = self.manager.session_store.create_telegram_session(
            chat_id=chat_id,
            user_name=user_name,
            model=model_to_use,
            agent=persona_id,
            workspace=ws_dir,
        )
        self.store.set_active_session(
            chat_id=chat_id,
            session_id=fresh_sess.session_id,
            user_id=rec.user_id,
            user_name=user_name,
            status="IDLE",
        )

        adapter = self._adapters.pop(chat_id, None)
        if adapter:
            await adapter.finish(status="stopped")
        await asyncio.to_thread(
            client.send_message,
            chat_id,
            "⏹️ Session stopped. A fresh session is ready for your next message.",
            thread_id=thread_id,
        )

        logger.info(
            "[TelegramBridge] SESSION_STOPPED chat_id=%s old_session_id=%s fresh_session_id=%s",
            chat_id,
            session_id,
            fresh_sess.session_id,
        )

    async def _handle_approval_response(
        self,
        client: TelegramClient,
        chat_id: str,
        thread_id: str | None,
        outcome: ApprovalOutcome,
    ) -> None:
        fut = self._pending_approvals.get(chat_id)
        if fut and not fut.done():
            fut.set_result(outcome)
            feedback = (
                "👍 Approved. Resuming task..."
                if outcome == ApprovalOutcome.ONCE
                else "🚫 Denied. Resuming task without action..."
            )
            await asyncio.to_thread(
                client.send_message, chat_id, feedback, thread_id=thread_id
            )
        else:
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                "ℹ️ No active approval request.",
                thread_id=thread_id,
            )

    async def _handle_user_prompt(
        self,
        client: TelegramClient,
        event: MessageEvent,
        prompt: str,
        chat_id: str,
        user_id: str,
        user_name: str,
    ) -> None:
        # 1. Concurrency check: one in-flight task per chat ID
        task = self._active_tasks.get(chat_id)
        if task and not task.done():
            reply = (
                f"You already have a CogniOS task running in this session.\n\n"
                f"Please wait for it to complete or use /stop to cancel it."
            )
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                reply,
                thread_id=event.source.thread_id,
            )
            return

        # 2. Authoritative lookup of active Telegram session from DB
        model_pref = self.store.get_model_preference(chat_id)
        model_to_use = model_pref.full_id if model_pref else None
        persona_id = (
            self.manager.personas.default_id()
            if hasattr(self.manager, "personas") and self.manager.personas
            else "cogniwork"
        )
        ws_dir = (
            str(self.manager.default_workspace)
            if getattr(self.manager, "default_workspace", None)
            else (str(self.manager.workspace) if getattr(self.manager, "workspace", None) else "")
        )

        active_sess = self.manager.session_store.get_active_telegram_session(chat_id)
        if active_sess is None:
            active_sess = self.manager.session_store.create_telegram_session(
                chat_id=chat_id,
                user_name=user_name,
                display_name=event.source.user_name or user_name,
                model=model_to_use or "default",
                agent=persona_id,
                workspace=ws_dir,
            )
            session_id = active_sess.session_id
            logger.info(
                "[Telegram] ACTIVE_SESSION_CREATED chat_id=%s user_id=%s session_id=%s",
                chat_id,
                user_id,
                session_id,
            )
        else:
            session_id = active_sess.session_id
            logger.info(
                "[Telegram] ACTIVE_SESSION_REUSED chat_id=%s user_id=%s session_id=%s",
                chat_id,
                user_id,
                session_id,
            )

        # 3. Record in-flight turn execution in SQLite store
        meta = {}
        if model_pref:
            meta["model"] = model_pref.full_id
            meta["provider"] = model_pref.provider

        self.store.set_active_session(
            chat_id=chat_id,
            session_id=session_id,
            user_id=user_id,
            user_name=user_name,
            prompt=prompt,
            status="RUNNING",
            metadata=meta,
        )

        # 4. Setup approval callback for this session
        async def _approver(req: PermissionRequest) -> ApprovalOutcome:
            if not os.environ.get("TELEGRAM_ENABLE_APPROVALS", "true").lower() in ("1", "true", "yes"):
                return ApprovalOutcome.ONCE

            self.store.update_status(chat_id, "WAITING_APPROVAL")
            fut = asyncio.get_running_loop().create_future()
            self._pending_approvals[chat_id] = fut

            # Send approval request to Telegram
            args_str = ""
            if req.arguments:
                args_str = f"\nArguments:\n{req.arguments}"
            msg = (
                f"⚠️ CogniOS needs your approval before continuing.\n\n"
                f"Action:\n{req.tool_name}\n"
                f"Reason:\n{req.reason}{args_str}\n\n"
                f"Reply with:\n/approve\nor\n/deny"
            )
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                msg,
                thread_id=event.source.thread_id,
            )

            try:
                outcome = await fut
                return outcome
            finally:
                self._pending_approvals.pop(chat_id, None)
                if self.store.get(chat_id):
                    self.store.update_status(chat_id, "RUNNING")

        # 5. Instantiate / load engine
        persona_id = self.manager.personas.default_id()
        engine = self.manager.get_engine(
            session_id, approver=_approver, agent=persona_id, model=model_to_use
        )
        if engine is None:
            self.store.update_status(
                chat_id, "ERROR", error="could not build engine"
            )
            await asyncio.to_thread(
                client.send_message,
                chat_id,
                "❌ Could not initialize CogniOS agent engine.",
                thread_id=event.source.thread_id,
            )
            return

        # 6. Update session metadata and touch activity
        self.manager.session_store.touch_telegram_activity(
            session_id,
            last_message=prompt[:120],
            increment_unread=True,
        )
        self.manager.save(session_id, engine)

        # 7. Initialize progress adapter
        adapter = TelegramProgressAdapter(
            client=client,
            chat_id=chat_id,
            thread_id=event.source.thread_id,
        )
        self._adapters[chat_id] = adapter

        # 8. Start progress tracking with immediate acknowledgment
        msg_id = await adapter.start("🟢 CogniOS session started")
        if msg_id:
            logger.info(
                "[Telegram] PROGRESS_MESSAGE_SENT chat_id=%s message_id=%s",
                chat_id,
                msg_id,
            )
            self.store.update_status(chat_id, "RUNNING", progress_message_id=msg_id)

        # 9. Launch asynchronous background turn execution
        task = asyncio.create_task(
            self._run_session_turn(
                session_id=session_id,
                chat_id=chat_id,
                prompt=prompt,
                engine=engine,
                adapter=adapter,
                event=event,
            )
        )
        self._active_tasks[chat_id] = task

    async def _run_session_turn(
        self,
        session_id: str,
        chat_id: str,
        prompt: str,
        engine: TurnEngine,
        adapter: TelegramProgressAdapter,
        event: MessageEvent,
    ) -> None:
        src = event.source
        ms = MessageSource(
            connector="telegram",
            kind="dm" if src.chat_type == "dm" else "channel",
            channel_id=src.chat_id,
            channel_name=src.chat_name or src.chat_id,
            sender_id=src.user_id or "",
            sender_name=src.user_name or src.user_id or "?",
            ts=time.time(),
            text=prompt,
        )

        if not self.manager.try_mark_running(session_id):
            logger.warning(
                "[Telegram] Session %s already running turn", session_id
            )
            return

        logger.warning("[TG-TRACE] TURN_START")
        logger.info("[Telegram] TURN_STARTED session_id=%s chat_id=%s", session_id, chat_id)
        final_answer: str | None = None
        turn_status = "completed"
        error_msg: str | None = None
        turn_start_time = time.time()
        pre_turn_artifacts: dict[str, float] = {}
        try:
            pre_turn_artifacts = {
                a.get("path"): a.get("modified_at", 0.0)
                for a in self.manager.list_artifacts(session_id)
                if a.get("path")
            }
        except Exception:
            pass
        turn_events: list[Event] = []
        tool_candidates: list[str] = []

        try:
            async for ev in engine.run(prompt, source=ms.to_dict()):
                turn_events.append(ev)

                # 1. Broadcast event to GUI sockets so web UI shows live trace
                await self.manager.broadcast_session(
                    session_id, {"type": ev.type.value, "data": ev.data}
                )

                # 2. Checkpoint session
                if ev.type.value in (
                    "turn_start",
                    "permission_required",
                    "directory_requested",
                    "plan_proposed",
                    "iteration_end",
                ):
                    self.manager.save(session_id, engine)

                logger.debug(
                    "[Telegram] TURN_EVENT_RECEIVED session_id=%s event_type=%s",
                    session_id,
                    ev.type.value,
                )

                # Track structured tool path references
                if ev.type in (
                    EventType.TOOL_STARTED,
                    EventType.TOOL_PROPOSED,
                    EventType.TOOL_FINISHED,
                ):
                    args = (ev.data or {}).get("arguments") or {}
                    if isinstance(args, dict):
                        p = args.get("path") or args.get("file")
                        if isinstance(p, str) and p and p not in tool_candidates:
                            tool_candidates.append(p)
                    d_path = (ev.data or {}).get("path") or (ev.data or {}).get("file")
                    if isinstance(d_path, str) and d_path and d_path not in tool_candidates:
                        tool_candidates.append(d_path)

                # 3. Stream normalized progress event to Telegram
                prog_ev = normalize_turn_event(ev, session_id)
                if prog_ev is not None:
                    logger.info(
                        "[Telegram] TELEGRAM_PROGRESS_UPDATE session_id=%s kind=%s summary=%r",
                        session_id,
                        prog_ev.kind,
                        prog_ev.summary[:60],
                    )
                    await adapter.on_progress_event(prog_ev)

                # 4. Capture assistant answer / error
                if ev.type == EventType.ASSISTANT_MESSAGE:
                    text = (ev.data or {}).get("text")
                    if text:
                        final_answer = text
                elif ev.type == EventType.ERROR:
                    turn_status = "failed"
                    error_msg = str((ev.data or {}).get("error") or "Unknown error")
                elif ev.type == EventType.INTERRUPTED:
                    turn_status = "stopped"

            self.manager.save(session_id, engine)

        except asyncio.CancelledError:
            turn_status = "stopped"
            logger.info(
                "[Telegram] Turn task cancelled for session %s",
                session_id,
            )
        except Exception as exc:
            turn_status = "failed"
            error_msg = str(exc)
            logger.exception(
                "[Telegram] Turn execution failed for session %s: %s",
                session_id,
                exc,
            )
        finally:
            self.manager.mark_idle(session_id)
            if final_answer:
                try:
                    self.manager.session_store.touch_telegram_activity(
                        session_id,
                        last_message=final_answer[:120],
                    )
                except Exception:
                    pass
            try:
                self.manager.save(session_id, engine)
            except Exception:
                pass
            try:
                await self.manager.broadcast_session(
                    session_id, {"type": "turn_done", "data": {}}
                )
            except Exception:
                pass

            # In-flight turn execution ends; session remains active and IDLE in store
            db_status = (
                "IDLE"
                if turn_status == "completed"
                else ("STOPPED" if turn_status == "stopped" else "ERROR")
            )
            try:
                self.store.update_status(
                    chat_id, db_status, error=error_msg
                )
            except Exception:
                pass
            self._active_tasks.pop(chat_id, None)
            self._pending_approvals.pop(chat_id, None)
            self._adapters.pop(chat_id, None)

            # Finalize progress adapter and deliver final answer
            await adapter.finish(
                status=turn_status,
                final_answer=final_answer,
                error_message=error_msg,
            )
            if final_answer and turn_status == "completed":
                logger.info(
                    "[Telegram] FINAL_RESPONSE_SENT session_id=%s chat_id=%s answer_len=%s",
                    session_id,
                    chat_id,
                    len(final_answer),
                )

            # Deliver any artifacts created or modified during THIS turn
            await self._deliver_turn_artifacts(
                session_id=session_id,
                chat_id=chat_id,
                thread_id=event.source.thread_id,
                turn_events=turn_events,
                final_answer=final_answer,
                turn_start_time=turn_start_time,
                pre_turn_artifacts=pre_turn_artifacts,
                tool_candidates=tool_candidates,
            )

            logger.info(
                "[Telegram] TURN_FINISHED chat_id=%s session_id=%s status=%s",
                chat_id,
                session_id,
                db_status,
            )

    async def _deliver_turn_artifacts(
        self,
        session_id: str,
        chat_id: str,
        thread_id: str | None,
        turn_events: list[Event],
        final_answer: str | None,
        turn_start_time: float,
        pre_turn_artifacts: dict[str, float],
        tool_candidates: list[str],
    ) -> None:
        """Discover, validate, deduplicate, and upload artifacts for this turn to Telegram."""
        client = self.get_client()
        if client is None:
            return

        try:
            artifacts = extract_turn_artifacts(
                manager=self.manager,
                session_id=session_id,
                turn_events=turn_events,
                final_answer=final_answer,
                turn_start_time=turn_start_time,
                pre_turn_artifacts=pre_turn_artifacts,
                tool_candidates=tool_candidates,
            )
        except Exception as exc:
            logger.exception(
                "[Telegram] Artifact extraction failed for session %s: %s",
                session_id,
                exc,
            )
            return

        if not artifacts:
            return

        session_delivered = self._delivered_artifacts.setdefault(session_id, set())

        for art in artifacts:
            dedup_key = artifact_dedup_key(session_id, art)
            if dedup_key in session_delivered:
                logger.info(
                    "[Telegram] Artifact %s already delivered in session %s — skipping",
                    art.filename,
                    session_id,
                )
                continue

            try:
                # Dispatch document upload to Telegram
                res = await asyncio.to_thread(
                    client.send_document,
                    chat_id,
                    art.resolved_path,
                    art.filename,
                    caption=art.filename,
                    thread_id=thread_id,
                    mime_type=art.mime_type,
                )

                if res.ok:
                    session_delivered.add(dedup_key)
                    logger.info(
                        "[Telegram] ARTIFACT_DELIVERED chat_id=%s session_id=%s filename=%s path=%s",
                        chat_id,
                        session_id,
                        art.filename,
                        art.resolved_path,
                    )
                else:
                    logger.warning(
                        "[Telegram] ARTIFACT_UPLOAD_FAILED chat_id=%s session_id=%s filename=%s path=%s error=%s",
                        chat_id,
                        session_id,
                        art.filename,
                        art.resolved_path,
                        res.error,
                    )
                    warn_text = (
                        f"⚠️ The file `{art.filename}` was created successfully, but Telegram upload failed."
                    )
                    await asyncio.to_thread(
                        client.send_message,
                        chat_id,
                        warn_text,
                        thread_id=thread_id,
                    )
            except Exception as exc:
                logger.exception(
                    "[Telegram] ARTIFACT_UPLOAD_EXCEPTION chat_id=%s session_id=%s filename=%s path=%s error=%s",
                    chat_id,
                    session_id,
                    art.filename,
                    art.resolved_path,
                    exc,
                )
                warn_text = (
                    f"⚠️ The file `{art.filename}` was created successfully, but Telegram upload failed."
                )
                try:
                    await asyncio.to_thread(
                        client.send_message,
                        chat_id,
                        warn_text,
                        thread_id=thread_id,
                    )
                except Exception:
                    pass

    def recover_stale_sessions(self) -> list[TelegramSessionRecord]:
        """Recover any orphaned sessions on server startup."""
        recovered = self.store.recover_stale_sessions()
        for r in recovered:
            logger.info(
                "[TelegramBridge] STALE_SESSION_RECOVERED chat_id=%s session_id=%s",
                r.chat_id,
                r.session_id,
            )
        return recovered

