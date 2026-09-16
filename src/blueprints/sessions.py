"""
Sessions blueprint — 会话管理与剧情列表。
"""

import os
import re
import logging
import shutil
import tempfile
import copy
import hashlib
import json
import threading
from pathlib import Path
from urllib.parse import quote

import frontmatter
from flask import Blueprint, jsonify, request

from shared.helpers import json_error
from session_manager import SessionCleanupError
from session_resources import is_safe_entity_name
from session_worldbook_dependencies import (
    apply_inheritance_update, change_relation, effective_graph, ensure_editable_scope,
    graph_view, preview_inheritance_update, restore_inheritance,
)
from world_book import content_revision
from worldbook_builder import (
    AnalysisCache, DependencyJobStore, content_hash, evidence_locatable,
    model_identity, normalize_reading_mode, run_scoped_build,
)
from worldbook_reading import READING_MODE_ADAPTIVE

logger = logging.getLogger(__name__)

_SESSION_BG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Project root = src/ (from blueprints/sessions.py)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Repository root for data/ access
_REPO_ROOT = Path(_project_root).parent
_SESSION_JOB_STORE = DependencyJobStore(
    _REPO_ROOT / "data" / "memory" / "session_dependency_jobs")
_SESSION_ANALYSIS_CACHE = AnalysisCache()
_SESSION_JOB_START_LOCK = threading.Lock()


def _load_plot_opening(session, plot_id: str, load_characters: bool = True):
    """加载剧情的开场配置到会话中。

    从 index.md frontmatter 读取所有开场字段。
    """
    from session_overlay import _read_plot_file

    try:
        result = _read_plot_file(plot_id)
        if not result:
            return
        meta, body = result

        # 1. 设置环境
        location = meta.get("initial_location", "")
        time_val = meta.get("initial_time", "")
        atmosphere = meta.get("initial_atmosphere", "")
        if location:
            session.environment.set_location(location)
        if time_val:
            session.environment.time_of_day = time_val
        if atmosphere:
            if isinstance(atmosphere, str):
                session.environment.atmosphere = [atmosphere]
            elif isinstance(atmosphere, list):
                session.environment.atmosphere = atmosphere
        session.persist_environment()

        # 2. 加载初始角色（跳过不存在的角色 & 玩家身份角色）
        player_identity = session.player_identity
        for char_name in (meta.get("initial_characters", []) if load_characters else []):
            name = char_name.strip()
            if name and name != player_identity:
                ok = session.scene_manager.load_character(name)
                if ok:
                    logger.debug("开场加载角色: %s", name)

        # 3. 设置默认对话目标（第一个非玩家角色）
        if not session.scene_manager.active:
            chars = session.scene_manager.get_scene_characters()
            if chars:
                session.scene_manager.active = chars[0]

        # 4. 存储开场上下文（首次叙述注入用）
        from session_overlay import _extract_section
        scene_desc = _extract_section(body, "开场设置") if body else ""
        if not scene_desc:
            scene_desc = body.strip()[:500] if body else ""
        if scene_desc:
            session.overlay.set_plot_context(scene_desc)

        logger.info("剧情 %s 开场已加载: loc=%s time=%s chars=%d",
                     plot_id, location, time_val,
                     len(session.scene_manager.get_scene_characters()))
    except Exception as e:
        logger.warning("加载剧情开场失败 %s: %s", plot_id, e)


def register(app, managers):
    bp = Blueprint("sessions", __name__)
    session_mgr = managers["session"]
    wb_mgr = managers.get("worldbook")

    # ── 会话 CRUD ──

    @bp.route("/api/sessions", methods=["GET"])
    def list_sessions():
        """列出所有会话。"""
        return jsonify(session_mgr.list_sessions())

    @bp.route("/api/sessions", methods=["POST"])
    def create_session():
        """创建新会话，可选绑定剧情。"""
        data = request.json or {}
        mode = data.get("mode", "free")
        if mode not in ("free", "story"):
            return json_error("mode 必须是 'free' 或 'story'")

        combat_mode = data.get("combat_mode", "narrative")
        if combat_mode not in ("narrative", "tactical"):
            return json_error("combat_mode 必须是 'narrative' 或 'tactical'")

        plot_id = data.get("plot_id", "").strip()
        plot_name = ""
        if plot_id and mode == "story":
            from session_overlay import _resolve_plot_dir, _read_plot_file
            result = _read_plot_file(plot_id)
            if result:
                plot_name = result[0].get("name", "")
            if not plot_name:
                resolved = _resolve_plot_dir(plot_id) or plot_id
                plot_name = resolved

        # 玩家身份角色（用户自身，默认"博士"）
        player_identity = str(data.get("identity", "") or "").strip() or "博士"

        worldbook_id = str(data.get("worldbook_id", "") or "").strip()
        roster = data.get("roster_character_ids", [])
        if not isinstance(roster, list) or not all(isinstance(x, str) and x.strip() for x in roster):
            return json_error("roster_character_ids 必须是非空字符串组成的数组")
        try:
            book = wb_mgr.load(worldbook_id) if worldbook_id and wb_mgr else None
            if worldbook_id and (book is None or not book.enabled):
                return json_error("世界书不存在或已停用", 404)
            # 旧客户端未传此字段时沿用默认书；新客户端空字符串表示明确不绑定。
            if "worldbook_id" not in data and wb_mgr:
                book = wb_mgr.resolve()
            book = copy.deepcopy(book)
        except (ValueError, TypeError, OSError) as exc:
            return json_error(f"世界书读取失败：{exc}")

        def initialize(session):
            if plot_id and mode == "story":
                from session_overlay import _resolve_plot_dir
                resolved = _resolve_plot_dir(plot_id) or plot_id
                if (_REPO_ROOT / "data" / "plots" / resolved).is_dir():
                    session.overlay.load_quests_from_plot(plot_id)
                    _load_plot_opening(session, plot_id, load_characters="roster_character_ids" not in data)
                    session.overlay.init_session_docs(plot_id)
            for character in dict.fromkeys(name.strip() for name in roster):
                if character != player_identity and not session.scene_manager.load_character(character):
                    raise ValueError(f"无法加载入队角色：{character}")
            # 以**实际加载成功**的阵容解析候选范围（加载失败的角色已在上面抛错）。
            roster_ids = session.scene_manager.get_scene_characters()
            # 「本次会话全量兼容」是显式选择，只作用于这个会话，不改这本书的规则。
            full_scope = bool(data.get("full_scope"))
            if book is not None:
                manual = data.get("manual_entry_uids") or []
                if not isinstance(manual, list) or any(
                        not isinstance(uid, str) or not uid.strip() for uid in manual):
                    raise ValueError("manual_entry_uids 必须是非空字符串组成的数组")
                # 预览版本校验：带了 draft_hash 就必须与当前实际阵容的解析一致，
                # 否则说明预览已过期，宁可报错也不静默用一套不同的范围创建会话。
                scoped_book = copy.deepcopy(book)
                if not scoped_book.v3_enabled:
                    scoped_book.adopt_v2_as_v3()
                expected = data.get("expected_draft_hash")
                if expected and book.v3_enabled and expected != book.policy_draft_hash(roster_ids, manual, None, full_scope):
                    raise ValueError("候选范围预览已过期，请重新预览后再创建会话")
                scope = scoped_book.session_scope_snapshot(
                    roster_ids, manual, full_scope=full_scope)
            else:
                scope = {"book_id": None, "resolved_entry_uids": []}
            session.overlay.set_worldbook_scope(scope)

        try:
            session = session_mgr.create_session(
                name=data.get("name", ""), mode=mode,
                plot_name=plot_name if not data.get("name") else "",
                combat_mode=combat_mode, player_identity=player_identity,
                plot_id=plot_id, worldbook_id=book.id if book else "",
                initializer=initialize,
            )
        except ValueError as exc:
            return json_error(str(exc))
        except Exception:
            logger.exception("创建会话失败，已清理本次半成品")
            return json_error("创建会话失败，请重试", 500)
        return jsonify(session.to_dict()), 201

    @bp.route("/api/sessions/<session_id>", methods=["GET"])
    def get_session(session_id: str):
        """获取单个会话详情。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        return jsonify(session.to_dict())

    @bp.route("/api/sessions/<session_id>", methods=["DELETE"])
    def delete_session(session_id: str):
        """删除会话（级联删除该会话下所有战斗与挂起存档）。

        清理失败必须如实返回错误：`delete_session` 在任何一项资源没清干净时
        都会抛 `SessionCleanupError` 并保持会话可用，前端可以重试。若这里
        静默吞掉，玩家会看到「删除成功」但磁盘上仍留着会话目录 / 挂起存档。
        """
        try:
            ok = session_mgr.delete_session(session_id)
        except SessionCleanupError as exc:
            logger.error("删除会话 %s 失败：%s", session_id, exc)
            return json_error(str(exc), 500)
        if not ok:
            return json_error("会话不存在", 404)
        return jsonify({"message": "会话已删除"})

    @bp.route("/api/sessions/<session_id>/rename", methods=["PUT"])
    def rename_session(session_id: str):
        """重命名会话。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        new_name = data.get("name", "").strip()
        if not new_name:
            return json_error("需要 name 参数")
        session_mgr.rename_session(session_id, new_name)
        return jsonify({"message": "已重命名", "name": new_name})

    @bp.route("/api/sessions/<session_id>/custom-prompt", methods=["PUT"])
    def set_custom_prompt(session_id: str):
        """设置会话的自定义提示词。"""
        session_obj = session_mgr.get_session(session_id)
        if not session_obj:
            return json_error("会话不存在", 404)
        data = request.json or {}
        prompt = data.get("prompt", "").strip()
        if prompt:
            session_obj.overlay.set_custom_prompt(prompt)
        else:
            session_obj.overlay.delete_custom_prompt()
        return jsonify({
            "message": "自定义提示词已更新",
            "custom_prompt": session_obj.overlay.get_custom_prompt(),
        })

    # ── 会话级世界书依赖 ──

    def _book_input_hash(book):
        payload = [{"uid": e.uid, "content": content_hash(e.content or ""),
                    "name": e.name, "aliases": e.trigger_keys,
                    "secondary_aliases": e.secondary_keys, "enabled": e.enabled,
                    "position": e.position, "category_id": e.category_id,
                    "character_id": e.character_id}
                   for e in book.entries]
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _session_book(session):
        book_id = session.overlay.get_worldbook_id()
        if not book_id and wb_mgr:
            scope = session.overlay.get_worldbook_scope() or {}
            book_id = scope.get("book_id")
        book = wb_mgr.load(book_id) if book_id and wb_mgr else None
        return book_id, book

    def _character_directory_ids():
        document = managers.get("document")
        if not document:
            return []
        try:
            docs = document.list_documents("characters", include_content=False)
        except Exception:
            return []
        return sorted({str(item.get("id") or "") for item in docs if item.get("id")})

    def _refresh_managed_scope(book, scope, roster):
        editable = ensure_editable_scope(scope, book, roster)
        return book.refresh_session_scope(editable, roster)

    def _scope_identity(scope):
        managed = scope if isinstance(scope, dict) else {}
        payload = {"book_id": (managed or {}).get("book_id"),
            "scope_revision": (managed or {}).get("scope_revision"),
            "roster": sorted((managed or {}).get("roster_character_ids") or []),
            "manual": sorted((managed or {}).get("manual_entry_uids") or []),
            "full_scope": bool((managed or {}).get("full_scope")),
            "resolved": sorted((managed or {}).get("resolved_entry_uids") or []),
            "rules": (managed or {}).get("rules"),
            "requires_edges": (managed or {}).get("requires_edges"),
            "related_edges": (managed or {}).get("related_edges")}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]

    def _dependency_payload(session, book, scope):
        view = graph_view(scope)
        selected = set(scope.get("resolved_entry_uids") or [])
        view.update({
            "session_id": session.id, "book_id": book.id, "book_name": book.name,
            "content_revision": content_revision(book.entries),
            "resolved_entry_uids": sorted(selected),
            "selection_reasons": scope.get("selection_reasons") or {},
            "entries": [{"uid": e.uid, "name": e.name,
                         "selected": e.uid in selected,
                         "reasons": (scope.get("selection_reasons") or {}).get(e.uid, [])}
                        for e in book.entries if e.enabled and (e.content or "").strip()],
        })
        return view

    def _get_managed(session_id, persist_upgrade=True):
        with session_mgr._lock:
            session = session_mgr._sessions.get(session_id)
            if session is None:
                return None, None, None, json_error("会话不存在", 404)
            book_id, book = _session_book(session)
            if not book:
                return session, None, None, json_error("会话未绑定可用世界书", 404)
            roster = session.scene_manager.get_scene_characters()
            try:
                current = session.overlay.get_worldbook_scope()
                needs_refresh = (not isinstance(current, dict)
                    or current.get("schema_version") != 3 or not current.get("inheritance")
                    or sorted(current.get("roster_character_ids") or []) != sorted(roster))
                if persist_upgrade and needs_refresh:
                    scope = session.overlay.update_worldbook_scope(
                        lambda latest: _refresh_managed_scope(book, latest, roster))
                else:
                    scope = ensure_editable_scope(current, book, roster)
            except (TypeError, ValueError) as exc:
                return session, book, None, json_error(str(exc))
            return session, book, scope, None

    @bp.route("/api/sessions/<session_id>/worldbook-dependencies", methods=["GET"])
    def get_session_worldbook_dependencies(session_id):
        session, book, scope, err = _get_managed(session_id)
        if err:
            return err
        return jsonify(_dependency_payload(session, book, scope))

    @bp.route("/api/sessions/<session_id>/worldbook-dependencies", methods=["PATCH"])
    def patch_session_worldbook_dependencies(session_id):
        data = request.get_json(silent=True) or {}
        try:
            expected = int(data.get("expected_scope_revision"))
        except (TypeError, ValueError):
            return json_error("需要 expected_scope_revision")
        with session_mgr._lock:
            session = session_mgr._sessions.get(session_id)
            if not session:
                return json_error("会话不存在", 404)
            _book_id, book = _session_book(session)
            if not book:
                return json_error("会话未绑定可用世界书", 404)
            known = {e.uid for e in book.entries}
            a, b = str(data.get("from_uid") or ""), str(data.get("to_uid") or "")
            if a not in known or b not in known:
                return json_error("关系引用了不存在的条目")
            try:
                def update(current):
                    managed = ensure_editable_scope(
                        current, book, session.scene_manager.get_scene_characters())
                    changed = change_relation(managed, a, b, data.get("relation"), expected,
                        bool(data.get("enable_source_expansion")))
                    return book.refresh_session_scope(
                        changed, session.scene_manager.get_scene_characters())
                scope = session.overlay.update_worldbook_scope(update)
            except RuntimeError as exc:
                return json_error(str(exc), 409)
            except ValueError as exc:
                return json_error(str(exc))
        return jsonify(_dependency_payload(session, book, scope))

    @bp.route("/api/sessions/<session_id>/worldbook-dependencies/restore", methods=["POST"])
    def restore_session_worldbook_dependencies(session_id):
        data = request.get_json(silent=True) or {}
        try:
            expected = int(data.get("expected_scope_revision"))
        except (TypeError, ValueError):
            return json_error("需要 expected_scope_revision")
        with session_mgr._lock:
            session = session_mgr._sessions.get(session_id)
            if not session:
                return json_error("会话不存在", 404)
            _book_id, book = _session_book(session)
            if not book:
                return json_error("会话未绑定可用世界书", 404)
            try:
                def update(current):
                    managed = ensure_editable_scope(
                        current, book, session.scene_manager.get_scene_characters())
                    changed = restore_inheritance(managed, expected,
                        data.get("from_uid"), data.get("to_uid"))
                    return book.refresh_session_scope(
                        changed, session.scene_manager.get_scene_characters())
                scope = session.overlay.update_worldbook_scope(update)
            except RuntimeError as exc:
                return json_error(str(exc), 409)
            except ValueError as exc:
                return json_error(str(exc))
        return jsonify(_dependency_payload(session, book, scope))

    @bp.route("/api/sessions/<session_id>/worldbook-dependencies/inheritance-preview", methods=["POST"])
    def preview_session_worldbook_inheritance(session_id):
        session, book, scope, err = _get_managed(session_id)
        if err:
            return err
        return jsonify(preview_inheritance_update(scope, book))

    @bp.route("/api/sessions/<session_id>/worldbook-dependencies/inheritance", methods=["POST"])
    def update_session_worldbook_inheritance(session_id):
        data = request.get_json(silent=True) or {}
        try:
            expected = int(data.get("expected_scope_revision"))
        except (TypeError, ValueError):
            return json_error("需要 expected_scope_revision")
        with session_mgr._lock:
            session = session_mgr._sessions.get(session_id)
            if not session:
                return json_error("会话不存在", 404)
            _book_id, book = _session_book(session)
            if not book:
                return json_error("会话未绑定可用世界书", 404)
            try:
                def update(current):
                    managed = ensure_editable_scope(
                        current, book, session.scene_manager.get_scene_characters())
                    preview = preview_inheritance_update(managed, book)
                    changed = apply_inheritance_update(
                        managed, preview, expected, str(data.get("preview_hash") or ""))
                    return book.refresh_session_scope(
                        changed, session.scene_manager.get_scene_characters())
                scope = session.overlay.update_worldbook_scope(update)
            except RuntimeError as exc:
                return json_error(str(exc), 409)
        return jsonify(_dependency_payload(session, book, scope))

    def _session_jobs(session_id, book_id):
        return [item for item in _SESSION_JOB_STORE.list_for_book(book_id)
                if (item.get("context") or {}).get("session_id") == session_id]

    @bp.route("/api/sessions/<session_id>/worldbook-dependency-jobs", methods=["POST"])
    def create_session_dependency_job(session_id):
        session, book, scope, err = _get_managed(session_id)
        if err:
            return err
        backend = managers.get("llm_backend")
        llm, backend_id = backend.get_llm() if backend else (None, "")
        if not llm:
            return json_error("尚未配置可用的 LLM，请先前往设置", 503)
        data = request.get_json(silent=True) or {}
        try:
            reading_mode = normalize_reading_mode(
                data.get("reading_mode"), default=READING_MODE_ADAPTIVE)
        except ValueError as exc:
            return json_error(str(exc))
        raw_max_calls = data.get("max_calls")
        try:
            max_calls = (max(1, min(5000, int(raw_max_calls)))
                         if raw_max_calls not in (None, "") else None)
        except (TypeError, ValueError):
            return json_error("max_calls 必须是正整数")
        graph = effective_graph(scope)
        current_revision = content_revision(book.entries)
        inherited_valid = scope["inheritance"].get("content_revision") == current_revision
        known_pairs, known_requires = [], []
        for relation in ("requires", "related"):
            for edge in graph.get(f"{relation}_edges", []):
                origin = graph["origins"].get(
                    f"{relation}:{edge['from_uid']}|{edge['to_uid']}")
                if origin == "local" or inherited_valid:
                    pair = (edge["from_uid"], edge["to_uid"])
                    known_pairs.append(pair)
                    if relation == "requires":
                        known_requires.append(pair)
        # 人工屏蔽始终保护；正文变化不应让 AI 把用户删掉的 pair 再建议回来。
        known_pairs += [(e["from_uid"], e["to_uid"])
                        for e in scope.get("suppressed_edges") or []]
        sources = sorted(set(scope.get("resolved_entry_uids") or []))
        character_ids = _character_directory_ids()
        with _SESSION_JOB_START_LOCK:
            if any(item.get("running") or item.get("stage") not in ("done", "failed", "cancelled")
                   for item in _session_jobs(session_id, book.id)):
                return json_error("这个会话已有依赖微调任务在运行", 409)
            job = _SESSION_JOB_STORE.create(
                book.id, _book_input_hash(book), model_identity(llm, backend_id), reading_mode)
            job.context = {"session_id": session_id, "book_id": book.id,
                "content_revision": current_revision, "scope_revision": scope["scope_revision"],
                "scope_identity": _scope_identity(scope),
                "source_uids": sources, "known_pairs": [list(p) for p in known_pairs],
                "known_requires": [list(p) for p in known_requires],
                "character_ids": character_ids}
            job.message = "已排队，正在分析本会话相关条目"
            job.running = True
            job.save()
        snapshot = copy.deepcopy(book)

        def worker():
            try:
                run_scoped_build(job, snapshot, llm, model=job.model,
                    cache=_SESSION_ANALYSIS_CACHE, max_calls=max_calls,
                    source_uids=sources, known_pairs=known_pairs,
                    known_requires=known_requires,
                    character_ids=character_ids)
            finally:
                job.running = False
                job.save()
        threading.Thread(target=worker, name=f"session-wb-{job.id}", daemon=True).start()
        return jsonify({"job": job.to_dict(include_result=False)}), 202

    @bp.route("/api/sessions/<session_id>/worldbook-dependency-jobs", methods=["GET"])
    def list_session_dependency_jobs(session_id):
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        book_id, book = _session_book(session)
        if not book:
            return jsonify({"jobs": []})
        return jsonify({"jobs": _session_jobs(session_id, book_id)})

    def _owned_job(session_id, job_id):
        job = _SESSION_JOB_STORE.get(job_id)
        if job is None or (job.context or {}).get("session_id") != session_id:
            return None
        return job

    @bp.route("/api/sessions/<session_id>/worldbook-dependency-jobs/<job_id>", methods=["GET"])
    def get_session_dependency_job(session_id, job_id):
        job = _owned_job(session_id, job_id)
        if not job:
            return json_error("任务不存在", 404)
        payload = job.to_dict()
        session = session_mgr.get_session(session_id)
        scope = session.overlay.get_worldbook_scope() if session else {}
        _book_id, book = _session_book(session) if session else (None, None)
        payload["stale"] = (not session or not book
            or job.input_hash != _book_input_hash(book)
            or (job.context or {}).get("scope_revision") != (scope or {}).get("scope_revision")
            or (job.context or {}).get("scope_identity") != _scope_identity(scope or {})
            or (job.context or {}).get("character_ids", []) != _character_directory_ids())
        return jsonify({"job": payload})

    @bp.route("/api/sessions/<session_id>/worldbook-dependency-jobs/<job_id>/cancel", methods=["POST"])
    def cancel_session_dependency_job(session_id, job_id):
        job = _owned_job(session_id, job_id)
        if not job:
            return json_error("任务不存在", 404)
        _SESSION_JOB_STORE.cancel(job_id)
        current = _SESSION_JOB_STORE.get(job_id)
        current.resumable = True
        current.save()
        return jsonify({"job": current.to_dict(False)})

    @bp.route("/api/sessions/<session_id>/worldbook-dependency-jobs/<job_id>/retry", methods=["POST"])
    def retry_session_dependency_job(session_id, job_id):
        job = _owned_job(session_id, job_id)
        if not job:
            return json_error("任务不存在", 404)
        session, book, scope, err = _get_managed(session_id)
        if err:
            return err
        if (job.input_hash != _book_input_hash(book)
                or (job.context or {}).get("scope_revision") != scope["scope_revision"]
                or (job.context or {}).get("scope_identity") != _scope_identity(scope)
                or (job.context or {}).get("character_ids", []) != _character_directory_ids()):
            return json_error("任务绑定的正文或会话范围已变化，请新建任务", 409)
        pairs = [{"from_uid": a, "to_uid": b} for batch in job.failed_batches
                 for a, b in batch.get("pairs", [])] or list(job.pending_pairs)
        uids = sorted({uid for batch in job.failed_batches for uid in batch.get("uids", [])}) \
            or list(job.pending_card_uids)
        if not pairs and not uids and not job.resumable:
            return json_error("没有失败批次需要重试")
        backend = managers.get("llm_backend")
        llm, backend_id = backend.get_llm() if backend else (None, "")
        if not llm:
            return json_error("尚未配置可用的 LLM，无法重试", 503)
        if model_identity(llm, backend_id) != job.model:
            return json_error("模型已变化，请新建任务", 409)
        raw_max_calls = (request.get_json(silent=True) or {}).get("max_calls")
        try:
            max_calls = max(1, min(5000, int(raw_max_calls))) if raw_max_calls else 100
        except (TypeError, ValueError):
            return json_error("max_calls 必须是正整数")
        with _SESSION_JOB_START_LOCK:
            if job.running or any(item.get("running") or item.get("stage") not in
                                  ("done", "failed", "cancelled")
                                  for item in _session_jobs(session_id, book.id)
                                  if item.get("job_id") != job.id):
                return json_error("这个会话已有依赖微调任务仍在运行", 409)
            job.cancelled = False
            job.failed_batches = []
            job.resumable = False
            job.running = True
            job.save()
        snapshot, context = copy.deepcopy(book), job.context or {}

        def worker():
            try:
                run_scoped_build(job, snapshot, llm, model=job.model,
                    cache=_SESSION_ANALYSIS_CACHE, max_calls=max_calls,
                    only_pairs=pairs or None, only_uids=uids or None,
                    source_uids=context.get("source_uids"),
                    known_pairs=context.get("known_pairs"),
                    known_requires=context.get("known_requires"),
                    character_ids=context.get("character_ids"))
            finally:
                job.running = False
                job.save()
        threading.Thread(target=worker, name=f"session-wb-retry-{job.id}", daemon=True).start()
        return jsonify({"job": job.to_dict(False)}), 202

    @bp.route("/api/sessions/<session_id>/worldbook-dependency-jobs/<job_id>/apply", methods=["POST"])
    def apply_session_dependency_job(session_id, job_id):
        job = _owned_job(session_id, job_id)
        if (not job or job.running or job.cancelled or job.stage != "done"
                or not isinstance(job.result, dict)
                or (job.context or {}).get("scoped_complete") is False):
            return json_error("任务尚未完成或不存在", 409)
        data = request.get_json(silent=True) or {}
        wanted = {(str(x[0]), str(x[1])) for x in data.get("accepted_pairs", [])
                  if isinstance(x, list) and len(x) == 2}
        with session_mgr._lock:
            session = session_mgr._sessions.get(session_id)
            if not session:
                return json_error("会话不存在", 404)
            _book_id, book = _session_book(session)
            context = job.context or {}
            if not book or context.get("book_id") != book.id or job.input_hash != _book_input_hash(book):
                return json_error("任务已过期：会话范围、世界书正文或绑定已变化", 409)
            by_uid = {e.uid: e for e in book.entries}
            accepted = []
            for record in job.result.get("records") or []:
                pair = (record.get("from_uid"), record.get("to_uid"))
                if pair not in wanted or record.get("relation") not in ("requires", "related"):
                    continue
                a, b = pair
                if a not in by_uid or b not in by_uid:
                    return json_error("AI 建议引用了不存在的条目", 409)
                if (record.get("source_content_hash") != content_hash(by_uid[a].content or "")
                        or record.get("target_content_hash") != content_hash(by_uid[b].content or "")
                        or not evidence_locatable(record.get("evidence"), [by_uid[a], by_uid[b]])):
                    return json_error(f"AI 建议证据已过期或不可定位：{a} → {b}", 409)
                accepted.append((a, b, record["relation"]))
            try:
                def update(scope):
                    if (context.get("content_revision") != content_revision(book.entries)
                            or context.get("scope_revision") != (scope or {}).get("scope_revision")
                            or context.get("scope_identity") != _scope_identity(scope or {})
                            or context.get("character_ids", []) != _character_directory_ids()):
                        raise RuntimeError("任务已过期：会话范围、世界书正文或绑定已变化")
                    changed = ensure_editable_scope(
                        scope, book, session.scene_manager.get_scene_characters())
                    revision = changed["scope_revision"]
                    for a, b, relation in accepted:
                        changed = change_relation(changed, a, b, relation, revision,
                                                  relation == "requires")
                        revision = changed["scope_revision"]
                    return book.refresh_session_scope(
                        changed, session.scene_manager.get_scene_characters())
                scope = session.overlay.update_worldbook_scope(update)
            except RuntimeError as exc:
                return json_error(str(exc), 409)
        return jsonify({"applied": len(accepted),
                        "dependencies": _dependency_payload(session, book, scope)})

    @bp.route("/api/sessions/<session_id>/backgrounds/<path:filename>", methods=["GET"])
    def session_background(session_id: str, filename: str):
        """会话级战斗背景覆盖图：data/memory/sessions/<mode>/<id>/backgrounds/<file>。"""
        from flask import send_from_directory

        sessions_dir = _REPO_ROOT / "data" / "memory" / "sessions"
        safe_name = filename.replace("\\", "/")
        for mode in ("story", "free"):
            bg_dir = sessions_dir / mode / session_id / "backgrounds"
            if not bg_dir.is_dir():
                continue
            filepath = (bg_dir / safe_name).resolve()
            # 防路径穿越
            if not str(filepath).startswith(str(bg_dir.resolve()) + os.sep):
                return json_error("无效的文件路径", 403)
            if filepath.suffix.lower() not in _SESSION_BG_EXTS:
                return json_error("不允许的文件类型", 403)
            if filepath.is_file():
                return send_from_directory(str(bg_dir), safe_name)
        return json_error("文件不存在", 404)

    # ── 会话资源空间（角色形象覆盖 + 背景覆盖 + 文档副本） ──

    @bp.route("/api/sessions/<session_id>/resources", methods=["GET"])
    def session_resources_overview(session_id: str):
        """会话资源总览：背景覆盖 + 角色形象覆盖 + 文档副本 + 可用背景 ID。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        session_dir = Path(session.data_dir)

        from combat_data_loader import CombatDataLoader
        from session_resources import list_session_media, session_resources_dir

        loader = CombatDataLoader()

        # 会话背景覆盖
        backgrounds = []
        bg_dir = session_dir / "backgrounds"
        if bg_dir.is_dir():
            for f in sorted(bg_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in _SESSION_BG_EXTS:
                    bg_id = f.stem
                    global_url = loader.background_image_url(bg_id)
                    backgrounds.append({
                        "type": "background",
                        "key": bg_id,
                        "name": f.name,
                        "url": f"/api/sessions/{session_id}/backgrounds/{f.name}",
                        "global_url": global_url,
                        "size": f.stat().st_size,
                        "has_global": global_url is not None,
                    })

        # 会话角色形象覆盖
        _ENDPOINT = {"avatar": "avatar", "skin": "skin", "card_face": "card-face"}
        character_media = []
        for item in list_session_media(session_dir):
            name = item["name"]
            media_type = item["media_type"]
            character_media.append({
                "type": "character_media",
                "key": name,
                "media_type": media_type,
                "name": item["filename"],
                "url": f"/api/characters/{quote(name)}/{_ENDPOINT[media_type]}?session_id={session_id}",
                "global_url": f"/api/characters/{quote(name)}/{_ENDPOINT[media_type]}",
                "size": item["size"],
                "has_global": True,
            })

        return jsonify({
            "session_id": session_id,
            "backgrounds": backgrounds,
            "available_background_ids": loader.list_background_ids(),
            "character_media": character_media,
            "scene_characters": list(session.scene_manager.get_scene_characters()),
            "resources_dir": str(session_resources_dir(session_dir)),
            "backgrounds_dir": str(bg_dir),
        })

    @bp.route("/api/sessions/<session_id>/resources/backgrounds", methods=["POST"])
    def session_bg_upload(session_id: str):
        """上传/替换会话背景覆盖（同 ID 自动替换旧扩展名文件）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        bg_id = (request.form.get("bg_id") or "").strip()
        if not re.fullmatch(r"[a-z0-9_]+", bg_id):
            return json_error("bg_id 只能包含小写字母、数字、下划线")
        file = request.files.get("file")
        if not file or not file.filename:
            return json_error("需要上传 file")
        ext = Path(file.filename).suffix.lower()
        if ext not in _SESSION_BG_EXTS:
            return json_error("仅支持 png/jpg/jpeg/webp 图片")

        bg_dir = session.data_dir / "backgrounds"
        bg_dir.mkdir(parents=True, exist_ok=True)
        # 同 ID 自动替换：清掉旧扩展名的同 stem 文件
        for old in bg_dir.glob(f"{bg_id}.*"):
            if old.suffix.lower() in _SESSION_BG_EXTS and old.is_file():
                old.unlink()
        target = bg_dir / f"{bg_id}{ext}"
        file.save(str(target))
        return jsonify({
            "message": "上传成功",
            "type": "background",
            "key": bg_id,
            "name": target.name,
            "url": f"/api/sessions/{session_id}/backgrounds/{target.name}",
            "size": target.stat().st_size,
        }), 201

    @bp.route("/api/sessions/<session_id>/resources/backgrounds/<bg_id>", methods=["DELETE"])
    def session_bg_delete(session_id: str, bg_id: str):
        """删除会话背景覆盖（还原为全局背景）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        if not re.fullmatch(r"[a-z0-9_]+", bg_id):
            return json_error("bg_id 只能包含小写字母、数字、下划线")
        bg_dir = session.data_dir / "backgrounds"
        removed = False
        if bg_dir.is_dir():
            for f in bg_dir.glob(f"{bg_id}.*"):
                if f.suffix.lower() in _SESSION_BG_EXTS and f.is_file():
                    f.unlink()
                    removed = True
        if not removed:
            return json_error("该背景没有会话覆盖", 404)
        return jsonify({"message": "已删除，还原为全局背景", "key": bg_id})

    @bp.route("/api/sessions/<session_id>/resources/characters/<name>/<media_type>", methods=["POST"])
    def session_character_media_upload(session_id: str, name: str, media_type: str):
        """上传/替换会话角色形象覆盖（头像/立绘/卡面，仅影响本会话）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        from session_resources import (is_safe_entity_name, normalize_media_type,
                                       session_media_dir)
        if not is_safe_entity_name(name):
            return json_error("非法的角色名")
        try:
            media_type = normalize_media_type(media_type)
        except ValueError as e:
            return json_error(str(e))
        file = request.files.get("file")
        if not file or not file.filename:
            return json_error("需要上传 file")
        ext = Path(file.filename).suffix.lower()
        if ext not in _SESSION_BG_EXTS:
            return json_error("仅支持 png/jpg/jpeg/webp 图片")

        media_dir = session_media_dir(session.data_dir, name)
        media_dir.mkdir(parents=True, exist_ok=True)
        for old in media_dir.glob(f"{media_type}.*"):
            if old.suffix.lower() in _SESSION_BG_EXTS and old.is_file():
                old.unlink()
        target = media_dir / f"{media_type}{ext}"
        file.save(str(target))
        return jsonify({
            "message": "上传成功",
            "type": "character_media",
            "key": name,
            "media_type": media_type,
            "name": target.name,
            "size": target.stat().st_size,
        }), 201

    @bp.route("/api/sessions/<session_id>/resources/characters/<name>/<media_type>", methods=["DELETE"])
    def session_character_media_delete(session_id: str, name: str, media_type: str):
        """删除会话角色形象覆盖（还原为全局形象）。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        from session_resources import (is_safe_entity_name, normalize_media_type,
                                       session_media_dir)
        if not is_safe_entity_name(name):
            return json_error("非法的角色名")
        try:
            media_type = normalize_media_type(media_type)
        except ValueError as e:
            return json_error(str(e))
        media_dir = session_media_dir(session.data_dir, name)
        removed = False
        if media_dir.is_dir():
            for f in media_dir.glob(f"{media_type}.*"):
                if f.suffix.lower() in _SESSION_BG_EXTS and f.is_file():
                    f.unlink()
                    removed = True
            try:
                if not any(media_dir.iterdir()):
                    media_dir.rmdir()
            except OSError:
                pass
        if not removed:
            return json_error("该角色没有此类型的会话形象覆盖", 404)
        return jsonify({"message": "已删除，还原为全局形象", "key": name, "media_type": media_type})

    # ── 会话存档导入导出 ──

    @bp.route("/api/sessions/<session_id>/export", methods=["GET"])
    def session_export(session_id: str):
        """导出会话存档 zip（会话目录 + 依赖快照 + manifest），便于社区传播。"""
        from flask import send_file
        from session_export import export_session_zip

        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        session_dir = Path(session.data_dir)
        meta = {
            "name": session.name,
            "combat_mode": session.combat_mode,
            "plot_id": session.overlay.get_plot_id() or None,
            "player_identity": session.player_identity,
        }
        out_dir = tempfile.mkdtemp(prefix="sess_export_")
        out_path = Path(out_dir) / f"session-{session_id}.zip"
        try:
            export_session_zip(session_dir, meta, out_path)
            safe_name = f"session-{session.name}.zip".replace(" ", "_")
            resp = send_file(str(out_path), as_attachment=True, download_name=safe_name)
            resp.call_on_close(
                lambda: (out_path.exists() and out_path.unlink(missing_ok=True),
                         shutil.rmtree(out_dir, ignore_errors=True))
            )
            return resp
        except Exception as e:
            logger.exception("导出会话失败 %s", session_id)
            shutil.rmtree(out_dir, ignore_errors=True)
            return json_error(f"导出失败: {e}", 500)

    @bp.route("/api/sessions/import", methods=["POST"])
    def session_import():
        """导入会话存档 zip：还原依赖到全局库（幂等）、放置并注册会话。"""
        from session_export import import_session_zip

        file = request.files.get("file")
        if not file or not file.filename:
            return json_error("需要上传存档 zip 文件")
        ext = Path(file.filename).suffix.lower()
        if ext != ".zip":
            return json_error("仅支持 .zip 存档")

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        try:
            file.save(tmp_path)
            result = import_session_zip(Path(tmp_path), session_mgr)
            return jsonify(result), 201
        except ValueError as e:
            return json_error(str(e), 400)
        except Exception as e:
            logger.exception("导入会话失败")
            return json_error(f"导入失败: {e}", 500)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ── 剧情列表 ──

    @bp.route("/api/plots", methods=["GET"])
    def list_plots():
        """列出所有可用剧情（从 data/plots/ 子目录扫描）。"""
        plots_dir = _REPO_ROOT / "data" / "plots"
        if not plots_dir.is_dir():
            return jsonify([])

        plots = []
        for entry in sorted(plots_dir.iterdir()):
            if not entry.is_dir():
                continue
            md = entry / "index.md"
            if not md.is_file():
                continue
            try:
                with open(md, "r", encoding="utf-8") as f:
                    plot_data = frontmatter.load(f)
                meta = plot_data.metadata
                plots.append({
                    "id": meta.get("id", entry.name),
                    "name": meta.get("name", entry.name),
                    "category": meta.get("category", "main"),
                    "priority": meta.get("priority", 5),
                    "initial_characters": meta.get("initial_characters", []) if isinstance(meta.get("initial_characters", []), list) else [],
                    "trigger_location": meta.get("trigger", {}).get("location", []),
                    "trigger_character": meta.get("trigger", {}).get("character", []),
                })
            except Exception:
                continue
        plots.sort(key=lambda p: p["priority"], reverse=True)
        return jsonify(plots)

    # ── 玩家身份角色（player_identity=true 的角色卡） ──

    @bp.route("/api/player-identities", methods=["GET"])
    def list_player_identities():
        """返回所有标记为 player_identity=true 的角色卡摘要。"""
        chars_dir = _REPO_ROOT / "data" / "characters"
        identities = []
        if chars_dir.is_dir():
            for entry in sorted(chars_dir.iterdir()):
                if not entry.is_dir():
                    continue
                md = entry / "index.md"
                if not md.is_file():
                    continue
                try:
                    with open(md, "r", encoding="utf-8") as f:
                        data = frontmatter.load(f)
                    if data.metadata.get("player_identity"):
                        identities.append({
                            "id": entry.name,
                            "name": data.metadata.get("name", entry.name),
                            "summary": data.metadata.get("summary", ""),
                            "tags": data.metadata.get("tags", []),
                        })
                except Exception:
                    continue
        return jsonify(identities)

    @bp.route("/api/player-identities/<name>", methods=["PUT"])
    def save_player_identity(name: str):
        """保存/创建玩家身份角色（强制设置 frontmatter player_identity=true）。"""
        if not is_safe_entity_name(name):
            return json_error("非法的玩家身份名称", 400)
        data = request.json or {}
        metadata = data.get("metadata") or {}
        content = data.get("content", "")
        metadata["player_identity"] = True
        metadata.setdefault("name", name)

        char_dir = _REPO_ROOT / "data" / "characters" / name
        char_dir.mkdir(parents=True, exist_ok=True)
        md_path = char_dir / "index.md"

        # 合并现有 frontmatter（保留用户未传字段）
        if md_path.is_file():
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    existing = frontmatter.load(f)
                merged = dict(existing.metadata)
                merged.update(metadata)
                metadata = merged
                if not content and existing.content:
                    content = existing.content
            except Exception as e:
                logger.warning("读取现有玩家身份档案失败 %s: %s", name, e)

        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(frontmatter.Post(content, **metadata)))
                f.write("\n")
        except Exception as e:
            return json_error(f"保存失败: {e}", 500)

        # 更新 player_profile 缓存
        from player_profile import invalidate_profile_cache
        invalidate_profile_cache(name)

        return jsonify({
            "message": "已保存玩家身份",
            "id": name,
            "metadata": metadata,
        })

    @bp.route("/api/player-identities/<name>", methods=["DELETE"])
    def delete_player_identity(name: str):
        """删除玩家身份角色目录（仅当 player_identity=true 时允许）。"""
        if not is_safe_entity_name(name):
            return json_error("非法的玩家身份名称", 400)
        if name == "博士":
            return json_error("不能删除默认身份「博士」", 400)

        char_dir = _REPO_ROOT / "data" / "characters" / name
        md_path = char_dir / "index.md"
        if not md_path.is_file():
            return json_error("玩家身份不存在", 404)

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                data = frontmatter.load(f)
            if not data.metadata.get("player_identity"):
                return json_error("该角色未标记为玩家身份", 400)
        except Exception as e:
            return json_error(f"读取角色档案失败: {e}", 500)

        try:
            shutil.rmtree(char_dir)
        except Exception as e:
            return json_error(f"删除失败: {e}", 500)

        from player_profile import invalidate_profile_cache
        invalidate_profile_cache(name)

        return jsonify({"message": "已删除玩家身份", "id": name})

    @bp.route("/api/sessions/<session_id>/identity", methods=["PUT"])
    def set_session_identity(session_id: str):
        """设置会话当前使用的玩家身份。"""
        session = session_mgr.get_session(session_id)
        if not session:
            return json_error("会话不存在", 404)
        data = request.json or {}
        identity = str(data.get("identity", "") or "").strip() or "博士"
        ok = session_mgr.set_player_identity(session_id, identity)
        if not ok:
            return json_error("设置失败", 500)
        return jsonify({
            "message": "已更新玩家身份",
            "player_identity": session.player_identity,
        })

    app.register_blueprint(bp)
