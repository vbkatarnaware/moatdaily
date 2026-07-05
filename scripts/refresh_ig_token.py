#!/usr/bin/env python3
"""
MoatDaily - Instagram token management.

Graph API Explorer hands out SHORT-LIVED tokens (~1-2 hours). For an unattended
pipeline you want a LONG-LIVED token (~60 days) that keeps itself alive.

Two ways this is used:
  1. Bootstrap / manual refresh (CLI): paste a fresh short-lived token into
     settings.yaml, run this script, and it exchanges it for a long-lived one
     and writes it back.
  2. Auto-refresh (imported): publish_instagram.py calls ensure_fresh() before
     every run. If the token is within `days_threshold` of expiry it re-exchanges
     and writes back, so a regularly-run pipeline never lets the token expire -
     no separate cron needed, and it works in whatever host runs the pipeline.

CLI usage:
  python scripts/refresh_ig_token.py            # exchange now + write back
  python scripts/refresh_ig_token.py --check    # report token status only, no writes
  python scripts/refresh_ig_token.py --ensure    # refresh only if expiring soon
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

GRAPH = "https://graph.facebook.com/v21.0"
ROOT = Path(__file__).parent.parent
SETTINGS_PATH = ROOT / "config" / "settings.yaml"
DEFAULT_REFRESH_DAYS = 10  # refresh when fewer than this many days remain


def _get(path, **params):
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def load_settings():
    with open(SETTINGS_PATH) as f:
        return yaml.safe_load(f)


def write_token(new_token):
    """Rewrite only the instagram.access_token line in settings.yaml, preserving
    the rest of the file (comments, formatting) verbatim."""
    lines = SETTINGS_PATH.read_text().splitlines(keepends=True)
    out, done, in_instagram = [], False, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("instagram:"):
            in_instagram = True
        elif in_instagram and line and not line[0].isspace() and stripped:
            in_instagram = False
        if in_instagram and stripped.startswith("access_token:") and not done:
            indent = line[: len(line) - len(line.lstrip())]
            comment = ""
            if "#" in line:
                comment = "  #" + line.split("#", 1)[1].rstrip("\n")
            out.append(f'{indent}access_token: "{new_token}"{comment}\n')
            done = True
        else:
            out.append(line)
    if not done:
        raise RuntimeError("Could not find instagram.access_token line to update")
    SETTINGS_PATH.write_text("".join(out))


def token_info(token):
    """Return the Graph debug_token data dict for a token (empty on error)."""
    info = _get("debug_token", input_token=token, access_token=token)
    return info.get("data", {}) if "error" not in info else {}


def exchange_long_lived(app_id, app_secret, token):
    """short-lived (or long-lived) token -> a fresh long-lived token (~60 days).
    Returns (new_token, expires_in_seconds) or raises."""
    res = _get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=token,
    )
    if "access_token" not in res:
        raise RuntimeError(f"Token exchange failed: {res.get('error', res)}")
    return res["access_token"], res.get("expires_in")


def _seconds_left(data):
    """Seconds until expiry from debug_token data. None if non-expiring or unknown."""
    exp = data.get("expires_at")
    if exp in (0, None):
        return None  # non-expiring (e.g. a Page token) or unknown
    return exp - int(time.time())


def ensure_fresh(settings=None, days_threshold=DEFAULT_REFRESH_DAYS, verbose=True):
    """Auto-refresh entry point. If the current token is within days_threshold of
    expiry (and app_id/app_secret are configured), re-exchange for a fresh
    long-lived token and write it back. Returns the token to use (possibly new),
    or the existing one unchanged if it's still fresh / non-expiring / can't be
    refreshed. Never raises - refresh is best-effort so it can't block a publish."""
    settings = settings or load_settings()
    ig = settings.get("instagram", {})
    token = (ig.get("access_token") or "").strip()
    if not token:
        return token

    data = token_info(token)
    left = _seconds_left(data)
    if left is None:
        return token  # non-expiring or couldn't determine - leave it alone
    if left > days_threshold * 86400:
        if verbose:
            print(f"[token] fresh ({left // 86400}d left), no refresh needed")
        return token

    app_id = str(ig.get("app_id", "")).strip()
    app_secret = str(ig.get("app_secret", "")).strip()
    if not (app_id and app_secret):
        if verbose:
            print(f"[token] expiring in {left // 86400}d but app_id/app_secret not set - cannot auto-refresh")
        return token

    try:
        new_token, expires_in = exchange_long_lived(app_id, app_secret, token)
        write_token(new_token)
        ig["access_token"] = new_token  # keep in-memory settings consistent
        if verbose:
            days = (expires_in or 0) // 86400
            print(f"[token] auto-refreshed - new token valid ~{days}d")
        return new_token
    except Exception as e:
        if verbose:
            print(f"[token] auto-refresh failed ({e}); continuing with existing token")
        return token


def _print_check(token):
    data = token_info(token)
    if not data.get("is_valid"):
        print(f"[check] token INVALID: {data or 'unknown error'}")
        return False
    left = _seconds_left(data)
    exp = "never" if left is None else f"{left // 86400}d ({data.get('expires_at')})"
    print(f"[check] valid | type={data.get('type')} | expires={exp} | scopes={data.get('scopes')}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report token status only, no writes")
    parser.add_argument("--ensure", action="store_true", help="refresh only if expiring soon")
    args = parser.parse_args()

    settings = load_settings()
    ig = settings.get("instagram", {})
    token = (ig.get("access_token") or "").strip()
    if not token:
        sys.exit("instagram.access_token is empty - paste a fresh token from Graph Explorer first.")

    if args.check:
        _print_check(token)
        return

    if args.ensure:
        ensure_fresh(settings)
        return

    # Default: force an exchange now (bootstrap a short-lived token to long-lived).
    app_id = str(ig.get("app_id", "")).strip()
    app_secret = str(ig.get("app_secret", "")).strip()
    if not (app_id and app_secret):
        sys.exit("instagram.app_id and app_secret must be set to exchange for a long-lived token.")
    print("Exchanging for a long-lived token...")
    new_token, expires_in = exchange_long_lived(app_id, app_secret, token)
    write_token(new_token)
    print(f"  new token valid ~{(expires_in or 0) // 86400}d")
    _print_check(new_token)
    print("\nDone. settings.yaml updated.")


if __name__ == "__main__":
    main()
