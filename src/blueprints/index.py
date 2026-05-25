"""
Index blueprint — 全局依赖聚合、导入/导出、会话索引配置。
"""

import os
import logging
from pathlib import Path

import yaml
from flask import Blueprint, jsonify, request

from shared.helpers import json_error
from shared.cache import invalidate_all_caches
import index_manager as idxmgr

logger = logging.getLogger(__name__)

# Project root from inside blueprints/ is two levels up → src/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = Path(_project_root).parent  # repo root for data/ access
_DATA_ROOT = str(_REPO_ROOT / "data")


def _get_session(session_mgr, session_id):
    """获取会话，不存在则返回 None。"""
    session = session_mgr.get_session(session_id)
    if not session:
        return None
    return session


def register(app, managers):
    bp = Blueprint("index", __name__)
    session_mgr = managers["session"]
    doc_mgr = managers["document"]
    wiki_manager = managers["wiki"]

    # ── 1. GET /api/index/overview ──
    @bp.route("/api/index/overview", methods=["GET"])
    def index_overview():
        """获取全局依赖概览（所有文档的 imports/imported_by）。"""
        overview = idxmgr.build_overview(_DATA_ROOT, doc_manager=doc_mgr)
        return jsonify(overview)

    # ── 2. GET /api/index/export ──
    @bp.route("/api/index/export", methods=["GET"])
    def index_export():
        """导出全局依赖概览为 YAML。"""
        overview = idxmgr.build_overview(_DATA_ROOT, doc_manager=doc_mgr)
        yaml_str = yaml.dump(overview, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return jsonify({"yaml": yaml_str})

    # ── 3. POST /api/index/import ──
    @bp.route("/api/index/import", methods=["POST"])
    def index_import():
        """从 YAML 导入 imports 配置（两阶段：先校验后写入）。"""
        data = request.json or {}
        yaml_text = data.get("yaml", "").strip()
        if not yaml_text:
            return json_error("需要 yaml 参数")

        try:
            config = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            return json_error(f"YAML 解析错误: {e!s}")

        categories = config.get("categories", [])
        if not isinstance(categories, list):
            return json_error("categories 必须是数组")

        # Phase 1: 验证（dry-run）—— 收集所有要写入的 imports
        operations: list[dict] = []
        errors: list[dict] = []

        for cat_entry in categories:
            cat_name = cat_entry.get("category", "")
            docs = cat_entry.get("docs", [])
            if not cat_name or not isinstance(docs, list):
                continue

            for d in docs:
                doc_id = d.get("id", "")
                imports_raw = d.get("imports", [])
                if not doc_id or not isinstance(imports_raw, list):
                    continue

                # 验证文档存在
                try:
                    doc = doc_mgr.read_document(cat_name, doc_id)
                    filepath = doc["filepath"]
                except Exception:
                    errors.append({
                        "category": cat_name,
                        "id": doc_id,
                        "error": "文档不存在",
                    })
                    continue

                # 验证每个 import 路径
                valid_imports = []
                for imp in imports_raw:
                    if isinstance(imp, dict):
                        imp_path = imp.get("path", "")
                    elif isinstance(imp, str):
                        imp_path = imp.split(" | ")[0].strip()
                    else:
                        continue

                    if "/" not in imp_path:
                        errors.append({
                            "category": cat_name,
                            "id": doc_id,
                            "import": imp_path,
                            "error": "路径格式错误",
                        })
                        continue

                    valid_imports.append(imp_path)

                operations.append({
                    "category": cat_name,
                    "id": doc_id,
                    "filepath": filepath,
                    "imports": valid_imports,
                })

        if errors:
            return json_error({
                "message": f"验证失败：{len(errors)} 个错误",
                "errors": errors,
            }, 400)

        # Phase 2: 写入
        written = 0
        for op in operations:
            try:
                idxmgr.write_imports_to_file(op["filepath"], op["imports"], doc_mgr)
                written += 1
            except Exception as e:
                errors.append({
                    "category": op["category"],
                    "id": op["id"],
                    "error": str(e),
                })

        # 失效缓存
        try:
            invalidate_all_caches(idxmgr, wiki_manager)
        except Exception:
            pass

        return jsonify({
            "message": f"已写入 {written} 个文档的 imports，{len(errors)} 个失败",
            "written": written,
            "errors": errors,
        })

    # ── 4. GET /api/index/verify ──
    @bp.route("/api/index/verify", methods=["GET"])
    def index_verify():
        """验证全局索引，检查断裂的引用。"""
        overview = idxmgr.build_overview(_DATA_ROOT, doc_manager=doc_mgr)
        categories = overview.get("categories", [])
        issues: list[dict] = []

        # 收集所有已知文档路径
        known_paths: set[str] = set()
        for cat in categories:
            for doc in cat.get("docs", []):
                path = doc.get("path", "")
                if path:
                    known_paths.add(path)

        # 检查每个文档的 imports
        for cat in categories:
            for doc in cat.get("docs", []):
                doc_path = doc.get("path", "")
                doc_name = doc.get("name", "")
                doc_imports = doc.get("imports", [])

                for imp in doc_imports:
                    imp_path = imp.get("path", "")
                    if imp_path and imp_path not in known_paths:
                        issues.append({
                            "type": "broken_import",
                            "source": doc_path,
                            "source_name": doc_name,
                            "target": imp_path,
                            "message": f"引用断裂: {doc_path} → {imp_path}（目标不存在）",
                        })

                # 检查无 imports 的文档（信息性警告）
                if not doc_imports:
                    issues.append({
                        "type": "no_imports",
                        "source": doc_path,
                        "source_name": doc_name,
                        "message": f"{doc_path} 没有任何 imports",
                    })

        # 检查无 imported_by 的文档（可能孤立）
        for cat in categories:
            for doc in cat.get("docs", []):
                doc_path = doc.get("path", "")
                imported_by = doc.get("imported_by", [])
                if not imported_by and doc.get("imports", []):
                    issues.append({
                        "type": "no_backlinks",
                        "source": doc_path,
                        "source_name": doc.get("name", ""),
                        "message": f"{doc_path} 没有反向引用（可能是终端节点）",
                    })

        broken = sum(1 for i in issues if i["type"] == "broken_import")
        return jsonify({
            "total_issues": len(issues),
            "broken_imports": broken,
            "issues": issues,
        })

    # ── 5. GET /api/sessions/<session_id>/index/verify ──
    @bp.route("/api/sessions/<session_id>/index/verify", methods=["GET"])
    def session_index_verify(session_id: str):
        """验证会话的索引配置：白名单启用的所有实体依赖是否完整。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)

        overview = idxmgr.build_overview(_DATA_ROOT, doc_manager=doc_mgr)
        index_config = session.overlay.get_index_config()

        # 计算白名单启用的路径集合
        enabled_paths: set[str] = set()

        if index_config.get("mode") == "whitelist":
            enabled_cats = index_config.get("enabled_categories", [])
            enabled_ents = index_config.get("enabled_entities", {})

            for cat_entry in overview.get("categories", []):
                cat_name = cat_entry.get("category", "")
                for doc in cat_entry.get("docs", []):
                    doc_path = doc.get("path", "")
                    doc_id = doc.get("id", "")
                    if cat_name in enabled_cats:
                        enabled_paths.add(doc_path)
                    elif (cat_name in enabled_ents and
                          doc_id in enabled_ents[cat_name]):
                        enabled_paths.add(doc_path)
        else:
            # mode == "all": 所有路径都启用
            for cat_entry in overview.get("categories", []):
                for doc in cat_entry.get("docs", []):
                    path = doc.get("path", "")
                    if path:
                        enabled_paths.add(path)

        # 检查每个启用文档的 imports 依赖完整性
        results: list[dict] = []
        for cat_entry in overview.get("categories", []):
            for doc in cat_entry.get("docs", []):
                doc_path = doc.get("path", "")
                if doc_path not in enabled_paths:
                    continue

                imports = doc.get("imports", [])
                missing = []
                for imp in imports:
                    imp_path = imp.get("path", "")
                    if imp_path and imp_path not in enabled_paths:
                        missing.append({
                            "path": imp_path,
                            "name": imp.get("name", ""),
                        })

                if missing:
                    results.append({
                        "path": doc_path,
                        "name": doc.get("name", ""),
                        "missing_imports": missing,
                        "issue": f"缺少 {len(missing)} 个依赖: " +
                                 ", ".join(m["path"] for m in missing),
                    })

        return jsonify({
            "mode": index_config.get("mode", "all"),
            "enabled_count": len(enabled_paths),
            "total_count": sum(
                len(cat.get("docs", []))
                for cat in overview.get("categories", [])
            ),
            "broken_dependencies": len(results),
            "results": results,
        })

    # ── 6. GET /api/sessions/<session_id>/index-config ──
    @bp.route("/api/sessions/<session_id>/index-config", methods=["GET"])
    def get_index_config(session_id: str):
        """获取会话的索引配置。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        return jsonify(session.overlay.get_index_config())

    # ── 7. PUT /api/sessions/<session_id>/index-config ──
    @bp.route("/api/sessions/<session_id>/index-config", methods=["PUT"])
    def set_index_config(session_id: str):
        """设置会话的索引配置。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        session.overlay.set_index_config(data)
        return jsonify(session.overlay.get_index_config())

    # ── 8. DELETE /api/sessions/<session_id>/index-config ──
    @bp.route("/api/sessions/<session_id>/index-config", methods=["DELETE"])
    def reset_index_config(session_id: str):
        """重置会话的索引配置为默认值。"""
        session = _get_session(session_mgr, session_id)
        if not session:
            return json_error("会话不存在", 404)
        session.overlay.reset_index_config()
        return jsonify(session.overlay.get_index_config())

    app.register_blueprint(bp)
