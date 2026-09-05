"""Escalation push notifications (Telegram / Slack).

When an agent's action is held for approval, ping the operator where they
actually are, with a deep link into mission control to approve or deny.
Fire-and-forget on a worker thread — notification failures never affect the
decision path (which has already been attested by the time we're called).
"""

from __future__ import annotations

import logging
import threading

from eidolon.config import Settings, get_settings

_log = logging.getLogger("eidolon.notify")


def notify_escalation(request_id: str, action_class: str, message: str | None,
                      settings: Settings | None = None) -> None:
    """Push "your agent wants to X — approve?" to all configured channels."""
    settings = settings or get_settings()
    if not (settings.slack_webhook_url or (settings.telegram_bot_token and settings.telegram_chat_id)):
        return
    link = f"{settings.public_url.rstrip('/')}/live" if settings.public_url else None
    text = f"⚑ EIDOLON: your agent wants to run a {action_class} action"
    if message:
        text += f"\n> {message[:300]}"
    text += f"\n[{request_id}] " + (f"approve/deny: {link}" if link else "approve/deny in mission control")
    threading.Thread(target=_send_all, args=(settings, text), daemon=True).start()


def notify_text(text: str, settings: Settings | None = None) -> None:
    """Fire a one-off message to the configured channels (fire-and-forget)."""
    settings = settings or get_settings()
    if not (settings.slack_webhook_url or (settings.telegram_bot_token and settings.telegram_chat_id)):
        return
    threading.Thread(target=_send_all, args=(settings, text), daemon=True).start()


def notify_lead(name: str, email: str, interest: str, message: str,
                settings: Settings | None = None) -> None:
    """Ping the operator when someone wants to collaborate."""
    text = (f"🎮 EIDOLON — new {interest or 'contact'} lead\n"
            f"from: {name or '(no name)'} <{email or 'no email'}>\n"
            f"{message[:400]}")
    notify_text(text, settings)


def _send_all(settings: Settings, text: str) -> None:
    try:
        import httpx

        if settings.slack_webhook_url:
            try:
                httpx.post(settings.slack_webhook_url, json={"text": text}, timeout=5)
            except Exception as exc:  # noqa: BLE001
                _log.warning("slack notify failed: %s", exc)
        if settings.telegram_bot_token and settings.telegram_chat_id:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": settings.telegram_chat_id, "text": text},
                    timeout=5,
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("telegram notify failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 — never let telemetry raise
        _log.warning("notify failed: %s", exc)
