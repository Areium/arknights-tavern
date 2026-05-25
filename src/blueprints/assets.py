"""
Assets blueprint — 静态资源服务。
"""

from pathlib import Path
from flask import Blueprint, jsonify, send_from_directory

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

    app.register_blueprint(bp)


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def _list_entity_images(doc_mgr):
    """扫描所有实体文件夹下的图片文件。"""
    import os
    import frontmatter

    categories = doc_mgr.list_categories()
    result = []

    for cat_meta in categories:
        cat = doc_mgr.get_category(cat_meta["id"])
        if not cat or not os.path.isdir(cat.directory):
            continue
        cat_dir = cat.directory

        for root, dirs, _files in os.walk(cat_dir):
            for d in sorted(dirs):
                d_full = os.path.join(root, d)
                index_md = os.path.join(d_full, "index.md")
                if not os.path.isfile(index_md):
                    continue
                images = []
                for f in sorted(os.listdir(d_full)):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in _IMAGE_EXTS and f != "index.md":
                        entity_rel = os.path.relpath(d_full, cat_dir).replace("\\", "/")
                        images.append({
                            "name": f,
                            "path": f"{cat['id']}/{entity_rel}/{f}",
                            "url": f"/api/assets/{cat['id']}/{entity_rel}/{f}",
                        })

                if images:
                    entity_name = d
                    try:
                        with open(index_md, "r", encoding="utf-8") as fh:
                            meta = frontmatter.load(fh).metadata
                        entity_name = meta.get("name", d)
                    except Exception:
                        pass

                    result.append({
                        "category": cat["id"],
                        "entity": d,
                        "entity_name": entity_name,
                        "images": images,
                    })

    return result
