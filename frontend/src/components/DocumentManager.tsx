import { useState, useEffect, useCallback, useRef } from "react";
import { useApi } from "../hooks/useApi";
import type { DocTreeCategory, DocTreeNode } from "../types";

interface ModalState {
  type: "createDoc" | "createFolder" | "rename" | "moveTo" | "delete";
  category: string;
  node?: DocTreeNode;
  parentPath?: string;
  oldName?: string;
}

interface ToastState {
  message: string;
  type: "success" | "error";
}

interface DocContent {
  content: string;
  hash: string;
  metadata: Record<string, any>;
}

// ── Helpers ──

function nodeKey(category: string, node?: DocTreeNode): string {
  if (!node) return category;
  return `${category}/${node.id || node.name}`;
}

function getNodePath(node: DocTreeNode): string {
  return node.id || node.name;
}

function getAllFolders(nodes: DocTreeNode[], prefix = ""): string[] {
  const result: string[] = [];
  for (const n of nodes) {
    if (n.type === "folder") {
      const path = prefix ? `${prefix}/${n.name}` : n.name;
      result.push(path);
      if (n.children) result.push(...getAllFolders(n.children, path));
    }
  }
  return result;
}

export default function DocumentManager() {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;

  // ── Tree ──
  const [tree, setTree] = useState<DocTreeCategory[]>([]);
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number;
    category: string;
    node?: DocTreeNode;
  } | null>(null);

  // ── Modal ──
  const [modal, setModal] = useState<ModalState | null>(null);
  const [modalValue, setModalValue] = useState("");
  const [modalTarget, setModalTarget] = useState("");

  // ── Editor ──
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>("");
  const [docContent, setDocContent] = useState<DocContent | null>(null);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ── Toast ──
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // ── Load tree ──

  const loadTree = useCallback(async (retries = 2) => {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const data: DocTreeCategory[] = await apiRef.current.getDocumentTree();
        setTree(data);
        setError("");
        return;
      } catch (err: any) {
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        } else {
          setError("加载文档树失败: " + err.message);
        }
      }
    }
  }, []);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  // ── Tree collapse ──

  const toggleCollapse = useCallback((key: string) => {
    setCollapsedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const isCollapsed = (key: string) => collapsedNodes.has(key);

  // ── Context menu ──

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, category: string, node?: DocTreeNode) => {
      e.preventDefault();
      e.stopPropagation();
      setContextMenu({ x: e.clientX, y: e.clientY, category, node });
    },
    []
  );

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  useEffect(() => {
    if (!contextMenu) return;
    const dismiss = () => setContextMenu(null);
    document.addEventListener("click", dismiss);
    // Also dismiss on scroll in the sidebar
    return () => document.removeEventListener("click", dismiss);
  }, [contextMenu]);

  // ── Editor ──

  const currentReq = useRef(0);

  const handleSelect = async (category: string, id: string) => {
    const reqId = ++currentReq.current;
    const path = `${category}/${id}`;
    setSelectedPath(path);
    setSelectedCategory(category);
    setEditing(false);
    setLoading(true);
    setError("");
    try {
      const content = await api.readDocument(category, id);
      if (reqId !== currentReq.current) return;
      setDocContent(content);
      setEditContent(content.content);
    } catch (err: any) {
      if (reqId !== currentReq.current) return;
      setError(err.message);
      setDocContent(null);
    } finally {
      if (reqId === currentReq.current) setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!selectedPath || !docContent) return;
    setLoading(true);
    setError("");
    try {
      const updated = await api.saveDocument(
        selectedCategory,
        docIdFromPath(selectedPath),
        editContent,
        docContent.metadata,
        docContent.hash
      );
      const fresh = await api.readDocument(selectedCategory, docIdFromPath(selectedPath));
      setDocContent(fresh);
      setEditContent(fresh.content);
      setEditing(false);
      showToast("文档已保存");
    } catch (err: any) {
      if (err.message.includes("hash") || err.message.includes("conflict")) {
        setError("保存冲突: 文档已被修改，请刷新后重试\n" + err.message);
      } else {
        setError("保存失败: " + err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  // ── Validation ──

  const validateName = (name: string): string | null => {
    if (name.includes("/") || name.includes("\\")) {
      return "名称不能包含 / 或 \\ 字符";
    }
    if (name.length === 0) {
      return "名称不能为空";
    }
    return null;
  };

  // ── Operations ──

  const doCreateDocument = async () => {
    const name = modalValue.trim();
    const v = validateName(name);
    if (v) { showToast(v, "error"); return; }
    const parentPath = modalTarget || "";
    const docId = parentPath ? `${parentPath}/${name}` : name;

    try {
      await api.createDocument(modal!.category, docId, "", { name });
      showToast(`文档 "${name}" 已创建`);
      setModal(null);
      setModalValue("");
      setModalTarget("");
      // Expand parent folder
      if (parentPath) {
        setCollapsedNodes((prev) => {
          const next = new Set(prev);
          next.delete(nodeKey(modal!.category, { name: parentPath.split("/").pop() || parentPath, type: "folder" }));
          return next;
        });
      }
      await loadTree();
    } catch (err: any) {
      showToast(err.message || "创建失败", "error");
    }
  };

  const doCreateFolder = async () => {
    const name = modalValue.trim();
    const v = validateName(name);
    if (v) { showToast(v, "error"); return; }
    const parentPath = modalTarget || "";
    const folderPath = parentPath ? `${parentPath}/${name}` : name;

    try {
      await api.createFolder(modal!.category, folderPath);
      showToast(`文件夹 "${name}" 已创建`);
      setModal(null);
      setModalValue("");
      setModalTarget("");
      await loadTree();
    } catch (err: any) {
      showToast(err.message || "创建失败", "error");
    }
  };

  const doRename = async () => {
    const newName = modalValue.trim();
    if (!modal?.node) return;
    if (newName === modal.oldName) return;
    const v = validateName(newName);
    if (v) { showToast(v, "error"); return; }
    const node = modal.node;
    const oldPath = getNodePath(node);
    const prefix = oldPath.includes("/") ? oldPath.substring(0, oldPath.lastIndexOf("/")) : "";
    const newPath = prefix ? `${prefix}/${newName}` : newName;
    const category = modal.category;

    try {
      if (node.type === "document") {
        await api.moveDocument(category, oldPath, newPath);
      } else {
        await api.moveFolder(category, oldPath, newPath);
      }
      showToast(`已重命名为 "${newName}"`);
      // If the renamed doc was open, update path
      if (selectedPath === `${category}/${oldPath}`) {
        setSelectedPath(`${category}/${newPath}`);
      }
      setModal(null);
      setModalValue("");
      await loadTree();
    } catch (err: any) {
      showToast(err.message || "重命名失败", "error");
    }
  };

  const doMove = async () => {
    if (!modal?.node || !modalTarget) return;
    const node = modal.node;
    const oldPath = getNodePath(node);
    const oldName = node.name;
    const newPath = modalTarget === "__root__"
      ? oldName
      : `${modalTarget}/${oldName}`;
    const category = modal.category;

    try {
      await api.moveDocument(category, oldPath, newPath);
      showToast(`已移动到 "${modalTarget === "__root__" ? "根目录" : modalTarget}"`);
      if (selectedPath === `${category}/${oldPath}`) {
        setSelectedPath(`${category}/${newPath}`);
      }
      setModal(null);
      setModalTarget("");
      await loadTree();
    } catch (err: any) {
      showToast(err.message || "移动失败", "error");
    }
  };

  const doDelete = async () => {
    if (!modal?.node) return;
    const node = modal.node;
    const path = getNodePath(node);
    const category = modal.category;

    try {
      if (node.type === "document") {
        await api.deleteDocument(category, path);
      } else {
        await api.deleteFolder(category, path);
      }
      showToast(`"${node.name}" 已删除`);
      if (selectedPath === `${category}/${path}`) {
        setSelectedPath(null);
        setDocContent(null);
      }
      setModal(null);
      await loadTree();
    } catch (err: any) {
      showToast(err.message || "删除失败", "error");
    }
  };

  const openModal = (
    type: ModalState["type"],
    category: string,
    node?: DocTreeNode,
    parentPath?: string
  ) => {
    setContextMenu(null);
    setModal({ type, category, node, parentPath, oldName: node?.name });
    setModalValue(node?.name || "");
    setModalTarget(parentPath || "");
  };

  // ── Render: tree node ──

  const renderTreeNode = (
    node: DocTreeNode,
    category: string,
    depth: number,
    parentPath: string
  ) => {
    const nodePath = parentPath ? `${parentPath}/${node.name}` : node.name;
    const key = nodeKey(category, node);
    const collapsed = isCollapsed(key);
    const isSelected = node.type === "document" && selectedPath === `${category}/${node.id}`;

    if (node.type === "folder") {
      return (
        <div key={key}>
          <div
            className="group flex items-center gap-1 cursor-pointer rounded text-sm hover:bg-gray-700/50 select-none"
            style={{ paddingLeft: depth * 16 + 4 }}
            onClick={() => toggleCollapse(key)}
            onContextMenu={(e) => handleContextMenu(e, category, node)}
          >
            <span className="w-4 text-center text-gray-500 shrink-0">
              {collapsed ? "▶" : "▼"}
            </span>
            <span className="w-4 text-center shrink-0">
              {collapsed ? "📁" : "📂"}
            </span>
            <span className="text-gray-300 truncate">{node.name}</span>
          </div>
          {!collapsed && node.children && (
            <div>
              {node.children.map((child) =>
                renderTreeNode(child, category, depth + 1, nodePath)
              )}
            </div>
          )}
        </div>
      );
    }

    // Document node
    return (
      <div key={key}>
        <div
          className={`group flex items-center gap-1 cursor-pointer rounded text-sm transition-colors select-none ${
            isSelected
              ? "bg-blue-600/20 text-blue-300"
              : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
          }`}
          style={{ paddingLeft: depth * 16 + 4 }}
          onClick={() => handleSelect(category, node.id!)}
          onContextMenu={(e) => handleContextMenu(e, category, node)}
        >
          <span className="w-4 text-center shrink-0" />
          <span className="w-4 text-center text-gray-500 shrink-0">📄</span>
          <span className="truncate">{node.name}</span>
        </div>
      </div>
    );
  };

  // ── Render: category ──

  const renderCategory = (cat: DocTreeCategory) => {
    const key = nodeKey(cat.category);
    const collapsed = isCollapsed(key);
    const hasChildren = cat.children && cat.children.length > 0;

    return (
      <div key={cat.category} className="mb-1">
        <div
          className="group flex items-center gap-1 cursor-pointer rounded text-xs font-semibold text-gray-500 uppercase tracking-wider py-1 hover:text-gray-300 select-none"
          onClick={() => toggleCollapse(key)}
          onContextMenu={(e) => handleContextMenu(e, cat.category)}
        >
          <span className="w-3 text-center shrink-0">
            {collapsed ? "▶" : "▼"}
          </span>
          <span className="truncate">{cat.category}</span>
        </div>
        {!collapsed && (
          <div>
            {hasChildren
              ? cat.children!.map((child) =>
                  renderTreeNode(child, cat.category, 1, "")
                )
              : (
                <p
                  className="text-xs text-gray-600 italic select-none"
                  style={{ paddingLeft: 20 }}
                >
                  (空)
                </p>
              )}
          </div>
        )}
      </div>
    );
  };

  // ── Helpers ──

  const docIdFromPath = (path: string) => {
    const idx = path.indexOf("/");
    return idx >= 0 ? path.substring(idx + 1) : path;
  };

  const getOpenDocNode = (): DocTreeNode | undefined => {
    if (!selectedPath || !selectedCategory) return undefined;
    const cat = tree.find((c) => c.category === selectedCategory);
    if (!cat?.children) return undefined;
    const docId = docIdFromPath(selectedPath);
    const find = (nodes: DocTreeNode[]): DocTreeNode | undefined => {
      for (const n of nodes) {
        if (n.type === "document" && n.id === docId) return n;
        if (n.type === "folder" && n.children) {
          const found = find(n.children);
          if (found) return found;
        }
      }
      return undefined;
    };
    return find(cat.children);
  };

  const getFoldersForCategory = (category: string): string[] => {
    const cat = tree.find((c) => c.category === category);
    if (!cat?.children) return [];
    return getAllFolders(cat.children);
  };

  // ── Cleanup on unmount ──
  useEffect(() => {
    return () => clearTimeout(toastTimer.current);
  }, []);

  // ══════════════════════════════════════════════════════
  //  Render
  // ══════════════════════════════════════════════════════

  return (
    <div className="flex h-full">
      {/* ── Tree sidebar ── */}
      <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 shrink-0" id="doc-tree-sidebar">
        <div className="flex items-center justify-between mb-3">
          <h2 className="panel-title mb-0 text-sm">文档</h2>
          <button
            onClick={() => loadTree()}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            刷新
          </button>
        </div>
        {error && !selectedPath && (
          <p className="text-red-400 text-xs mb-2">{error}</p>
        )}
        {tree.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
        ) : (
          tree.map((cat) => renderCategory(cat))
        )}
      </div>

      {/* ── Editor panel ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedPath ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p>选择左侧文档查看或编辑</p>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p>加载中...</p>
          </div>
        ) : (
          <>
            {/* Toolbar */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
              <h2 className="text-sm font-medium text-gray-300 truncate max-w-[50%]">
                {selectedPath}
              </h2>
              <div className="flex gap-2">
                {editing ? (
                  <>
                    <button
                      onClick={handleSave}
                      disabled={loading}
                      className="btn-primary text-xs px-3 py-1"
                    >
                      {loading ? "保存中..." : "保存"}
                    </button>
                    <button
                      onClick={() => {
                        setEditing(false);
                        setEditContent(docContent?.content || "");
                      }}
                      className="btn-ghost text-xs px-3 py-1"
                    >
                      取消
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => setEditing(true)}
                      className="btn-ghost text-xs px-3 py-1"
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => {
                        const node = getOpenDocNode();
                        if (node) openModal("rename", selectedCategory, node);
                      }}
                      className="btn-ghost text-xs px-3 py-1 text-gray-500"
                      title="重命名"
                    >
                      重命名
                    </button>
                    <button
                      onClick={() => {
                        const node = getOpenDocNode();
                        if (node) openModal("moveTo", selectedCategory, node);
                      }}
                      className="btn-ghost text-xs px-3 py-1 text-gray-500"
                      title="移动"
                    >
                      移动
                    </button>
                    <button
                      onClick={() => {
                        const node = getOpenDocNode();
                        if (node) openModal("delete", selectedCategory, node);
                      }}
                      className="btn-ghost text-xs px-3 py-1 text-red-400 hover:text-red-300"
                      title="删除"
                    >
                      删除
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="mx-4 mt-3 p-2 bg-red-900/30 border border-red-700/30 rounded text-xs text-red-400">
                {error}
              </div>
            )}

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {editing ? (
                <textarea
                  className="input font-mono text-sm h-full resize-none"
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                />
              ) : (
                <pre className="text-sm text-gray-300 font-mono whitespace-pre-wrap">
                  {docContent?.content || "（空文档）"}
                </pre>
              )}
            </div>

            {/* Metadata footer */}
            {docContent?.metadata && Object.keys(docContent.metadata).length > 0 && (
              <div className="px-4 py-2 border-t border-gray-700 text-xs text-gray-500">
                {Object.entries(docContent.metadata).map(([k, v]) => (
                  <span key={k} className="mr-4">
                    {k}: {String(v)}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Context menu ── */}
      {contextMenu && (
        <div
          className="fixed z-50 min-w-[150px] bg-gray-800 border border-gray-600 rounded-lg shadow-xl py-1 text-sm"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* If it's a category (no node) */}
          {!contextMenu.node && (
            <>
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("createDoc", contextMenu.category, undefined, "")}
              >
                + 新建文档
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("createFolder", contextMenu.category, undefined, "")}
              >
                + 新建文件夹
              </button>
            </>
          )}

          {/* Folder node */}
          {contextMenu.node?.type === "folder" && (
            <>
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("createDoc", contextMenu.category, undefined, getNodePath(contextMenu.node!))}
              >
                + 新建文档
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("createFolder", contextMenu.category, undefined, getNodePath(contextMenu.node!))}
              >
                + 新建文件夹
              </button>
              <hr className="border-gray-700 my-1" />
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("rename", contextMenu.category, contextMenu.node)}
              >
                重命名
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-red-400 hover:bg-gray-700"
                onClick={() => openModal("delete", contextMenu.category, contextMenu.node)}
              >
                删除
              </button>
            </>
          )}

          {/* Document node */}
          {contextMenu.node?.type === "document" && (
            <>
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("rename", contextMenu.category, contextMenu.node)}
              >
                重命名
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                onClick={() => openModal("moveTo", contextMenu.category, contextMenu.node)}
              >
                移动到...
              </button>
              <hr className="border-gray-700 my-1" />
              <button
                className="w-full text-left px-3 py-1.5 text-red-400 hover:bg-gray-700"
                onClick={() => openModal("delete", contextMenu.category, contextMenu.node)}
              >
                删除
              </button>
            </>
          )}
        </div>
      )}

      {/* ── Modal overlay ── */}
      {modal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => { setModal(null); setModalValue(""); setModalTarget(""); }}
        >
          <div
            className="bg-gray-800 border border-gray-600 rounded-lg shadow-xl p-5 w-[400px] max-w-[90vw]"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Create Document */}
            {modal.type === "createDoc" && (
              <>
                <h3 className="text-base font-medium mb-4">新建文档</h3>
                {modal.parentPath && (
                  <p className="text-xs text-gray-500 mb-2">
                    位置: {modal.category}/{modal.parentPath}
                  </p>
                )}
                <label className="block text-xs text-gray-400 mb-1">文档名称（不含 .md）</label>
                <input
                  className="input text-sm w-full"
                  value={modalValue}
                  onChange={(e) => setModalValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") doCreateDocument(); if (e.key === "Escape") { setModal(null); setModalValue(""); } }}
                  autoFocus
                  placeholder="例如: 新角色"
                />
                <div className="flex gap-2 justify-end mt-4">
                  <button
                    className="btn-ghost text-xs px-4 py-1"
                    onClick={() => { setModal(null); setModalValue(""); }}
                  >
                    取消
                  </button>
                  <button
                    className="btn-primary text-xs px-4 py-1"
                    onClick={doCreateDocument}
                    disabled={!modalValue.trim()}
                  >
                    创建
                  </button>
                </div>
              </>
            )}

            {/* Create Folder */}
            {modal.type === "createFolder" && (
              <>
                <h3 className="text-base font-medium mb-4">新建文件夹</h3>
                {modal.parentPath && (
                  <p className="text-xs text-gray-500 mb-2">
                    位置: {modal.category}/{modal.parentPath}
                  </p>
                )}
                <label className="block text-xs text-gray-400 mb-1">文件夹名称</label>
                <input
                  className="input text-sm w-full"
                  value={modalValue}
                  onChange={(e) => setModalValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") doCreateFolder(); if (e.key === "Escape") { setModal(null); setModalValue(""); } }}
                  autoFocus
                  placeholder="例如: 新分类"
                />
                <div className="flex gap-2 justify-end mt-4">
                  <button
                    className="btn-ghost text-xs px-4 py-1"
                    onClick={() => { setModal(null); setModalValue(""); }}
                  >
                    取消
                  </button>
                  <button
                    className="btn-primary text-xs px-4 py-1"
                    onClick={doCreateFolder}
                    disabled={!modalValue.trim()}
                  >
                    创建
                  </button>
                </div>
              </>
            )}

            {/* Rename */}
            {modal.type === "rename" && (
              <>
                <h3 className="text-base font-medium mb-4">重命名</h3>
                <p className="text-xs text-gray-500 mb-2">
                  原名: {modal.oldName}
                </p>
                <label className="block text-xs text-gray-400 mb-1">新名称</label>
                <input
                  className="input text-sm w-full"
                  value={modalValue}
                  onChange={(e) => setModalValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") doRename(); if (e.key === "Escape") { setModal(null); setModalValue(""); } }}
                  autoFocus
                  placeholder="输入新名称"
                />
                <div className="flex gap-2 justify-end mt-4">
                  <button
                    className="btn-ghost text-xs px-4 py-1"
                    onClick={() => { setModal(null); setModalValue(""); }}
                  >
                    取消
                  </button>
                  <button
                    className="btn-primary text-xs px-4 py-1"
                    onClick={doRename}
                    disabled={!modalValue.trim() || modalValue.trim() === modal.oldName}
                  >
                    确认
                  </button>
                </div>
              </>
            )}

            {/* Move To */}
            {modal.type === "moveTo" && (
              <>
                <h3 className="text-base font-medium mb-4">移动到</h3>
                <p className="text-xs text-gray-500 mb-2">
                  文档: {modal.oldName}
                </p>
                <label className="block text-xs text-gray-400 mb-1">目标文件夹</label>
                <select
                  className="input text-sm w-full"
                  value={modalTarget}
                  onChange={(e) => setModalTarget(e.target.value)}
                  autoFocus
                >
                  <option value="__root__">(根目录)</option>
                  {getFoldersForCategory(modal.category).map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
                <div className="flex gap-2 justify-end mt-4">
                  <button
                    className="btn-ghost text-xs px-4 py-1"
                    onClick={() => { setModal(null); setModalTarget(""); }}
                  >
                    取消
                  </button>
                  <button
                    className="btn-primary text-xs px-4 py-1"
                    onClick={doMove}
                    disabled={!modalTarget}
                  >
                    移动
                  </button>
                </div>
              </>
            )}

            {/* Delete confirmation */}
            {modal.type === "delete" && (
              <>
                <h3 className="text-base font-medium mb-4 text-red-400">确认删除</h3>
                <p className="text-sm text-gray-300 mb-1">
                  确定要删除 "{modal.oldName}" 吗？
                </p>
                {modal.node?.type === "folder" && modal.node.children && modal.node.children.length > 0 && (
                  <p className="text-xs text-yellow-400 mt-2">
                    此文件夹非空，包含 {modal.node.children.length} 个项目。请先移走或删除文件夹内容。
                  </p>
                )}
                <div className="flex gap-2 justify-end mt-4">
                  <button
                    className="btn-ghost text-xs px-4 py-1"
                    onClick={() => setModal(null)}
                  >
                    取消
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-700 text-white text-xs px-4 py-1 rounded"
                    onClick={doDelete}
                    disabled={modal.node?.type === "folder" && modal.node.children && modal.node.children.length > 0}
                  >
                    删除
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Toast ── */}
      {toast && (
        <div
          className={`fixed bottom-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg text-sm transition-all ${
            toast.type === "error"
              ? "bg-red-600 text-white"
              : "bg-green-700 text-white"
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
