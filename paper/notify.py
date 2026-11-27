"""Telegram alerts. Silent no-op unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set (see ~/.paper.env)."""
import os

import requests


def send(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": "true"}, timeout=15)
        return r.ok
    except Exception:  # noqa: BLE001
        return False
