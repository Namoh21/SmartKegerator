"""
Email notification sender.

Reads SMTP configuration from the database settings table and sends
notifications for keg events, pours, temperature alerts, and new users.

All sends are fire-and-forget (run in a daemon thread) so they never
block the main application loop.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Well-known SMTP presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict] = {
    "gmail": {
        "label":    "Gmail",
        "host":     "smtp.gmail.com",
        "port":     587,
        "security": "starttls",
        "note":     (
            "Gmail requires an <strong>App Password</strong> — your regular Google password "
            "will not work. Go to <a href='https://myaccount.google.com/apppasswords' "
            "target='_blank' rel='noopener'>myaccount.google.com/apppasswords</a> to generate one. "
            "Two-factor authentication must be enabled on your account."
        ),
    },
    "icloud": {
        "label":    "iCloud / Apple Mail",
        "host":     "smtp.mail.me.com",
        "port":     587,
        "security": "starttls",
        "note":     (
            "iCloud requires an <strong>App-Specific Password</strong>. "
            "Generate one at <a href='https://appleid.apple.com' target='_blank' "
            "rel='noopener'>appleid.apple.com</a> → Sign-In and Security → App-Specific Passwords."
        ),
    },
    "outlook": {
        "label":    "Outlook.com / Hotmail / Live",
        "host":     "smtp.office365.com",
        "port":     587,
        "security": "starttls",
        "note":     (
            "Works with Outlook.com, Hotmail, Live, and personal Microsoft accounts. "
            "Use your full email address as the username."
        ),
    },
    "microsoft365": {
        "label":    "Microsoft 365 (work/school)",
        "host":     "smtp.office365.com",
        "port":     587,
        "security": "starttls",
        "note":     (
            "For work or school Microsoft 365 accounts. "
            "Your IT admin may need to enable SMTP AUTH for your account in the Microsoft 365 admin center."
        ),
    },
    "custom": {
        "label":    "Custom / Exchange / Other",
        "host":     "",
        "port":     587,
        "security": "starttls",
        "note":     (
            "Enter your mail server details manually. "
            "For on-premises Exchange, contact your IT administrator for the SMTP relay hostname and port."
        ),
    },
}


# ---------------------------------------------------------------------------
# Core send helper
# ---------------------------------------------------------------------------

def _build_message(
    *,
    from_address: str,
    to_address:   str,
    subject:      str,
    body_html:    str,
    body_text:    str,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_address
    msg["To"]      = to_address
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    return msg


def send_email(
    *,
    host:         str,
    port:         int,
    username:     str,
    password:     str,
    security:     str,   # "starttls" | "ssl" | "none"
    from_address: str,
    to_address:   str,
    subject:      str,
    body_html:    str,
    body_text:    str,
) -> tuple[bool, str]:
    """
    Send one email synchronously. Returns (success, error_message).
    Caller is responsible for running this in a thread if needed.
    """
    try:
        msg = _build_message(
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
        )

        if security == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
                if username and password:
                    server.login(username, password)
                server.sendmail(from_address, [to_address], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                if security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if username and password:
                    server.login(username, password)
                server.sendmail(from_address, [to_address], msg.as_string())

        log.info("email: sent '%s' to %s", subject, to_address)
        return True, ""

    except smtplib.SMTPAuthenticationError:
        msg = "Authentication failed — check your username and password (or App Password)."
        log.warning("email: auth error sending to %s", to_address)
        return False, msg
    except smtplib.SMTPException as exc:
        log.warning("email: SMTP error: %s", exc)
        return False, str(exc)
    except OSError as exc:
        msg = f"Could not connect to {host}:{port} — {exc}"
        log.warning("email: connection error: %s", exc)
        return False, msg


def send_email_async(*, db, subject: str, body_html: str, body_text: str) -> None:
    """
    Fire-and-forget email send. Reads SMTP config from the DB settings table.
    Silently does nothing if email is disabled or not configured.
    """
    def _run():
        try:
            if db.get_setting("notif_email_enabled", "0") != "1":
                return
            host     = db.get_setting("notif_email_smtp_host", "")
            port     = int(db.get_setting("notif_email_smtp_port", "587"))
            username = db.get_setting("notif_email_smtp_user", "")
            password = db.get_setting("notif_email_smtp_password", "")
            security = db.get_setting("notif_email_smtp_security", "starttls")
            from_    = db.get_setting("notif_email_from", "")
            to       = db.get_setting("notif_email_to", "")
            if not host or not to:
                return
            send_email(
                host=host, port=port, username=username, password=password,
                security=security, from_address=from_ or username,
                to_address=to, subject=subject,
                body_html=body_html, body_text=body_text,
            )
        except Exception as exc:
            log.warning("email: async send error: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Notification helpers (called from app logic)
# ---------------------------------------------------------------------------

_STYLE = (
    "font-family:sans-serif;max-width:480px;margin:0 auto;background:#f9f9f9;"
    "border-radius:8px;overflow:hidden;"
)
_HDR = (
    "<div style='background:#1a1a3e;padding:20px 24px;'>"
    "<span style='color:#e84567;font-size:1.3rem;font-weight:700;'>🍺 SmartKegerator</span>"
    "</div>"
)
_BODY_OPEN  = "<div style='padding:24px;'>"
_BODY_CLOSE = "</div>"
_FOOTER = (
    "<div style='background:#eee;padding:10px 24px;font-size:.75rem;color:#888;'>"
    "You are receiving this because notifications are enabled in your SmartKegerator settings."
    "</div>"
)


def _wrap(content: str) -> str:
    return f"<div style='{_STYLE}'>{_HDR}{_BODY_OPEN}{content}{_BODY_CLOSE}{_FOOTER}</div>"


def notify_pour(*, db, user_name: str, beer_name: str, ounces: float, price: float) -> None:
    if db.get_setting("notif_email_on_pour", "0") != "1":
        return
    price_str = f" (${price:.2f})" if price > 0 else ""
    subject   = f"🍺 Pour: {user_name} — {ounces:.1f} oz of {beer_name}"
    html = _wrap(
        f"<h2 style='margin-top:0;color:#1a1a3e;'>Pour Recorded</h2>"
        f"<p><strong>{user_name}</strong> just poured <strong>{ounces:.1f} oz</strong> "
        f"of <strong>{beer_name}</strong>{price_str}.</p>"
    )
    text = f"Pour: {user_name} poured {ounces:.1f} oz of {beer_name}{price_str}."
    send_email_async(db=db, subject=subject, body_html=html, body_text=text)


def notify_keg_low(*, db, beer_name: str, pct_remaining: float) -> None:
    threshold = int(db.get_setting("notif_email_keg_low_pct", "15"))
    if db.get_setting("notif_email_on_keg_low", "0") != "1":
        return
    if pct_remaining > threshold:
        return
    subject = f"⚠️ Keg Low: {beer_name} — {pct_remaining:.0f}% remaining"
    html = _wrap(
        f"<h2 style='margin-top:0;color:#e67e22;'>Keg Running Low</h2>"
        f"<p><strong>{beer_name}</strong> is at <strong>{pct_remaining:.0f}%</strong> — "
        f"time to order a replacement.</p>"
    )
    text = f"Keg low: {beer_name} is at {pct_remaining:.0f}% remaining."
    send_email_async(db=db, subject=subject, body_html=html, body_text=text)


def notify_keg_empty(*, db, beer_name: str) -> None:
    if db.get_setting("notif_email_on_keg_empty", "0") != "1":
        return
    subject = f"🪣 Keg Empty: {beer_name}"
    html = _wrap(
        f"<h2 style='margin-top:0;color:#e84567;'>Keg Empty</h2>"
        f"<p><strong>{beer_name}</strong> has been emptied.</p>"
    )
    text = f"Keg empty: {beer_name} is now empty."
    send_email_async(db=db, subject=subject, body_html=html, body_text=text)


def notify_temp_alert(*, db, temp_f: float, threshold_f: float) -> None:
    if db.get_setting("notif_email_on_temp_alert", "0") != "1":
        return
    subject = f"🌡️ Temperature Alert — {temp_f:.1f}°F"
    html = _wrap(
        f"<h2 style='margin-top:0;color:#e84567;'>Temperature Alert</h2>"
        f"<p>Kegerator temperature is <strong>{temp_f:.1f}°F</strong>, "
        f"above your alert threshold of <strong>{threshold_f:.0f}°F</strong>.</p>"
    )
    text = f"Temp alert: {temp_f:.1f}°F (threshold {threshold_f:.0f}°F)."
    send_email_async(db=db, subject=subject, body_html=html, body_text=text)


def notify_new_user(*, db, user_name: str) -> None:
    if db.get_setting("notif_email_on_new_user", "0") != "1":
        return
    subject = f"👤 New User Registered: {user_name}"
    html = _wrap(
        f"<h2 style='margin-top:0;color:#1a1a3e;'>New User Registered</h2>"
        f"<p><strong>{user_name}</strong> has registered on the SmartKegerator.</p>"
    )
    text = f"New user registered: {user_name}."
    send_email_async(db=db, subject=subject, body_html=html, body_text=text)
