"""
LintVertex - Configuration Module
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-prod")
    DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    # Gemini
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Ollama
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama")

    # JWT - regular users (24h)
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret-change-in-prod")
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

    # JWT - admin tokens (SEPARATE secret, short 2h)
    ADMIN_JWT_SECRET = os.getenv("ADMIN_JWT_SECRET", "admin-jwt-MUST-be-different-key")
    ADMIN_TOKEN_EXPIRY_HOURS = int(os.getenv("ADMIN_TOKEN_EXPIRY_HOURS", "2"))

    # File Upload
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2"))
    ALLOWED_IMAGE_TYPES = os.getenv("ALLOWED_IMAGE_TYPES", "image/jpeg,image/png").split(",")

    # Admin
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@lintvertex.com")

    # SMTP Email
    SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT      = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER      = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM      = os.getenv("SMTP_FROM", "noreply@lintvertex.com")
    SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "LintVertex")
    SMTP_USE_SSL   = os.getenv("SMTP_USE_SSL", "True").lower() == "true"
    SMTP_USE_TLS   = os.getenv("SMTP_USE_TLS", "False").lower() == "true"
    EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "auto") # 'auto', 'smtp', or 'emailjs'

    # App public URL (used in email links)
    APP_URL = os.getenv("APP_URL", "http://localhost:5000")


    # EmailJS (replaces SMTP)
    EMAILJS_SERVICE_ID          = os.getenv("EMAILJS_SERVICE_ID", "")
    EMAILJS_PUBLIC_KEY          = os.getenv("EMAILJS_PUBLIC_KEY", "")
    EMAILJS_PRIVATE_KEY         = os.getenv("EMAILJS_PRIVATE_KEY", "")
    EMAILJS_OTP_TEMPLATE_ID     = os.getenv("EMAILJS_OTP_TEMPLATE_ID", "template_otp")
    EMAILJS_CHANGED_TEMPLATE_ID = os.getenv("EMAILJS_CHANGED_TEMPLATE_ID", "template_pwd_changed")
    EMAILJS_WELCOME_TEMPLATE_ID = os.getenv("EMAILJS_WELCOME_TEMPLATE_ID", "template_welcome")