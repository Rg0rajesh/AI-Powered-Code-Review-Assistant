"""
LintVertex - Code Analysis Routes
Full pipeline: detect → ML → AI → store → respond
"""
from flask import Blueprint, request, jsonify
from utils.security import require_auth
from services.language_detector import detect_language, get_language_meta
from services.ml_service import extract_code_features, compute_quality_score, detect_syntax_issues
from services.ai_service import run_ai_analysis, parse_ai_sections
import services.supabase_client as db

analysis_bp = Blueprint("analysis", __name__)


@analysis_bp.route("/api/analysis/submit", methods=["POST"])
@require_auth
def submit_analysis():
    """Submit code for full analysis pipeline"""
    data = request.get_json() or {}
    code = data.get("code", "").strip()

    if not code:
        return jsonify({"error": "Code is required"}), 400

    if len(code) > 50000:
        return jsonify({"error": "Code too large (max 50,000 characters)"}), 400

    user_id = request.user["user_id"]

    # ── Step 1: Language Detection ────────────────────────────────────────
    lang_result = detect_language(code)
    language = lang_result["language"]
    lang_meta = get_language_meta(language)

    # ── Step 2: Feature Extraction ────────────────────────────────────────
    features = extract_code_features(code)

    # ── Step 3: Quality Score ─────────────────────────────────────────────
    ml_score = compute_quality_score(features, language)

    # ── Step 4: Syntax Issue Detection ────────────────────────────────────
    syntax_issues = detect_syntax_issues(code, language)

    # ── Step 5: AI Analysis ───────────────────────────────────────────────
    ai_result = run_ai_analysis(code, language, ml_score, syntax_issues)
    ai_sections = parse_ai_sections(ai_result["ai_explanation"])

    # ── Step 6: Store Results ─────────────────────────────────────────────
    record = {
        "user_id": user_id,
        "language_detected": language,
        "source_code": code[:5000],  # Store first 5k chars
        "syntax_errors": len([i for i in syntax_issues if i["severity"] == "error"]),
        "detected_issues": syntax_issues[:20],  # JSON column
        "improvements": ai_sections.get("improvements", ""),
        "ml_prediction": ml_score.get("grade", "?"),
        "confidence": ml_score.get("confidence", 0.0),
    }

    saved = db.save_analysis(record)
    analysis_id = saved.data[0]["id"] if saved.data else None

    db.log_activity(user_id, f"code_analysis:{language}")

    return jsonify({
        "analysis_id": analysis_id,
        "language": {
            "detected": language,
            "display": lang_meta["display"],
            "icon": lang_meta["icon"],
            "confidence": lang_result["confidence"],
        },
        "quality": {
            "score": ml_score["total_score"],
            "grade": ml_score["grade"],
            "breakdown": ml_score["breakdown"],
        },
        "issues": {
            "total": len(syntax_issues),
            "errors": len([i for i in syntax_issues if i["severity"] == "error"]),
            "warnings": len([i for i in syntax_issues if i["severity"] == "warning"]),
            "info": len([i for i in syntax_issues if i["severity"] == "info"]),
            "list": syntax_issues,
        },
        "ai": {
            "provider": ai_result["ai_provider"],
            "sections": ai_sections,
            "full_text": ai_result["ai_explanation"],
        },
        "features": features,
    }), 200


@analysis_bp.route("/api/analysis/history", methods=["GET"])
@require_auth
def get_history():
    """Get user's analysis history"""
    user_id = request.user["user_id"]
    limit = min(int(request.args.get("limit", 20)), 50)

    result = db.get_user_analyses(user_id, limit)
    analyses = []
    for a in (result.data or []):
        analyses.append({
            "id": a["id"],
            "language": a["language_detected"],
            "grade": a["ml_prediction"],
            "syntax_errors": a["syntax_errors"],
            "confidence": a["confidence"],
            "created_at": a["created_at"],
            "code_preview": (a.get("source_code") or "")[:100] + "...",
        })

    return jsonify({"analyses": analyses, "count": len(analyses)}), 200


@analysis_bp.route("/api/analysis/<analysis_id>", methods=["GET"])
@require_auth
def get_analysis(analysis_id):
    """Get full analysis by ID"""
    user_id = request.user["user_id"]
    analysis = db.get_analysis_by_id(analysis_id)

    if not analysis:
        return jsonify({"error": "Analysis not found"}), 404

    # Only owner or admin can view
    if analysis["user_id"] != user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    return jsonify(analysis), 200


@analysis_bp.route("/api/analysis/<analysis_id>", methods=["DELETE"])
@require_auth
def delete_analysis(analysis_id):
    """Delete an analysis"""
    user_id = request.user["user_id"]
    db.delete_analysis(analysis_id, user_id)
    db.log_activity(user_id, "analysis_deleted")
    return jsonify({"message": "Analysis deleted"}), 200


@analysis_bp.route("/api/analysis/rerun/<analysis_id>", methods=["POST"])
@require_auth
def rerun_analysis(analysis_id):
    """Re-run analysis on stored code"""
    user_id = request.user["user_id"]
    analysis = db.get_analysis_by_id(analysis_id)

    if not analysis:
        return jsonify({"error": "Analysis not found"}), 404

    if analysis["user_id"] != user_id:
        return jsonify({"error": "Access denied"}), 403

    # Re-run with original code
    code = analysis.get("source_code", "")
    if not code:
        return jsonify({"error": "No source code stored"}), 400

    # Redirect to submit
    from flask import g
    request._cached_json = ({"code": code}, True)

    # Re-run inline
    language = detect_language(code)["language"]
    features = extract_code_features(code)
    ml_score = compute_quality_score(features, language)
    syntax_issues = detect_syntax_issues(code, language)
    ai_result = run_ai_analysis(code, language, ml_score, syntax_issues)
    ai_sections = parse_ai_sections(ai_result["ai_explanation"])

    db.log_activity(user_id, "analysis_rerun")

    return jsonify({
        "language": language,
        "quality": ml_score,
        "issues": syntax_issues,
        "ai": ai_sections,
    }), 200
