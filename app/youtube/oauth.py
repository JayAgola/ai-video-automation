"""OAuth 2.0 (installed-app flow) for YouTube uploads.

Secrets live only in config.YOUTUBE_TOKEN_FILE (git-ignored) — never in
state.json, logs, or API responses. Test mode (TEST_YOUTUBE_MODE) provides a
fake authenticated client clearly labelled TEST — it never touches Google.
"""
from __future__ import annotations

import json

from app.core import config
from app.core.logger import log


class OAuthError(Exception):
    """Controlled OAuth error (message is safe to show; never contains secrets)."""


def _redact(err: Exception) -> str:
    """Return a short error string with anything secret-looking removed."""
    text = str(err)
    for token in ("access_token", "refresh_token", "client_secret", "client_id"):
        text = text.replace(token, "<redacted>")
    return text[:200]


def is_configured() -> bool:
    return config.YOUTUBE_CLIENT_SECRET_FILE.exists()


def get_client(credentials=None):
    """Return an authorized client object, or None when unauthenticated.

    `credentials` may be injected (tests). Loads + refreshes the saved token.
    """
    if config.TEST_YOUTUBE_MODE:
        from app.youtube.test_client import FakeYouTube
        return FakeYouTube()
    if credentials is None:
        if not is_configured():
            return None
        if not config.YOUTUBE_TOKEN_FILE.exists():
            return None
        try:
            from google.oauth2.credentials import Credentials
            raw = json.loads(config.YOUTUBE_TOKEN_FILE.read_text(encoding="utf-8"))
            credentials = Credentials(
                token=raw.get("token"),
                refresh_token=raw.get("refresh_token"),
                token_uri=raw.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=raw.get("client_id"),
                client_secret=raw.get("client_secret"),
                scopes=raw.get("scopes", config.YOUTUBE_OAUTH_SCOPES),
            )
        except Exception as e:
            log("YOUTUBE", "Token load failed: {}".format(_redact(e)))
            return None
    if not credentials.valid:
        try:
            from google.auth.transport.requests import Request
            credentials.refresh(Request())
            save_token(credentials)
            log("YOUTUBE", "Token refreshed")
        except Exception as e:
            log("YOUTUBE", "Token refresh failed (re-authentication required): {}".format(_redact(e)))
            return None
    return credentials


def start_auth() -> str:
    """Return the Google authorization URL for the installed-app flow."""
    if config.TEST_YOUTUBE_MODE:
        raise OAuthError("TEST YOUTUBE MODE — no real OAuth flow")
    if not is_configured():
        raise OAuthError("OAuth client secret file not configured/missing")
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            str(config.YOUTUBE_CLIENT_SECRET_FILE), scopes=config.YOUTUBE_OAUTH_SCOPES)
        flow.redirect_uri = "http://localhost:{}".format(config.YOUTUBE_OAUTH_PORT)
        auth_url, _ = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent")
        return auth_url
    except OAuthError:
        raise
    except Exception as e:
        raise OAuthError("failed to build authorization URL: {}".format(_redact(e)))


def complete_auth(code: str) -> dict:
    """Exchange the authorization code and persist the token (safe fields only)."""
    if config.TEST_YOUTUBE_MODE:
        raise OAuthError("TEST YOUTUBE MODE — no real OAuth flow")
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            str(config.YOUTUBE_CLIENT_SECRET_FILE), scopes=config.YOUTUBE_OAUTH_SCOPES)
        flow.redirect_uri = "http://localhost:{}".format(config.YOUTUBE_OAUTH_PORT)
        flow.fetch_token(code=code)
        save_token(flow.credentials)
        log("YOUTUBE", "OAuth token saved")
        return status()
    except OAuthError:
        raise
    except Exception as e:
        raise OAuthError("token exchange failed: {}".format(_redact(e)))


def save_token(credentials) -> None:
    config.YOUTUBE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or config.YOUTUBE_OAUTH_SCOPES),
    }
    config.YOUTUBE_TOKEN_FILE.write_text(json.dumps(raw), encoding="utf-8")


def status() -> dict:
    """Safe connection status — NEVER returns tokens/secrets."""
    st = {
        "configured": is_configured(),
        "authenticated": False,
        "channel": None,
        "upload_enabled": config.YOUTUBE_UPLOAD_ENABLED,
        "test_mode": config.TEST_YOUTUBE_MODE,
    }
    try:
        creds = get_client()
        st["authenticated"] = creds is not None
    except Exception as e:
        st["error"] = _redact(e)
        return st
    if creds is not None and not config.TEST_YOUTUBE_MODE:
        try:
            from googleapiclient.discovery import build
            yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
            resp = yt.channels().list(part="snippet", mine=True).execute()
            items = resp.get("items", [])
            if items:
                st["channel"] = {"id": items[0]["id"],
                                 "title": items[0]["snippet"]["title"]}
        except Exception as e:
            st["error"] = _redact(e)
    elif config.TEST_YOUTUBE_MODE:
        st["channel"] = {"id": "TEST_CHANNEL", "title": "TEST YOUTUBE MODE — NO REAL CHANNEL"}
    return st
