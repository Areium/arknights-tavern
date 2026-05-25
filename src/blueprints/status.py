"""
Status blueprint — 后端健康检查。
"""

from flask import Blueprint, jsonify


def register(app, managers):
    bp = Blueprint("status", __name__)
    llm_backend = managers["llm_backend"]
    session_mgr = managers["session"]

    @bp.route("/api/status", methods=["GET"])
    def api_status():
        return jsonify({
            "status": "ok",
            "llm": llm_backend.get_status(),
            "sessions": len(session_mgr.list_sessions()),
        })

    app.register_blueprint(bp)
