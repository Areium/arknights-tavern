"""
Arknight-txt API 服务 (Phase 2 重构版 — Blueprint 架构)

架构：
- Flask app factory 模式：create_app() 创建并配置 app 实例
- Manager 层：全局共享（LLMBackendManager, WikiManager, DocumentManager, SessionManager）
- Blueprint 层：按功能域拆分路由（sessions, chat, scene, combat, documents, index, llm, wiki, environment, assets, worldbook, memories, status）
- Service 层：业务逻辑抽取到 services/ 目录
"""

import os
import sys
import logging

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Flask
from flask_cors import CORS

from llm_backend_manager import LLMBackendManager
from session_manager import SessionManager
from document_manager import DocumentManager
from wiki_manager import WikiManager
from combat_session import CombatTestSessionManager
from world_book import WorldBookManager

logger = logging.getLogger(__name__)


def create_app():
    """创建并配置 Flask 应用（factory 模式）。"""
    app = Flask(__name__)
    CORS(app)

    # ── 全局 Manager 实例 ──
    managers = {
        "llm_backend": LLMBackendManager(),
        "wiki": WikiManager(),
        "document": DocumentManager(),
        "combat_test": CombatTestSessionManager(),
        "worldbook": WorldBookManager(),
    }
    managers["session"] = SessionManager(
        managers["llm_backend"], wiki_manager=managers["wiki"],
        worldbook_manager=managers["worldbook"],
    )

    # ── Hook 管道 ──
    from hooks.pipeline import HookPipeline
    from hooks.attribute_roll import AttributeRollHook
    from hooks.wiki_prefetch import WikiPreFetchHook
    from services.attribute_loader import AttributeLoader

    hook_pipeline = HookPipeline()
    hook_pipeline.register(AttributeRollHook(AttributeLoader()))
    hook_pipeline.register(WikiPreFetchHook())
    managers["hook_pipeline"] = hook_pipeline

    # ── 注册所有 Blueprints ──
    from blueprints.status import register as reg_status
    from blueprints.sessions import register as reg_sessions
    from blueprints.chat import register as reg_chat
    from blueprints.scene import register as reg_scene
    from blueprints.combat import register as reg_combat
    from blueprints.combat_nodes import register as reg_combat_nodes
    from blueprints.documents import register as reg_documents
    from blueprints.index import register as reg_index
    from blueprints.llm import register as reg_llm
    from blueprints.wiki import register as reg_wiki
    from blueprints.environment import register as reg_environment
    from blueprints.assets import register as reg_assets
    from blueprints.memories import register as reg_memories
    from blueprints.cards import register as reg_cards
    from blueprints.worldbook import register as reg_worldbook

    for reg in [
        reg_status,
        reg_sessions,
        reg_chat,
        reg_scene,
        reg_combat,
        reg_combat_nodes,
        reg_documents,
        reg_index,
        reg_llm,
        reg_wiki,
        reg_environment,
        reg_assets,
        reg_memories,
        reg_cards,
        reg_worldbook,
    ]:
        reg(app, managers)

    # 将 managers 附加到 app 上，供 main() 和测试使用
    app._managers = managers

    return app


# ── 模块级 app 变量 ──
app = create_app()


def main():
    """启动 API 服务。"""
    # 基础日志配置（logging_setup 模块移除后恢复）：让各模块 logger 输出到 stderr
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    managers = app._managers
    llm_backend = managers["llm_backend"]
    doc_manager = managers["document"]
    wiki_manager = managers["wiki"]

    status = llm_backend.get_status()
    print(f"\n  API 服务启动: http://{host}:{port}")
    print(f"  LLM 后端: {status['primary']['name'] if status['primary'] else '无'} / "
          f"备用: {status['fallback']['name'] if status['fallback'] else '无'}")
    print(f"  文档类别: {len(doc_manager.list_categories())} 个")

    # 检查摘要缺失情况
    total_docs = len(wiki_manager._catalog)
    missing = sum(1 for entry in wiki_manager._catalog.values()
                  if wiki_manager._needs_summary(entry["path"]))
    if total_docs > 0 and missing / total_docs > 0.5:
        print(f"  Wiki 摘要: {total_docs - missing}/{total_docs} 有摘要，"
              f"{missing} 篇缺失。建议运行 POST /api/wiki/backfill-summaries")
    print()

    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    main()
