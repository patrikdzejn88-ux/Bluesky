import secrets
import time
import uuid

import requests

HCS_API = "https://api.hcaptchasolver.org"
SITEKEY = "e75b29e9-404c-48a4-b89f-7abf6bbd17b1"
ATTEST = "https://bsky.social/gate/signup/attempt-attest?handle={handle}&state={state}&colorScheme=light"


def solve(key, handle=None, timeout=300, poll=5, log=print):
    url = ATTEST.format(handle=handle or "x", state=secrets.token_hex(8))
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    task_id = ""
    for _ in range(25):
        r = requests.post(
            f"{HCS_API}/v2/tasks",
            json={"url": url, "sitekey": SITEKEY},
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
            timeout=45,
        )
        if r.status_code == 429:
            try:
                ra = int(r.headers.get("Retry-After") or 5)
            except ValueError:
                ra = 5
            log(f"captcha: hcs 429, wait {ra}s")
            time.sleep(ra + 1)
            continue
        if r.status_code in (401, 403):
            raise RuntimeError("captcha: bad hcs key")
        if r.status_code == 402:
            raise RuntimeError("captcha: ZERO_BALANCE hcs")
        data = r.json()
        task_id = data.get("id") or ""
        if task_id:
            break
        raise RuntimeError(f"captcha hcs create: {data}")
    if not task_id:
        raise RuntimeError("captcha: hcs rate limit x25")
    log(f"captcha task {task_id} (hcs)")

    end = time.time() + max(timeout, 130)
    time.sleep(poll)
    while time.time() < end:
        data = requests.get(f"{HCS_API}/v2/tasks/{task_id}", headers=headers, timeout=45).json()
        status = data.get("status")
        if status == "ready":
            result = data.get("result") or {}
            if data.get("result_expired") or not result.get("token"):
                raise RuntimeError(f"captcha hcs expired/empty: {data}")
            return result["token"]
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"captcha hcs {status}: {data.get('error')}")
        time.sleep(poll)
    raise TimeoutError("captcha: timeout")
