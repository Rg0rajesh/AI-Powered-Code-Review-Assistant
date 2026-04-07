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

def _send_via_brevo(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send via Brevo API (300 emails/day free)."""
    if not Config.BREVO_API_KEY:
        return False
    try:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": Config.BREVO_API_KEY,
            "content-type": "application/json"
        }
        payload = {
            "sender": {"name": Config.BREVO_FROM_NAME, "email": Config.BREVO_FROM_EMAIL},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_body
        }
        if text_body:
            payload["textContent"] = text_body
        
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 201:
            logger.info(f"Email sent via Brevo to {to_email}")
            return True
        logger.error(f"Brevo error ({resp.status_code}): {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Brevo exception: {e}")
        return False


def _send_via_sendgrid(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send via SendGrid API (100 emails/day free)."""
    if not Config.SENDGRID_API_KEY:
        return False
    try:
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            "Authorization": f"Bearer {Config.SENDGRID_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "personalizations": [{"to": [{"email": to_email}], "subject": subject}],
            "from": {"email": Config.SENDGRID_FROM_EMAIL, "name": Config.SENDGRID_FROM_NAME},
            "content": [{"type": "text/html", "value": html_body}]
        }
        if text_body:
            payload["content"].append({"type": "text/plain", "value": text_body})
        
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 202:
            logger.info(f"Email sent via SendGrid to {to_email}")
            return True
        logger.error(f"SendGrid error ({resp.status_code}): {resp.text}")
        return False
    except Exception as e:
        logger.error(f"SendGrid exception: {e}")
        return False


def _send_via_emailjs(to_email: str, subject: str, html_body: str, template_id: str = None, params: dict = None) -> bool:
    """Send via EmailJS (template-based, user emails like OTP/welcome)."""
    if not (Config.EMAILJS_SERVICE_ID and Config.EMAILJS_PUBLIC_KEY and template_id):
        return False
    try:
        url = "https://api.emailjs.com/api/v1.0/email/send"
        payload = {
            "service_id": Config.EMAILJS_SERVICE_ID,
            "template_id": template_id,
            "user_id": Config.EMAILJS_PUBLIC_KEY,
            "template_params": params or {"to_email": to_email, "to_name": to_email.split('@')[0], "subject": subject}
        }
        if Config.EMAILJS_PRIVATE_KEY:
            payload["accessToken"] = Config.EMAILJS_PRIVATE_KEY
        
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info(f"Email sent via EmailJS (user) to {to_email}")
            return True
        logger.error(f"EmailJS error ({resp.status_code}): {resp.text}")
        return False
    except Exception as e:
        logger.error(f"EmailJS exception: {e}")
        return False


def _send_via_admin_emailjs(to_email: str, subject: str, html_body: str, template_id: str = None, params: dict = None) -> bool:
    """Send via Admin EmailJS (separate account for admin broadcasts)."""
    if not (Config.ADMIN_EMAILJS_SERVICE_ID and Config.ADMIN_EMAILJS_PUBLIC_KEY and template_id):
        return False
    try:
        url = "https://api.emailjs.com/api/v1.0/email/send"
        payload = {
            "service_id": Config.ADMIN_EMAILJS_SERVICE_ID,
            "template_id": template_id,
            "user_id": Config.ADMIN_EMAILJS_PUBLIC_KEY,
            "template_params": params or {"to_email": to_email, "to_name": to_email.split('@')[0], "subject": subject}
        }
        if Config.ADMIN_EMAILJS_PRIVATE_KEY:
            payload["accessToken"] = Config.ADMIN_EMAILJS_PRIVATE_KEY
        
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info(f"Email sent via EmailJS (admin) to {to_email}")
            return True
        logger.error(f"Admin EmailJS error ({resp.status_code}): {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Admin EmailJS exception: {e}")
        return False


def send_email(to_email: str, subject: str, html_body: str, text_body: str = "", template_id: str = None, params: dict = None) -> bool:
    """Send email with provider fallback (Brevo → SendGrid → EmailJS). SMTP disabled on Render."""
    provider = (Config.EMAIL_PROVIDER or "brevo").strip().lower()
    
    # Priority list based on configured provider
    provider_order = []
    if provider == "sendgrid":
        provider_order = ["sendgrid", "brevo", "emailjs"]
    elif provider == "emailjs":
        provider_order = ["emailjs", "brevo", "sendgrid"]
    else:  # Default to Brevo
        provider_order = ["brevo", "sendgrid", "emailjs"]
    
    # Try each provider in order
    for prov in provider_order:
        if prov == "brevo" and _send_via_brevo(to_email, subject, html_body, text_body):
            return True
        elif prov == "sendgrid" and _send_via_sendgrid(to_email, subject, html_body, text_body):
            return True
        elif prov == "emailjs" and _send_via_emailjs(to_email, subject, html_body, template_id, params):
            return True
    
    logger.error(f"All email providers failed for {to_email}. Configure BREVO_API_KEY, SENDGRID_API_KEY, or EMAILJS credentials.")
    return False


def send_admin_email(to_email: str, subject: str, html_body: str, template_id: str = None, params: dict = None) -> bool:
    """Send admin broadcast emails via Admin EmailJS account only."""
    # Only use admin EmailJS for broadcasts
    if not (Config.ADMIN_EMAILJS_SERVICE_ID and Config.ADMIN_EMAILJS_PUBLIC_KEY):
        logger.error("Admin EmailJS not configured. Configure ADMIN_EMAILJS_SERVICE_ID and ADMIN_EMAILJS_PUBLIC_KEY.")
        return False
    
    if not template_id:
        logger.error("Admin email requires template_id to be set.")
        return False
    
    return _send_via_admin_emailjs(to_email, subject, html_body, template_id, params)

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
    """Send a feature announcement via Admin EmailJS."""
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
    
    params = {
        "to_email": to_email,
        "to_name": username,
        "subject": subject,
        "headline": headline,
        "body_html": body_html,
        "features": str(features) if features else "",
        "cta_text": cta_text,
        "cta_url": cta_url
    }
    return send_admin_email(to_email, subject, _base_template(html), template_id=Config.ADMIN_EMAILJS_FEATURE_TEMPLATE_ID, params=params)

def send_custom_email(to_email: str, username: str, subject: str, headline: str, body_html: str, tag_label: str = "", cta_text: str = "", cta_url: str = "", **kwargs) -> bool:
    """Send a custom email via Admin EmailJS."""
    html = ""
    if tag_label:
        html += f"<div class='tag tag-orange'>{tag_label}</div>"
    
    html += f"<h2>{headline}</h2><p>Hi {username},</p>{body_html}"
    
    if cta_url and cta_text:
        html += f"<p><a href='{cta_url}' class='btn'>{cta_text}</a></p>"
    
    params = {
        "to_email": to_email,
        "to_name": username,
        "subject": subject,
        "headline": headline,
        "body_html": body_html,
        "tag_label": tag_label,
        "cta_text": cta_text,
        "cta_url": cta_url
    }
    return send_admin_email(to_email, subject, _base_template(html), template_id=Config.ADMIN_EMAILJS_CUSTOM_TEMPLATE_ID, params=params)

def send_feedback_reply(to_email: str, username: str, original_feedback: str, reply_text: str):
    html = f"<h2>Feedback Response</h2><p>Hello {username},</p><p>We have a response to your feedback:</p><p style='font-style:italic;color:#666'>\"{original_feedback}\"</p><hr><p>{reply_text}</p>"
    return send_email(to_email, "Re: Your feedback - LintVertex", _base_template(html))

def send_policy_notice(to_email: str, username: str, subject: str, headline: str, body_html: str, effective_date: str = "", tag_label: str = "Policy Update", **kwargs) -> bool:
    """Send a policy notice via Admin EmailJS."""
    html = f"""
    <div class="tag tag-orange">{tag_label}</div>
    <h2>{headline}</h2>
    <p>Hello {username},</p>
    {body_html}
    {f"<p><strong>Effective Date:</strong> {effective_date}</p>" if effective_date else ""}
    <p style='margin-top:20px'>Thank you for using LintVertex.<br>The LintVertex Team</p>
    """
    
    params = {
        "to_email": to_email,
        "to_name": username,
        "subject": subject,
        "headline": headline,
        "body_html": body_html,
        "effective_date": effective_date,
        "tag_label": tag_label
    }
    return send_admin_email(to_email, subject, _base_template(html), template_id=Config.ADMIN_EMAILJS_POLICY_TEMPLATE_ID, params=params)
