"""
Assets blueprint — 静态资源服务。
"""

from pathlib import Path
from urllib.parse import quote
from flask import Blueprint, jsonify, request, send_from_directory

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def register(app, managers):
    bp = Blueprint("assets", __name__)
    doc_mgr = managers["document"]

    @bp.route("/api/assets/images", methods=["GET"])
    def list_asset_images():
        return jsonify(_list_entity_images(doc_mgr))

    @bp.route("/api/assets/data-dir", methods=["GET"])
    def get_data_dir():
        return jsonify({"path": str(_REPO_ROOT / "data")})

    @bp.route("/api/assets/<category>/<path:filename>", methods=["GET"])
    def serve_asset(category, filename):
        import os as _os
        cat = doc_mgr.get_category(category)
        if not cat:
            return jsonify({"error": f"未知类别: {category}"}), 404
        filepath = _os.path.join(cat.directory, filename)
        if not _os.path.isfile(filepath):
            return jsonify({"error": "文件不存在"}), 404
        directory = _os.path.dirname(filepath)
        basename = _os.path.basename(filepath)
        return send_from_directory(directory, basename)

    @bp.route("/api/assets/<category>/upload", methods=["POST"])
    def upload_asset(category):
        """上传图片到分类/实体目录。"""
        import os as _os

        cat = doc_mgr.get_category(category)
        if not cat:
            return jsonify({"error": f"未知类别: {category}"}), 404

        if "file" not in request.files:
            return jsonify({"error": "缺少上传文件"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "文件名为空"}), 400

        ext = _os.path.splitext(file.filename)[1].lower()
        if ext not in _IMAGE_EXTS:
            return jsonify({"error": f"不支持的文件格式: {ext}"}), 400

        subdir = request.form.get("subdir", "").strip()
        if ".." in subdir or subdir.startswith("/") or subdir.startswith("\\"):
            return jsonify({"error": "无效的子目录路径"}), 400

        target_dir = _os.path.join(cat.directory, subdir) if subdir else cat.directory
        _os.makedirs(target_dir, exist_ok=True)

        filepath = _os.path.join(target_dir, file.filename)
        if _os.path.exists(filepath):
            return jsonify({"error": f"文件已存在: {file.filename}"}), 409

        file.save(filepath)
        file_stat = _os.stat(filepath)
        entity_rel = _os.path.relpath(target_dir, cat.directory).replace("\\", "/")
        path_key = f"{category}/{entity_rel}/{file.filename}" if entity_rel != "." else f"{category}/{file.filename}"

        return jsonify({
            "message": "上传成功",
            "name": file.filename,
            "path": path_key,
            "url": f"/api/assets/{quote(path_key, safe='/')}",
            "size": file_stat.st_size,
        }), 201

    @bp.route("/api/assets/<category>/<path:filename>", methods=["DELETE"])
    def delete_asset(category, filename):
        """删除指定图片资产。"""
        import os as _os

        cat = doc_mgr.get_category(category)
        if not cat:
            return jsonify({"error": f"未知类别: {category}"}), 404

        # 路径穿越防护
        filepath = _os.path.join(cat.directory, filename.replace("\\", "/"))
        real_base = _os.path.realpath(cat.directory)
        real_file = _os.path.realpath(filepath)
        if not real_file.startswith(real_base + _os.sep) and real_file != real_base:
            return jsonify({"error": "无效的文件路径"}), 403

        if not _os.path.isfile(filepath):
            return jsonify({"error": "文件不存在"}), 404

        ext = _os.path.splitext(filepath)[1].lower()
        if ext not in _IMAGE_EXTS:
            return jsonify({"error": "不允许删除非图片文件"}), 403

        _os.remove(filepath)
        return jsonify({"message": "已删除", "path": f"{category}/{filename}"})

    @bp.route("/api/assets/<category>/<path:entity>/default-image", methods=["GET"])
    def get_default_image(category, entity):
        """读取实体的默认头像/立绘设置。"""
        import os as _os
        import frontmatter as _fm

        cat = doc_mgr.get_category(category)
        if not cat:
            return jsonify({"error": f"未知类别: {category}"}), 404

        index_md = _os.path.join(cat.directory, entity, "index.md")
        if not _os.path.isfile(index_md):
            return jsonify({"error": "实体不存在"}), 404

        try:
            with open(index_md, "r", encoding="utf-8") as f:
                meta = _fm.load(f).metadata
            crop = None
            keys = ("card_face_crop_x", "card_face_crop_y", "card_face_crop_w", "card_face_crop_h")
            if all(k in meta for k in keys):
                try:
                    crop = {
                        "x": float(meta["card_face_crop_x"]),
                        "y": float(meta["card_face_crop_y"]),
                        "w": float(meta["card_face_crop_w"]),
                        "h": float(meta["card_face_crop_h"]),
                    }
                except (ValueError, TypeError):
                    crop = None
            return jsonify({
                "default_avatar": meta.get("default_avatar", ""),
                "default_skin": meta.get("default_skin", ""),
                "card_face": meta.get("card_face", ""),
                "card_face_crop": crop,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/assets/<category>/<path:entity>/default-image", methods=["PUT"])
    def set_default_image(category, entity):
        """设置实体的默认头像/立绘。写入 index.md frontmatter。"""
        import os as _os
        import frontmatter as _fm

        cat = doc_mgr.get_category(category)
        if not cat:
            return jsonify({"error": f"未知类别: {category}"}), 404

        index_md = _os.path.join(cat.directory, entity, "index.md")
        if not _os.path.isfile(index_md):
            return jsonify({"error": "实体不存在"}), 404

        data = request.json or {}
        img_type = data.get("type", "").strip()
        filename = data.get("filename", "").strip()

        if img_type not in ("avatar", "skin", "card_face"):
            return jsonify({"error": "type 必须为 'avatar'、'skin' 或 'card_face'"}), 400

        if img_type == "card_face":
            field = "card_face"
        else:
            field = f"default_{img_type}"

        # card_face: 将文件复制到 card_face/ 目录（如果不在其中）
        if img_type == "card_face":
            import shutil as _shutil
            entity_dir = _os.path.dirname(index_md)
            card_face_dir = _os.path.join(entity_dir, "card_face")
            dest = _os.path.join(card_face_dir, filename)
            src_path = None
            for sub in ("avatar", "skin"):
                candidate = _os.path.join(entity_dir, sub, filename)
                if _os.path.isfile(candidate):
                    src_path = candidate
                    break
            if not src_path:
                candidate = _os.path.join(entity_dir, filename)
                if _os.path.isfile(candidate):
                    src_path = candidate
            if src_path and src_path != dest:
                _os.makedirs(card_face_dir, exist_ok=True)
                _shutil.copy2(src_path, dest)

        try:
            with open(index_md, "r", encoding="utf-8") as f:
                post = _fm.load(f)
            post.metadata[field] = filename

            # card_face 可附带裁剪参数
            if img_type == "card_face":
                crop = data.get("crop")
                if crop and isinstance(crop, dict):
                    post.metadata["card_face_crop_x"] = crop.get("x", 0)
                    post.metadata["card_face_crop_y"] = crop.get("y", 0)
                    post.metadata["card_face_crop_w"] = crop.get("w", 100)
                    post.metadata["card_face_crop_h"] = crop.get("h", 100)
                elif "crop" in data and data["crop"] is None:
                    # 仅当明确传入 crop=null 时清除裁剪
                    for k in ("card_face_crop_x", "card_face_crop_y", "card_face_crop_w", "card_face_crop_h"):
                        post.metadata.pop(k, None)

            with open(index_md, "w", encoding="utf-8") as f:
                f.write(_fm.dumps(post))
            return jsonify({"message": "已更新", "field": field, "filename": filename})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    app.register_blueprint(bp)


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def _list_entity_images(doc_mgr):
    """递归扫描所有实体文件夹及其子目录下的图片文件。"""
    import os
    import frontmatter

    categories = doc_mgr.list_categories()
    result = []

    for cat_meta in categories:
        cat_id = cat_meta["id"]
        cat = doc_mgr.get_category(cat_id)
        if not cat or not os.path.isdir(cat.directory):
            continue
        cat_dir = cat.directory

        # 收集该分类下所有实体目录（含 index.md 的目录）
        entity_dirs: dict[str, str] = {}  # dir_path -> entity_name
        for root, dirs, _files in os.walk(cat_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            index_md = os.path.join(root, "index.md")
            if os.path.isfile(index_md):
                entity_name = os.path.basename(root)
                try:
                    with open(index_md, "r", encoding="utf-8") as fh:
                        meta = frontmatter.load(fh).metadata
                    entity_name = meta.get("name", entity_name)
                except Exception:
                    pass
                entity_dirs[root] = entity_name

        # 递归扫描每个实体目录内的所有图片（包括子目录 avatar/、skin/ 等）
        for entity_root, entity_name in entity_dirs.items():
            images = []
            for walk_root, walk_dirs, walk_files in os.walk(entity_root):
                walk_dirs[:] = [d for d in walk_dirs if not d.startswith(".") and d != "spine"]
                for f in sorted(walk_files):
                    ext = os.path.splitext(f)[1].lower()
                    if ext not in _IMAGE_EXTS:
                        continue
                    filepath = os.path.join(walk_root, f)
                    file_stat = os.stat(filepath)
                    inner_rel = os.path.relpath(walk_root, entity_root).replace("\\", "/")
                    entity_rel = os.path.relpath(entity_root, cat_dir).replace("\\", "/")
                    if inner_rel == ".":
                        path_key = f"{cat_id}/{entity_rel}/{f}"
                    else:
                        path_key = f"{cat_id}/{entity_rel}/{inner_rel}/{f}"
                    images.append({
                        "name": f,
                        "path": path_key,
                        "url": f"/api/assets/{quote(path_key, safe='/')}",
                        "size": file_stat.st_size,
                        "subdir": inner_rel if inner_rel != "." else "",
                    })

            if images:
                result.append({
                    "category": cat_id,
                    "entity": os.path.relpath(entity_root, cat_dir).replace("\\", "/"),
                    "entity_name": entity_name,
                    "images": images,
                })

    return result
