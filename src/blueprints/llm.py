"""
LLM blueprint — LLM 后端配置与管理。
"""

from flask import Blueprint, jsonify, request

from shared.helpers import json_error


def register(app, managers):
    bp = Blueprint("llm", __name__)
    llm_backend = managers["llm_backend"]

    @bp.route("/api/llm/status", methods=["GET"])
    def llm_status():
        return jsonify(llm_backend.get_status())

    @bp.route("/api/llm/refresh", methods=["POST"])
    def llm_refresh():
        llm_backend._detect()
        return jsonify(llm_backend.get_status())

    @bp.route("/api/llm/switch", methods=["POST"])
    def llm_switch():
        data = request.json or {}
        endpoint_id = data.get("endpoint")
        if not endpoint_id:
            return json_error("需要 endpoint 参数")

        # Find and prioritise selected endpoint
        endpoints = list(llm_backend._all_endpoints)
        target = None
        for ep in endpoints:
            if ep.get("id") == endpoint_id:
                target = ep
                break
        if not target:
            return json_error(f"未找到端点: {endpoint_id}", 404)

        llm_backend._primary = target
        llm_backend._fallback = [
            ep for ep in endpoints if ep.get("id") != endpoint_id
        ]
        return jsonify(llm_backend.get_status())

    @bp.route("/api/llm/config", methods=["GET"])
    def llm_get_config():
        return jsonify(llm_backend.get_config())

    @bp.route("/api/llm/config", methods=["PUT"])
    def llm_update_config():
        allowed = {
            "auto_generate_choices", "choice_count",
            "memory_interval", "memory_enabled",
            "system_content_enabled",
            "dialogue_bubble_mode",
        }
        updates = {k: v for k, v in (request.json or {}).items() if k in allowed}
        if updates:
            llm_backend.update_config(updates)
        return jsonify(llm_backend.get_config())

    @bp.route("/api/llm/test", methods=["POST"])
    def llm_test():
        data = request.json or {}
        message = data.get("message", "Hello, this is a test message.")
        result = llm_backend.test_connection(message)
        return jsonify(result)

    app.register_blueprint(bp)
