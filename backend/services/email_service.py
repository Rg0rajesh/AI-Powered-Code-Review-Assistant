"""
LintVertex - Email Service
Supports EmailJS (template-based) and SMTP (fallback) for sending emails.
Now properly located in services/ to match the backend architecture.
"""
import smtplib
import logging
import requests
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from config import Config

logger = logging.getLogger(__name__)

def _base_template(content: str) -> str:
    """Standard HTML wrapper for SMTP emails."""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; color: #333; background: #f9f9f9; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; border-top: 4px solid #556B2F; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        h2 {{ color: #556B2F; margin-top: 0; }}
        .otp-box {{ background: #F5F5DC; padding: 20px; border-radius: 8px; text-align: center; border: 2px dashed #556B2F; margin: 20px 0; }}
        .otp-code {{ font-size: 2.5rem; font-weight: 800; letter-spacing: 0.3em; color: #556B2F; }}
        .footer {{ margin-top: 30px; font-size: 0.8rem; color: #888; text-align: center; border-top: 1px solid #eee; padding-top: 20px; }}
        .btn {{ display: inline-block; background: #556B2F; color: white !important; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; }}
        .tag {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; }}
        .tag-orange {{ background: #FFF3E0; color: #E67E22; }}
    </style>
</head>
<body>
    <div class="container">
        {content}
        <div class="footer">
            &copy; {datetime.datetime.now().year} LintVertex &nbsp;·&nbsp; AI Code Analysis
        </div>
    </div>
</body>
</html>
"""

def send_email(to_email: str, subject: str, html_body: str, text_body: str = "", template_id: str = None, params: dict = None) -> bool:
    """Generic send function with EmailJS priority and SMTP fallback."""
    # ── Try EmailJS ───────────────────────────────────────────
    if Config.EMAILJS_SERVICE_ID and Config.EMAILJS_PUBLIC_KEY and template_id:
        try:
            url = "https://api.emailjs.com/api/v1.0/email/send"
            payload = {
                "service_id": Config.EMAILJS_SERVICE_ID,
                "template_id": template_id,
                "user_id": Config.EMAILJS_PUBLIC_KEY,
                "template_params": params or {
                    "to_email": to_email,
                    "to_name": to_email.split('@')[0],
                    "subject": subject,
                    "message_html": html_body
                }
            }
            if Config.EMAILJS_PRIVATE_KEY:
                payload["accessToken"] = Config.EMAILJS_PRIVATE_KEY
                
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Email sent via EmailJS to {to_email}")
                return True
            logger.error(f"EmailJS error ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"EmailJS exception: {e}")

    # ── Fallback: SMTP ────────────────────────────────────────
    if not Config.SMTP_USER or not Config.SMTP_PASSWORD:
        logger.warning(f"SMTP not configured. Logged to console: {to_email} | {subject}")
        return False
        
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((Config.SMTP_FROM_NAME, Config.SMTP_FROM or Config.SMTP_USER))
        msg["To"] = to_email
        if text_body: msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        
        if Config.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.sendmail(Config.SMTP_FROM or Config.SMTP_USER, to_email, msg.as_string())
        else:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                if Config.SMTP_USE_TLS: server.starttls()
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.sendmail(Config.SMTP_FROM or Config.SMTP_USER, to_email, msg.as_string())
        logger.info(f"Email sent via SMTP to {to_email}")
        return True
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        return False

def send_otp_email(to_email: str, username: str, otp: str, expiry_minutes: int = 5) -> bool:
    html = f"""
    <h2>Verification Code</h2>
    <p>Hi <strong>{username}</strong>,</p>
    <p>Your verification code for LintVertex is:</p>
    <div class="otp-box"><span class="otp-code">{' '.join(list(otp))}</span></div>
    <p>This code expires in {expiry_minutes} minutes.</p>"""
    
    return send_email(
        to_email, f"LintVertex OTP: {otp}", _base_template(html),
        template_id=Config.EMAILJS_OTP_TEMPLATE_ID,
        params={
            "to_email": to_email, "to_name": username, "otp_code": otp, 
            "expiry_minutes": expiry_minutes, "app_url": Config.APP_URL
        }
    )

def send_password_changed_email(to_email: str, username: str) -> bool:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""
    <h2>Password Changed</h2>
    <p>Hi {username}, your password was updated on {now}.</p>
    <p>If this wasn't you, contact support immediately.</p>"""
    
    return send_email(
        to_email, "Password Changed - LintVertex", _base_template(html),
        template_id=Config.EMAILJS_CHANGED_TEMPLATE_ID,
        params={
            "to_email": to_email, "to_name": username, "changed_at": now,
            "login_url": f"{Config.APP_URL}/login.html"
        }
    )

def send_welcome_email(to_email: str, username: str) -> bool:
    html = f"<h2>Welcome to LintVertex!</h2><p>Hi {username}, your account is ready.</p>"
    return send_email(
        to_email, f"Welcome {username}", _base_template(html),
        template_id=Config.EMAILJS_WELCOME_TEMPLATE_ID,
        params={"to_email": to_email, "to_name": username, "dashboard_url": f"{Config.APP_URL}/dashboard.html"}
    )

def send_password_otp_email(to_email: str, username: str, otp: str):
    return send_otp_email(to_email, username, otp)

def send_feature_announcement(to_email: str, username: str, subject: str, headline: str, body_html: str, features: list = None, cta_text: str = "Explore Now", cta_url: str = "", **kwargs) -> bool:
    """Send a feature announcement email with optional features list and CTA."""
    html = f"<h2>🚀 {headline}</h2><p>Hi {username},</p>{body_html}"
    
    # Add features list if provided
    if features:
        html += "<ul style='margin: 20px 0'>"
        for feature in features:
            if isinstance(feature, dict):
                icon = feature.get('icon', '✨')
                title = feature.get('title', '')
                desc = feature.get('desc', '')
                html += f"<li>{icon} <strong>{title}</strong> - {desc}</li>"
        html += "</ul>"
    
    # Add CTA button if provided
    if cta_url and cta_text:
        html += f"<p><a href='{cta_url}' class='btn'>{cta_text}</a></p>"
    
    return send_email(to_email, subject, _base_template(html))

def send_custom_email(to_email: str, username: str, subject: str, headline: str, body_html: str, tag_label: str = "", cta_text: str = "", cta_url: str = "", **kwargs) -> bool:
    """Send a custom email with optional tag and CTA."""
    html = ""
    if tag_label:
        html += f"<div class='tag tag-orange'>{tag_label}</div>"
    
    html += f"<h2>{headline}</h2><p>Hi {username},</p>{body_html}"
    
    if cta_url and cta_text:
        html += f"<p><a href='{cta_url}' class='btn'>{cta_text}</a></p>"
    
    return send_email(to_email, subject, _base_template(html))

def send_feedback_reply(to_email: str, username: str, original_feedback: str, reply_text: str):
    html = f"<h2>Feedback Response</h2><p>Hello {username},</p><p>We have a response to your feedback:</p><p style='font-style:italic;color:#666'>\"{original_feedback}\"</p><hr><p>{reply_text}</p>"
    return send_email(to_email, "Re: Your feedback - LintVertex", _base_template(html))

def send_policy_notice(to_email: str, username: str, subject: str, headline: str, body_html: str, effective_date: str = "", tag_label: str = "Policy Update", **kwargs) -> bool:
    """Send a formal policy notice (like terms changes) to users."""
    html = f"""
    <div class="tag tag-orange">{tag_label}</div>
    <h2>{headline}</h2>
    <p>Hello {username},</p>
    {body_html}
    {f"<p><strong>Effective Date:</strong> {effective_date}</p>" if effective_date else ""}
    <p style='margin-top:20px'>Thank you for using LintVertex.<br>The LintVertex Team</p>
    """
    return send_email(to_email, subject, _base_template(html))
