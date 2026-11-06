from __future__ import annotations

import random
import re
import time
from typing import Optional, Sequence

from temptf import Message, TempTFClient

MAIL_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "all providers (gmail + high.edu.pl)"),
    ("gmail", "gmail.com (dot + plus)"),
    ("gmail-dot", "gmail.com (dot only)"),
    ("gmail-plus", "gmail.com (plus only)"),
    ("high.edu.pl", "high.edu.pl (edu)"),
)
MAIL_PROVIDERS = tuple(k for k, _ in MAIL_OPTIONS)

_CODE_LINE_RE = re.compile(r"(?m)^\s*([A-Z0-9]{4,8}(?:-[A-Z0-9]{4,8})?|\d{4,8})\s*$")
_CODE_RE = re.compile(r"\b(\d{4,8})\b")

_client = TempTFClient(timeout=20.0)


def generate_email(providers: Optional[Sequence[str]] = None) -> str:
    choice = random.choice(list(providers)) if providers else "all"
    for attempt in range(3):
        try:
            if choice == "gmail":
                return _client.create_gmail()
            if choice == "gmail-dot":
                return _client.create_gmail_dot()
            if choice == "gmail-plus":
                return _client.create_gmail_plus()
            if choice == "outlook":
                return _client.create_outlook()
            if choice == "hotmail":
                return _client.create_hotmail()
            if choice == "high.edu.pl":
                return _client.create_edu()
            return _client.create_email(
                providers=("gmail", "high.edu.pl"),
                dot=True,
                plus=True,
            )
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 + attempt * 2)
    return ""


def inbox(email: str) -> list[Message]:
    return _client.get_messages(email)


def extract_code(text: str) -> Optional[str]:
    if not text:
        return None
    m = _CODE_LINE_RE.search(text)
    if m:
        return m.group(1)
    m = _CODE_RE.search(text)
    return m.group(1) if m else None


def wait_code(
    email: str,
    timeout: float = 120,
    poll: float = 4,
    seen_ids: Optional[set] = None,
) -> Optional[str]:
    seen = seen_ids if seen_ids is not None else set()
    end = time.time() + timeout
    while time.time() < end:
        for msg in _client.get_messages(email):
            mid = msg.id or f"{msg.date}:{msg.subject}"
            if mid in seen:
                continue
            seen.add(mid)
            code = extract_code(f"{msg.subject}\n{msg.text}")
            if code:
                return code
        time.sleep(poll)
    return None
