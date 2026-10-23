import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

from ..core.config import settings

logger = logging.getLogger(__name__)


def _get_base_url():
    """Get base URL - read from DB via subprocess since psycopg2 isn't available."""
    import subprocess
    try:
        psql = settings.get_psql_path()
    except FileNotFoundError:
        return settings.magic_link_base_url
    try:
        result = subprocess.run(
            [psql, "-h", "/tmp", "-p", "5433", "-d", "nanocortex",
             "-t", "-A", "-c", "SELECT value FROM app_settings WHERE key = 'magic_link_base_url'"],
            capture_output=True, text=True, timeout=3
        )
        val = result.stdout.strip()
        if val:
            return val
    except Exception:
        pass
    return settings.magic_link_base_url


def _send_email(to_email: str, subject: str, html: str, text: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, e)
        return False


def _wrap_html(body_content: str) -> str:
    return f"""\
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; padding: 40px;">
  <div style="max-width: 480px; margin: 0 auto; background: #16213e; border-radius: 12px; padding: 32px; border: 1px solid #0f3460;">
    <h2 style="color: #e94560; margin: 0 0 8px 0;">NanoCortex</h2>
    <p style="color: #a0a0b0; margin: 0 0 24px 0; font-size: 14px;">AI Knowledge Agent</p>
    {body_content}
  </div>
</body>
</html>"""


def send_magic_link_email(to_email: str, token: str) -> bool:
    link = f"{_get_base_url()}/#/magic-link?token={token}"

    body = f"""\
    <p style="color: #e0e0e0; font-size: 16px;">Click the button below to sign in:</p>
    <a href="{link}" style="display: inline-block; background: #e94560; color: white; text-decoration: none; padding: 12px 32px; border-radius: 6px; font-weight: 600; margin: 16px 0;">
      Sign In
    </a>
    <p style="color: #808090; font-size: 13px; margin-top: 24px;">
      This link expires in {settings.magic_link_expire_minutes} minutes.<br/>
      If you didn't request this, ignore this email.
    </p>"""

    html = _wrap_html(body)
    text = f"Sign in to NanoCortex:\n\n{link}\n\nExpires in {settings.magic_link_expire_minutes} minutes."
    return _send_email(to_email, "Sign in to NanoCortex", html, text)


def send_review_submitted_email(to_emails: List[str], asset_filename: str, submitter_name: str) -> None:
    body = f"""\
    <p style="color: #e0e0e0; font-size: 16px;">A new asset has been submitted for review:</p>
    <div style="background: #0f3460; border-radius: 6px; padding: 16px; margin: 16px 0;">
      <p style="color: #e94560; font-weight: 600; margin: 0 0 8px 0;">{asset_filename}</p>
      <p style="color: #a0a0b0; margin: 0; font-size: 13px;">Submitted by {submitter_name}</p>
    </div>
    <a href="{_get_base_url()}/#/review" style="display: inline-block; background: #e94560; color: white; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; margin: 8px 0;">
      Open Review Queue
    </a>"""

    html = _wrap_html(body)
    text = f"New asset submitted for review: {asset_filename}\nSubmitted by: {submitter_name}\n\nOpen: {_get_base_url()}/#/review"

    for email in to_emails:
        _send_email(email, f"Review needed: {asset_filename}", html, text)


def send_review_claimed_email(to_email: str, asset_filename: str, reviewer_name: str) -> None:
    body = f"""\
    <p style="color: #e0e0e0; font-size: 16px;">Your asset is now being reviewed:</p>
    <div style="background: #0f3460; border-radius: 6px; padding: 16px; margin: 16px 0;">
      <p style="color: #e94560; font-weight: 600; margin: 0 0 8px 0;">{asset_filename}</p>
      <p style="color: #a0a0b0; margin: 0; font-size: 13px;">Under review by {reviewer_name}</p>
    </div>
    <a href="{_get_base_url()}/#/review" style="display: inline-block; background: #e94560; color: white; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; margin: 8px 0;">
      View in Review Queue
    </a>"""

    html = _wrap_html(body)
    text = f"Your asset '{asset_filename}' is now under review by {reviewer_name}.\n\nView: {_get_base_url()}/#/review"
    _send_email(to_email, f"Review started: {asset_filename}", html, text)


def send_review_approved_email(to_emails: List[str], asset_filename: str, reviewer_name: str) -> None:
    body = f"""\
    <p style="color: #e0e0e0; font-size: 16px;">An asset has been approved:</p>
    <div style="background: #0f3460; border-radius: 6px; padding: 16px; margin: 16px 0;">
      <p style="color: #4ecdc4; font-weight: 600; margin: 0 0 8px 0;">{asset_filename}</p>
      <p style="color: #a0a0b0; margin: 0; font-size: 13px;">Approved by {reviewer_name}</p>
    </div>
    <a href="{_get_base_url()}/#/review" style="display: inline-block; background: #4ecdc4; color: #0f172a; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; margin: 8px 0;">
      View in Review Queue
    </a>"""

    html = _wrap_html(body)
    text = f"Asset '{asset_filename}' has been approved by {reviewer_name}.\n\nView: {_get_base_url()}/#/review"

    for email in to_emails:
        _send_email(email, f"Approved: {asset_filename}", html, text)


def send_review_rejected_email(to_emails: List[str], asset_filename: str, reviewer_name: str, reason: str) -> None:
    body = f"""\
    <p style="color: #e0e0e0; font-size: 16px;">An asset has been rejected:</p>
    <div style="background: #0f3460; border-radius: 6px; padding: 16px; margin: 16px 0;">
      <p style="color: #ff6b6b; font-weight: 600; margin: 0 0 8px 0;">{asset_filename}</p>
      <p style="color: #a0a0b0; margin: 0; font-size: 13px;">Rejected by {reviewer_name}</p>
      <p style="color: #e0e0e0; margin: 12px 0 0 0; font-size: 14px; border-top: 1px solid #1a1a2e; padding-top: 12px;">
        <strong>Reason:</strong> {reason or 'No reason provided'}
      </p>
    </div>
    <a href="{_get_base_url()}/#/review" style="display: inline-block; background: #e94560; color: white; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; margin: 8px 0;">
      View in Review Queue
    </a>"""

    html = _wrap_html(body)
    text = f"Asset '{asset_filename}' has been rejected by {reviewer_name}.\nReason: {reason or 'No reason provided'}\n\nView: {_get_base_url()}/#/review"

    for email in to_emails:
        _send_email(email, f"Rejected: {asset_filename}", html, text)


def send_claim_action_email(to_emails: List[str], asset_filename: str, actor_name: str, action: str) -> None:
    action_color = "#e94560" if action == "claimed" else "#a0a0b0" if action == "released" else "#4ecdc4"

    body = f"""\
    <p style="color: #e0e0e0; font-size: 16px;">Review assignment update:</p>
    <div style="background: #0f3460; border-radius: 6px; padding: 16px; margin: 16px 0;">
      <p style="color: {action_color}; font-weight: 600; margin: 0 0 8px 0;">{asset_filename}</p>
      <p style="color: #a0a0b0; margin: 0; font-size: 13px;">{actor_name} {action} this asset</p>
    </div>
    <a href="{_get_base_url()}/#/review" style="display: inline-block; background: #e94560; color: white; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: 600; margin: 8px 0;">
      Open Review Queue
    </a>"""

    html = _wrap_html(body)
    text = f"Asset '{asset_filename}': {actor_name} {action}.\n\nOpen: {_get_base_url()}/#/review"

    for email in to_emails:
        _send_email(email, f"Review update: {asset_filename} — {action}", html, text)
