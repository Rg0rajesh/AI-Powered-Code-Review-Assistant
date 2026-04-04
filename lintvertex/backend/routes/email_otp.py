"""
LintVertex - Email OTP Routes
Used for authenticated password changes in profile.html
"""
from flask import Blueprint, request, jsonify
from utils.security import require_auth, verify_password, hash_password, validate_password
import services.supabase_client as db
from services.otp_service import generate_otp, verify_otp, invalidate_otp
from services.email_service import send_password_otp_email as send_otp_email

email_otp_bp = Blueprint("email_otp", __name__)

@email_otp_bp.route("/api/email/otp/request", methods=["POST"])
@require_auth
def request_otp():
    """Step 1: Verify current password and send OTP"""
    data = request.get_json() or {}
    current_password = data.get("current_password", "")
    
    if not current_password:
        return jsonify({"error": "Current password required"}), 400
        
    user_id = request.user["user_id"]
    email = request.user["email"]
    
    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    if not verify_password(current_password, user["password_hash"]):
        return jsonify({"error": "Incorrect current password"}), 401
        
    try:
        otp = generate_otp(email, user_id=user_id, ip_address=request.remote_addr)
        sent = send_otp_email(email, user["username"], otp)
        
        # Email hint for frontend
        email_parts = email.split("@")
        hint = email_parts[0][:2] + "***@" + email_parts[1]
        
        return jsonify({
            "message": "OTP sent successfully",
            "email_hint": hint,
            "expires_in_seconds": 300
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@email_otp_bp.route("/api/email/otp/verify", methods=["POST"])
@require_auth
def verify_otp_and_reset():
    """Step 2: Verify OTP and update password in one go"""
    data = request.get_json() or {}
    otp_code = data.get("otp_code", "")
    new_password = data.get("new_password", "")
    confirm_new_password = data.get("confirm_new_password", "")
    
    if not otp_code or not new_password:
        return jsonify({"error": "OTP and new password required"}), 400
        
    if new_password != confirm_new_password:
        return jsonify({"error": "Passwords do not match"}), 400
        
    valid, err = validate_password(new_password)
    if not valid:
        return jsonify({"error": err}), 400
        
    user_id = request.user["user_id"]
    email = request.user["email"]
    
    # 1. Verify OTP
    try:
        from services.otp_service import OTPExpired, OTPInvalid, OTPAlreadyUsed
        verify_otp(email, otp_code)
    except OTPExpired:
        return jsonify({"error": "OTP has expired"}), 400
    except OTPAlreadyUsed:
        return jsonify({"error": "OTP already used"}), 400
    except OTPInvalid as e:
        return jsonify({"error": f"Invalid OTP. {e.attempts_left} attempts remaining"}), 400
    except Exception as e:
        return jsonify({"error": f"Verification failed: {str(e)}"}), 500
        
    # 2. Update password
    try:
        new_hash = hash_password(new_password)
        db.update_user(user_id, {"password_hash": new_hash})
        invalidate_otp(email)
        db.log_activity(user_id, "password_changed_via_profile")
        
        return jsonify({"message": "Password updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Update failed: {str(e)}"}), 500
