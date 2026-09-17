import json
import os
import re
import sys
from urllib.parse import urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    read_url_arg, json_out, make_session,
    UA_CHROME,
)

GATE = "linkunlock"

API_BASE = "https://api.link-unlock.com"
SITE_BASE = "https://link-unlock.com"

HOSTS = {"link-unlock.com"}

UA = UA_CHROME


def is_linkunlock_url(url):
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host in HOSTS


def safe_parse(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def extract_cookies(resp):
    out = []
    raw = None
    try:
        raw = resp.headers.get("set-cookie")
    except Exception:
        raw = None
    if not raw:
        return out
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, list):
        raw = [str(raw)]
    for line in raw:
        m = re.match(r"^([^=]+)=([^;]*)", line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def main():
    url = read_url_arg()
    if not is_linkunlock_url(url):
        json_out(False, error="Not a link-unlock URL", gate=GATE)

    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts:
        json_out(False, error="Link-Unlock URL missing slug (expected /<slug>)", gate=GATE)
    slug = parts[0]

    try:
        from curl_cffi import requests as creq
        session = creq.Session(impersonate="chrome120")
    except ImportError:
        import requests as creq
        session = creq.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
    })

    hops = [url]

    csrf_url = f"{API_BASE}/auth/csrf-token"
    try:
        csrf_resp = session.get(
            csrf_url,
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=10,
        )
    except Exception as e:
        json_out(False, error=f"CSRF token fetch failed: {e}", gate=GATE)
    hops.append(csrf_url)

    csrf_body = safe_parse(csrf_resp.text)
    if not csrf_body or not csrf_body.get("csrfToken"):
        json_out(
            False,
            error=f"Failed to fetch CSRF token (status {getattr(csrf_resp, 'status_code', '?')})",
            gate=GATE,
        )
    csrf = csrf_body["csrfToken"]

    cookies = extract_cookies(csrf_resp)
    cookie_header = "; ".join(f"{n}={v}" for n, v in cookies)

    unlock_url = f"{API_BASE}/u/{quote(slug)}"
    unlock_headers = {
        "Accept": "application/json",
        "User-Agent": UA,
        "Referer": f"{SITE_BASE}/{slug}",
        "Origin": SITE_BASE,
    }
    if cookie_header:
        unlock_headers["Cookie"] = cookie_header
    try:
        unlock_resp = session.get(unlock_url, headers=unlock_headers, timeout=10)
    except Exception as e:
        json_out(False, error=f"unlock data fetch failed: {e}", gate=GATE)
    hops.append(unlock_url)

    unlock_body = safe_parse(unlock_resp.text)
    if not unlock_body or not unlock_body.get("unlock") or not unlock_body["unlock"].get("steps"):
        json_out(
            False,
            error=f"Failed to fetch unlock data (status {getattr(unlock_resp, 'status_code', '?')})",
            gate=GATE,
        )
    step_ids = [s.get("id") for s in unlock_body["unlock"]["steps"] if s.get("id")]

    complete_url = f"{API_BASE}/u/{quote(slug)}/complete"
    complete_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Referer": f"{SITE_BASE}/{slug}",
        "Origin": SITE_BASE,
        "x-csrf-token": csrf,
    }
    if cookie_header:
        complete_headers["Cookie"] = cookie_header
    body = json.dumps({"steps": step_ids, "offerSessions": []}).encode("utf-8")
    try:
        complete_resp = session.post(
            complete_url,
            headers=complete_headers,
            data=body,
            timeout=10,
        )
    except Exception as e:
        json_out(False, error=f"complete POST failed: {e}", gate=GATE)
    hops.append(complete_url)

    complete_json = safe_parse(complete_resp.text)
    if not complete_json:
        json_out(
            False,
            error=f"Complete endpoint returned non-JSON (status {getattr(complete_resp, 'status_code', '?')})",
            gate=GATE,
        )
    if not complete_json.get("success") or not complete_json.get("destinationUrl"):
        json_out(
            False,
            error=f"Complete failed: {complete_json.get('error') or complete_json.get('message') or 'no destinationUrl'}",
            gate=GATE,
        )

    target = complete_json["destinationUrl"]
    if not re.match(r"^https?://", target, re.I):
        json_out(False, error=f"destinationUrl is not http(s): {target}", gate=GATE)

    hops.append(target)
    json_out(True, destination=target, gate=GATE, hops=hops)


if __name__ == "__main__":
    main()