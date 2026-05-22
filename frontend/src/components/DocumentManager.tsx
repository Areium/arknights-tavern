import { useState, useEffect, useCallback, useRef } from "react";
import { useApi } from "../hooks/useApi";

interface TreeNode {
  name: string;
  type: "category" | "document";
  path?: string;
  children?: TreeNode[];
}

interface DocContent {
  content: string;
  hash: string;
  metadata: Record<string, any>;
}

export default function DocumentManager() {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;

  const [tree, setTree] = useState<TreeNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [docContent, setDocContent] = useState<DocContent | null>(null);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadTree = useCallback(async (retries = 2): Promise<void> => {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const data: any[] = await apiRef.current.getDocumentTree();
        const nodes: TreeNode[] = data.map((cat: any) => ({
          name: cat.category || cat.category_info?.id || "unknown",
          type: "category" as const,
          children: (cat.documents || []).map((doc: any) => ({
            name: doc.title || doc.id,
            type: "document" as const,
            path: `${cat.category || cat.category_info?.id}/${doc.id}`,
          })),
        }));
        setTree(nodes);
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
  }, []);

  const currentReq = useRef(0);

  const handleSelect = async (path: string) => {
    const reqId = ++currentReq.current;
    setSelectedPath(path);
    setEditing(false);
    setLoading(true);
    setError("");
    try {
      const parts = path.split("/");
      if (parts.length < 2) throw new Error("Invalid path");
      const category = parts[0];
      const id = parts.slice(1).join("/");
      const content = await api.readDocument(category, id);
      if (reqId !== currentReq.current) return; // 废弃旧请求的响应
      setDocContent(content);
      setEditContent(content.content);
    } catch (err: any) {
      if (reqId !== currentReq.current) return;
      setError(err.message);
      setDocContent(null);
    } finally {
      if (reqId === currentReq.current) {
        setLoading(false);
      }
    }
  };

  const handleSave = async () => {
    if (!selectedPath || !docContent) return;
    setLoading(true);
    setError("");
    try {
      const parts = selectedPath.split("/");
      const category = parts[0];
      const id = parts.slice(1).join("/");
      const updated = await api.saveDocument(
        category,
        id,
        editContent,
        docContent.metadata,
        docContent.hash
      );
      // Re-read to get full content (save endpoint only returns {hash, path})
      const fresh = await api.readDocument(category, id);
      setDocContent(fresh);
      setEditContent(fresh.content);
      setEditing(false);
    } catch (err: any) {
      if (err.message.includes("hash") || err.message.includes("conflict")) {
        setError(
          "保存冲突: 文档已被修改，请刷新后重试\n" + err.message
        );
      } else {
        setError("保存失败: " + err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const renderTree = (nodes: TreeNode[], level = 0) => {
    return nodes.map((node) => (
      <div key={node.name + (node.path || "")}>
        {node.type === "category" ? (
          <div
            className="text-xs font-semibold text-gray-500 uppercase tracking-wider mt-2 mb-1"
            style={{ paddingLeft: level * 16 + 8 }}
          >
            {node.name}
          </div>
        ) : (
          <button
            onClick={() => node.path && handleSelect(node.path)}
            className={`w-full text-left px-3 py-1 text-sm rounded transition-colors ${
              selectedPath === node.path
                ? "bg-blue-600/20 text-blue-300"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
            }`}
            style={{ paddingLeft: level * 16 + 8 }}
          >
            {node.name}
          </button>
        )}
        {node.children && renderTree(node.children, level + 1)}
      </div>
    ));
  };

  return (
    <div className="flex h-full">
      {/* Tree sidebar */}
      <div className="w-64 border-r border-gray-700 overflow-y-auto p-3 shrink-0">
        <div className="flex items-center justify-between mb-3">
          <h2 className="panel-title mb-0">文档</h2>
          <button
            onClick={loadTree}
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
          renderTree(tree)
        )}
      </div>

      {/* Editor */}
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
              <h2 className="text-sm font-medium">{selectedPath}</h2>
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
                  <button
                    onClick={() => setEditing(true)}
                    className="btn-ghost text-xs px-3 py-1"
                  >
                    编辑
                  </button>
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

            {/* Metadata */}
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
    </div>
  );
}
