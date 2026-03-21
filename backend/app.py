"""
LintVertex - Main Flask Application
"""
import os, sys, logging
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from config import Config

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    CORS(app, resources={r"/api/*": {
        "origins": [
            "http://localhost:3000", "http://localhost:5000",
            "https://*.vercel.app", "https://*.onrender.com"
        ],
        "methods": ["GET","POST","PUT","DELETE","OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "X-Admin-Confirm"],
    }})
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_FILE_SIZE_MB * 1024 * 1024

    # Blueprints
    from routes.auth        import auth_bp
    from routes.analysis    import analysis_bp
    from routes.rooms       import rooms_bp
    from routes.other       import profile_bp, feedback_bp
    from routes.admin       import admin_bp
    from routes.email_routes import email_bp, admin_email_bp
    from routes.terms       import terms_bp, admin_terms_bp
    from routes.notifications import notif_bp, admin_notif_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(admin_email_bp)
    app.register_blueprint(terms_bp)
    app.register_blueprint(admin_terms_bp)
    app.register_blueprint(notif_bp)
    app.register_blueprint(admin_notif_bp)

    from utils.security import add_security_headers
    @app.after_request
    def set_security_headers(response):
        return add_security_headers(response)

    @app.route("/api/health")
    def health():
        return jsonify({"status":"ok","service":"LintVertex API","version":"1.0.0"})

    @app.errorhandler(400)
    def bad_request(e):
        if request.path.startswith("/api/"): return jsonify({"error":"Bad request"}), 400
        return send_from_directory(app.static_folder, "404.html"), 400

    @app.errorhandler(401)
    def unauthorized(e):
        if request.path.startswith("/api/"): return jsonify({"error":"Unauthorized"}), 401
        return send_from_directory(app.static_folder, "403.html"), 401

    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith("/api/"): return jsonify({"error":"Forbidden"}), 403
        return send_from_directory(app.static_folder, "403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"): return jsonify({"error":"Not found"}), 404
        return send_from_directory(app.static_folder, "404.html"), 404

    @app.errorhandler(413)
    def file_too_large(e):
        if request.path.startswith("/api/"): return jsonify({"error":"File too large"}), 413
        return send_from_directory(app.static_folder, "404.html"), 413

    @app.errorhandler(429)
    def too_many_requests(e):
        if request.path.startswith("/api/"): return jsonify({"error":"Too many requests","retry_after":60}), 429
        return send_from_directory(app.static_folder, "429.html"), 429

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal server error: {e}")
        if request.path.startswith("/api/"): return jsonify({"error":"Internal server error"}), 500
        return send_from_directory(app.static_folder, "500.html"), 500

    @app.errorhandler(503)
    def service_unavailable(e):
        if request.path.startswith("/api/"): return jsonify({"error":"Service unavailable"}), 503
        return send_from_directory(app.static_folder, "503.html"), 503

    @app.route("/", defaults={"path":""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        if path and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        return send_from_directory(app.static_folder, "index.html")

    logger.info("LintVertex Flask app initialized")
    return app


app = create_app()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=Config.DEBUG)
