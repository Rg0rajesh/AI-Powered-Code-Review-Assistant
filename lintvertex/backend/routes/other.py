"""
LintVertex - Profile, Feedback, and Admin Routes
"""
import base64
from flask import Blueprint, request, jsonify
from utils.security import require_auth, verify_password, validate_email, validate_image
import services.supabase_client as db

profile_bp = Blueprint("profile", __name__)
feedback_bp = Blueprint("feedback", __name__)

# ─── Profile Routes ───────────────────────────────────────────────────────────

@profile_bp.route("/api/profile/update", methods=["PUT"])
@require_auth
def update_profile():
    user_id = request.user["user_id"]

    if request.content_type and "multipart/form-data" in request.content_type:
        data = request.form.to_dict()
        profile_image_file = request.files.get("profile_image")
    else:
        data = request.get_json() or {}
        profile_image_file = None

    # Require password verification
    current_password = data.get("current_password", "")
    if not current_password:
        return jsonify({"error": "Current password required to update profile"}), 400

    user = db.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    from utils.security import verify_password as vp
    if not vp(current_password, user["password_hash"]):
        return jsonify({"error": "Incorrect password"}), 401

    updates = {}

    if "username" in data and data["username"].strip():
        updates["username"] = data["username"].strip()

    if "email" in data and data["email"].strip():
        new_email = data["email"].strip().lower()
        if not validate_email(new_email):
            return jsonify({"error": "Invalid email"}), 400
        updates["email"] = new_email

    if "address" in data and data["address"].strip():
        updates["address"] = data["address"].strip()

    if profile_image_file and profile_image_file.filename:
        valid_img, img_err = validate_image(profile_image_file)
        if not valid_img:
            return jsonify({"error": img_err}), 400
        img_bytes = profile_image_file.read()
        updates["profile_image"] = f"data:{profile_image_file.content_type};base64,{base64.b64encode(img_bytes).decode()}"

    if not updates:
        return jsonify({"error": "No updates provided"}), 400

    db.update_user(user_id, updates)
    db.log_activity(user_id, "profile_updated")

    return jsonify({"message": "Profile updated successfully", "updates": list(updates.keys())}), 200


@profile_bp.route("/api/profile/stats", methods=["GET"])
@require_auth
def profile_stats():
    user_id = request.user["user_id"]

    analyses = db.get_user_analyses(user_id, limit=100)
    analysis_list = analyses.data or []

    rooms = db.get_user_rooms(user_id)
    room_list = rooms.data or []

    grades = [a.get("ml_prediction", "") for a in analysis_list if a.get("ml_prediction")]
    languages = {}
    for a in analysis_list:
        lang = a.get("language_detected", "unknown")
        languages[lang] = languages.get(lang, 0) + 1

    avg_score = 0
    if analysis_list:
        grade_map = {"A": 90, "B": 75, "C": 60, "D": 45, "F": 25}
        avg_score = round(sum(grade_map.get(g, 50) for g in grades) / len(grades)) if grades else 0

    return jsonify({
        "total_analyses": len(analysis_list),
        "joined_rooms": len(room_list),
        "avg_quality_score": avg_score,
        "language_breakdown": languages,
        "recent_grades": grades[:10],
    }), 200


# ─── Feedback Routes ──────────────────────────────────────────────────────────

@feedback_bp.route("/api/feedback/submit", methods=["POST"])
@require_auth
def submit_feedback():
    data = request.get_json() or {}
    rating = data.get("rating")
    feedback_text = data.get("feedback_text", "").strip()

    if rating is None or not isinstance(rating, (int, float)):
        return jsonify({"error": "Rating (1-5) is required"}), 400

    rating = int(rating)
    if rating < 1 or rating > 5:
        return jsonify({"error": "Rating must be between 1 and 5"}), 400

    if not feedback_text:
        return jsonify({"error": "Feedback text is required"}), 400

    user_id = request.user["user_id"]
    db.save_feedback({
        "user_id": user_id,
        "rating": rating,
        "feedback_text": feedback_text,
    })
    db.log_activity(user_id, "feedback_submitted")

    return jsonify({"message": "Thank you for your feedback!"}), 201
