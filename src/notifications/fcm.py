"""
Firebase Cloud Messaging (FCM) notification sender.

Uses the FCM HTTP v1 API with a Google service account for authentication.
The service account JSON is stored in the DB settings table under the key
'fcm_service_account_json', and the admin enters it via the web settings page.

Dependencies: google-auth, httpx (both already in requirements.txt).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

_FCM_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
_SCOPES  = ["https://www.googleapis.com/auth/firebase.messaging"]


def _access_token(service_account_json: str) -> Optional[tuple[str, str]]:
    """Return (bearer_token, project_id) or None if credentials are invalid."""
    try:
        from google.oauth2 import service_account as _sa
        import google.auth.transport.requests as _req

        info       = json.loads(service_account_json)
        project_id = info.get("project_id", "")
        if not project_id:
            log.error("fcm: no project_id in service account JSON")
            return None

        creds = _sa.Credentials.from_service_account_info(info, scopes=_SCOPES)
        creds.refresh(_req.Request())
        return creds.token, project_id
    except Exception as exc:
        log.error("fcm: failed to obtain access token: %s", exc)
        return None


def send_pour_notification(
    *,
    tokens:               list[str],
    user_name:            str,
    beer_name:            str,
    ounces:               float,
    price:                float,
    service_account_json: str,
) -> int:
    """
    Send a push notification to every registered device.
    Returns the number of tokens successfully notified.
    Silently skips if tokens list is empty or credentials are not set.
    """
    if not tokens or not service_account_json.strip():
        return 0

    result = _access_token(service_account_json)
    if result is None:
        return 0
    bearer, project_id = result

    import httpx

    url     = _FCM_URL.format(project_id=project_id)
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    body    = f"{user_name} poured {ounces:.1f} oz of {beer_name}"
    if price > 0:
        body += f" (${price:.2f})"

    sent = 0
    for token in tokens:
        payload = {
            "message": {
                "token": token,
                "notification": {
                    "title": "🍺 Pour Detected",
                    "body":  body,
                },
                "data": {
                    "user_name": user_name,
                    "beer_name": beer_name,
                    "ounces":    f"{ounces:.2f}",
                    "price":     f"{price:.2f}",
                },
                "android": {
                    "priority": "high",
                    "notification": {"sound": "default", "channel_id": "pours"},
                },
            }
        }
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if r.status_code == 200:
                sent += 1
            else:
                log.warning("fcm: send failed (status %d): %s", r.status_code, r.text[:200])
        except Exception as exc:
            log.warning("fcm: send error for token: %s", exc)

    log.info("fcm: notified %d/%d device(s) — pour by %s", sent, len(tokens), user_name)
    return sent


def send_keg_low_notification(
    *,
    tokens:               list[str],
    beer_name:            str,
    pct_remaining:        float,
    service_account_json: str,
) -> int:
    if not tokens or not service_account_json.strip():
        return 0
    result = _access_token(service_account_json)
    if result is None:
        return 0
    bearer, project_id = result

    import httpx
    url     = _FCM_URL.format(project_id=project_id)
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    body    = f"{beer_name} is running low — {pct_remaining:.0f}% remaining."

    sent = 0
    for token in tokens:
        payload = {
            "message": {
                "token": token,
                "notification": {"title": "⚠️ Keg Running Low", "body": body},
                "data": {"beer_name": beer_name, "pct_remaining": f"{pct_remaining:.1f}"},
                "android": {"priority": "high", "notification": {"sound": "default", "channel_id": "pours"}},
            }
        }
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if r.status_code == 200:
                sent += 1
            else:
                log.warning("fcm: keg-low send failed (status %d): %s", r.status_code, r.text[:200])
        except Exception as exc:
            log.warning("fcm: keg-low send error: %s", exc)

    log.info("fcm: keg-low — notified %d/%d device(s)", sent, len(tokens))
    return sent


def send_temp_alert_notification(
    *,
    tokens:               list[str],
    temp_f:               float,
    threshold_f:          float,
    service_account_json: str,
) -> int:
    if not tokens or not service_account_json.strip():
        return 0
    result = _access_token(service_account_json)
    if result is None:
        return 0
    bearer, project_id = result

    import httpx
    url     = _FCM_URL.format(project_id=project_id)
    headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
    body    = f"Kegerator temp is {temp_f:.1f}°F — above your {threshold_f:.0f}°F alert threshold."

    sent = 0
    for token in tokens:
        payload = {
            "message": {
                "token": token,
                "notification": {"title": "🌡️ Temperature Alert", "body": body},
                "data": {"temp_f": f"{temp_f:.1f}", "threshold_f": f"{threshold_f:.1f}"},
                "android": {"priority": "high", "notification": {"sound": "default", "channel_id": "pours"}},
            }
        }
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if r.status_code == 200:
                sent += 1
            else:
                log.warning("fcm: temp-alert send failed (status %d): %s", r.status_code, r.text[:200])
        except Exception as exc:
            log.warning("fcm: temp-alert send error: %s", exc)

    log.info("fcm: temp-alert %.1f°F — notified %d/%d device(s)", temp_f, sent, len(tokens))
    return sent
