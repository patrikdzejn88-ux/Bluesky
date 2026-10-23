from __future__ import annotations

import argparse
import json
import os
import random
import re
import secrets
import string
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from colorama import Fore, Style, init

from bsky import BskyClient, captcha, mail
from bsky import proxy as proxy_util

init(autoreset=True)

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
ACCOUNTS = LOGS / "accounts.json"
KEY_FILE = ROOT / "captcha_key.txt"

RETRY = 2

BANNER = f"""
{Fore.CYAN}╔═╗╔═╗╦╔═╦ ╦
{Fore.CYAN}╠╩╗╚═╗╠╩╗╚╦╝
{Fore.WHITE}╚═╝╚═╝╩ ╩ ╩ {Style.RESET_ALL}
"""

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _vlen(s: object) -> int:
    return len(_ANSI_RE.sub("", str(s)))


def _panel(title: str, lines: list[tuple[str, str]], col=Fore.CYAN, w: int = 40) -> None:
    inner = w - 4
    bar = "─" * max(w - len(title) - 7, 1)
    print(f" {col}┌── {title} {bar}┐{Style.RESET_ALL}")
    for lbl, val in lines:
        gap = max(inner - _vlen(lbl) - _vlen(val), 1)
        print(f" {col}│{Style.RESET_ALL} {lbl}{' ' * gap}{val} {col}│{Style.RESET_ALL}")
    print(f" {col}└{'─' * (w - 2)}┘{Style.RESET_ALL}")


def log(msg: str) -> None:
    print(msg)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val if val else default


def _ask_int(prompt: str, default: int) -> int:
    try:
        return max(1, int(_ask(prompt, str(default))))
    except ValueError:
        return default


def _clean_handle(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _rand_handle() -> str:
    letters = "".join(random.choices(string.ascii_lowercase, k=8))
    digits = "".join(random.choices(string.digits, k=3))
    return letters + digits


def save_account(row: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    data: list = []
    if ACCOUNTS.exists():
        try:
            parsed = json.loads(ACCOUNTS.read_text(encoding="utf-8"))
            if not isinstance(parsed, list):
                raise ValueError("accounts.json: expected a JSON list")
            data = parsed
        except Exception as e:
            bak = ACCOUNTS.with_name(ACCOUNTS.name + ".bak")
            try:
                ACCOUNTS.replace(bak)
                log(f"  {Fore.RED}accounts.json read error ({e}) — бэкап в {bak.name}{Style.RESET_ALL}")
            except Exception as be:
                log(f"  {Fore.RED}accounts.json read error ({e}); бэкап не удался ({be}){Style.RESET_ALL}")
                return
    by_email = {a.get("email"): a for a in data if a.get("email")}
    by_email[row["email"]] = row
    ACCOUNTS.write_text(
        json.dumps(list(by_email.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_count() -> int:
    if not ACCOUNTS.exists():
        return 0
    try:
        return len(json.loads(ACCOUNTS.read_text(encoding="utf-8")))
    except Exception:
        return 0


def load_captcha_key(cli_key: str) -> str:
    if cli_key:
        return cli_key
    env = os.environ.get("CAPTCHA_KEY", "")
    if env:
        return env
    if KEY_FILE.is_file():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


def _attempt(
    tag: str,
    password: str,
    handle_base: Optional[str],
    captcha_key: str,
    proxy: Optional[dict],
) -> tuple[bool, str]:
    pwd = password or secrets.token_urlsafe(12)
    purl = proxy["url"] if proxy else None
    client = BskyClient(proxy=purl, log=log)

    email = mail.generate_email()
    log(f"  {tag}  {Fore.CYAN}···{Style.RESET_ALL}  {email}")

    handle = ""
    for _ in range(3):
        cand = handle_base or _rand_handle()
        cand = _clean_handle(cand)[:14]
        if handle_base:
            cand += "".join(random.choices(string.digits, k=2))
        full = f"{cand}.bsky.social"
        if client.check_handle(full):
            handle = full
            break
    if not handle:
        return False, f"  {tag}  {Fore.RED}fail{Style.RESET_ALL}  handle taken x3"
    log(f"  {tag}  handle {handle}")

    token = captcha.solve(captcha_key, log=log, handle=handle)
    code = client.gate_code(handle, token)

    reg = client.create_account(email, pwd, handle, code)

    save_account(
        {
            "ts": int(time.time()),
            "registered_at": datetime.now().isoformat(timespec="seconds"),
            "email": email,
            "password": pwd,
            "handle": handle,
            "did": reg.get("did", ""),
            "accessJwt": reg.get("accessJwt", ""),
            "refreshJwt": reg.get("refreshJwt", ""),
        }
    )
    return True, (
        f"  {tag}  {Fore.GREEN}ok{Style.RESET_ALL}  "
        f"{handle}  {email}  pass={pwd}  {Fore.WHITE}{reg.get('did', '')}{Style.RESET_ALL}"
    )


def reg_one(
    idx: int,
    total: int,
    password: str,
    handle_base: Optional[str],
    captcha_key: str,
    proxy: Optional[dict],
) -> tuple[bool, str]:
    tag = f"{Fore.WHITE}[{idx}/{total}]{Style.RESET_ALL}"
    last = f"  {tag}  {Fore.RED}fail{Style.RESET_ALL}"
    for attempt in range(1, RETRY + 1):
        try:
            if proxy:
                proxy_util.rotate(proxy)
            ok, line = _attempt(tag, password, handle_base, captcha_key, proxy)
            if ok:
                return True, line
            last = line
        except Exception as e:
            last = f"  {tag}  {Fore.RED}fail{Style.RESET_ALL}  {e}"
            if "ZERO_BALANCE" in str(e):
                break
        if attempt < RETRY:
            time.sleep(2)
    return False, last


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--password", default="")
    ap.add_argument("--nickname", default="", help="база хендла (пусто = random)")
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--captcha-key", default="", help="ключ hcaptchasolver.org (или captcha_key.txt)")
    ap.add_argument("--proxy", default="", help="один прокси, любой формат")
    ap.add_argument("--change-link", default="", help="ссылка смены IP для --proxy")
    ap.add_argument("--proxies", default=str(ROOT / "proxies.txt"), help="файл со списком прокси")
    ap.add_argument("--no-prompt", action="store_true")
    args = ap.parse_args()

    plist: list[dict] = []
    if args.proxy:
        plist = [proxy_util.make(proxy_util.normalize(args.proxy), args.change_link)]
    elif Path(args.proxies).is_file():
        plist = proxy_util.load(args.proxies)

    captcha_key = load_captcha_key(args.captcha_key)

    print(BANNER)

    password = args.password
    nickname = args.nickname
    count = args.count if args.count > 0 else 1

    if not args.no_prompt:
        print(f"  {Fore.WHITE}setup{Style.RESET_ALL}")
        password = _ask("password", password)
        nickname = _ask("handle base (empty=random)", nickname)
        count = _ask_int("accounts", count)
        if not captcha_key:
            captcha_key = _ask("captcha key")
        print()

    if not captcha_key:
        print(f"  {Fore.RED}нет ключа капчи (--captcha-key / captcha_key.txt){Style.RESET_ALL}")
        return 1

    _panel(
        "config",
        [
            ("accounts", f"{Fore.CYAN}{count}{Style.RESET_ALL}"),
            ("password", "*" * len(password)),
            ("handle", nickname or "random"),
            ("proxies", str(len(plist)) if plist else "off"),
            ("captcha", "..." + captcha_key[-4:]),
            ("saved", str(load_count())),
        ],
    )
    print()

    ok = fail = 0
    t0 = time.time()

    for i in range(1, count + 1):
        success, line = reg_one(
            i,
            count,
            password,
            nickname or None,
            captcha_key,
            plist[(i - 1) % len(plist)] if plist else None,
        )
        log(line)
        if success:
            ok += 1
        else:
            fail += 1

    print()
    _panel(
        "done",
        [
            ("ok", f"{Fore.GREEN}{ok}{Style.RESET_ALL}"),
            ("fail", f"{Fore.RED}{fail}{Style.RESET_ALL}"),
            ("file", "logs/accounts.json"),
            ("time", f"{time.time() - t0:.1f}s"),
        ],
    )
    print()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
