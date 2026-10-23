import random
import string
import time
from urllib.parse import parse_qs, urlparse

import requests

HOST = "https://bsky.social"
UA = "okhttp/4.12.0"

HTTP_RETRIES = 4
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
BACKOFF_BASE = 8.0


def rand_state(n=16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


class BskyClient:
    def __init__(self, proxy=None, log=None):
        self.log = log or print
        self.s = requests.Session()
        if proxy:
            self.s.proxies.update({"http": proxy, "https": proxy})
        self.s.headers.update({"accept": "application/json", "user-agent": UA})
        self.did = ""
        self.handle = ""
        self.access_jwt = ""
        self.refresh_jwt = ""

    def _request(self, method, url, **kw):
        r = None
        for attempt in range(1, HTTP_RETRIES + 1):
            r = self.s.request(method, url, timeout=30, **kw)
            if r.status_code not in RETRYABLE_STATUS:
                break
            if attempt < HTTP_RETRIES:
                pause = BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 3)
                self.log(
                    f"http {r.status_code} {url.rsplit('/', 1)[-1]}, "
                    f"retry {attempt}/{HTTP_RETRIES - 1} in {pause:.0f}s"
                )
                time.sleep(pause)
        r.raise_for_status()
        return r

    def _xrpc(self, path, json_body=None, params=None):
        if json_body is None:
            return self._request("GET", HOST + path, params=params).json()
        return self._request("POST", HOST + path, json=json_body).json()

    def check_handle(self, handle):
        r = self._xrpc(
            "/xrpc/com.atproto.temp.checkHandleAvailability",
            params={"handle": handle},
        )
        return r.get("result", {}).get("$type", "").endswith("#resultAvailable")

    def gate_code(self, handle, captcha_token, state=None):
        state = state or rand_state()
        q = f"handle={handle}&state={state}&colorScheme=light"
        # attest 303 -> /gate/signup
        self._request("GET", f"{HOST}/gate/signup/attempt-attest?{q}")
        r = self._request(
            "POST",
            f"{HOST}/gate/signup?{q}&error=",
            data={
                "g-recaptcha-response": captcha_token,
                "h-captcha-response": captcha_token,
            },
            allow_redirects=False,
        )
        loc = r.headers.get("location", "")
        code = parse_qs(urlparse(loc).query).get("code", [""])[0]
        if not code:
            raise RuntimeError(f"gate: no code (http {r.status_code})")
        return code

    def create_account(self, email, password, handle, code):
        r = self._xrpc(
            "/xrpc/com.atproto.server.createAccount",
            json_body={
                "email": email,
                "password": password,
                "handle": handle,
                "inviteCode": "",
                "verificationCode": code,
            },
        )
        self.did = r.get("did", "")
        self.handle = r.get("handle", handle)
        self.access_jwt = r.get("accessJwt", "")
        self.refresh_jwt = r.get("refreshJwt", "")
        return r
