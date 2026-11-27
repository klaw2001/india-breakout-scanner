"""Telegram alerts. Silent no-op unless TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set (see ~/.paper.env)."""
import os

import requests


def _load_env_file():
    """Fill missing TELEGRAM_* vars from ~/.paper.env, so manual runs work like cron runs."""
    p = os.path.expanduser("~/.paper.env")
    if not os.path.exists(p):
        return
    for line in open(p):
        k, _, v = line.strip().partition("=")
        if k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") and v and not os.environ.get(k):
            os.environ[k] = v.strip().strip('"').strip("'")


def send(text: str) -> bool:
    _load_env_file()
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
