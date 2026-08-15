import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useApi } from "../hooks/useApi";
import { useAppStore } from "../stores/appStore";
import type { DocTreeCategory, DocTreeNode, SkinCrop } from "../types";
import MarkdownRenderer from "./MarkdownRenderer";
import CropModal from "./assets/CropModal";
import CardEditor from "./combat/CardEditor";

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

const CATEGORY_LABELS: Record<string, string> = {
  characters: "角色",
  factions: "势力",
  items: "物品",
  locations: "地点",
  plots: "剧情",
  races: "种族",
  classes: "职业",
  enemies: "叙事敌人",
  combat_enemies: "战斗敌人",
  combat_encounters: "遭遇战",
  weather: "天气",
  world: "世界观",
  attributes: "属性",
  rules: "规则",
};

function catLabel(cat: string): string {
  return CATEGORY_LABELS[cat] || cat;
}

function formatFileSize(bytes: number): string {
  if (!bytes || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

export default function DocumentManager({ initialTab = "docs" }: { initialTab?: "docs" | "images" | "cards" } = {}) {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;
  const setContentHubTab = useAppStore((s) => s.setContentHubTab);
  const docJumpTarget = useAppStore((s) => s.docJumpTarget);
  const setDocJumpTarget = useAppStore((s) => s.setDocJumpTarget);

  // ── Tab（内容中心按 Tab 挂载，默认进入指定 Tab）──
  const [activeTab, setActiveTab] = useState<"docs" | "images" | "cards">(initialTab);

  // ── Cards ──
  const [cardsTree, setCardsTree] = useState<import("../types").CardsTreeDTO | null>(null);
  const [cardsCollapsed, setCardsCollapsed] = useState<{ characters: boolean; classes: boolean }>({ characters: false, classes: false });
  const [selectedCardEntity, setSelectedCardEntity] = useState<string | null>(null);
  const [selectedCardEntityType, setSelectedCardEntityType] = useState<"character" | "class" | null>(null);

  // ── Tree ──
  const [tree, setTree] = useState<DocTreeCategory[]>([]);
  const [hierarchy, setHierarchy] = useState<{ level: number; label: string; categories: string[] }[]>([]);
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  const [contextMenu, setContextMenu] = useState<{
    x: number; y: number;
    category: string;
    node?: DocTreeNode;
  } | null>(null);

  // ── Images ──
  const [assetImages, setAssetImages] = useState<any[]>([]);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [imageFilter, setImageFilter] = useState("");
  const [collapsedImageKeys, setCollapsedImageKeys] = useState<Set<string>>(new Set());
  const [selectedImage, setSelectedImage] = useState<{
    url: string; name: string; size: number; subdir: string;
    path: string; category: string; entity: string;
  } | null>(null);
  const [defaultImages, setDefaultImages] = useState<Record<string, { default_avatar: string; default_skin: string; card_face: string; card_face_crop: import("../types").SkinCrop | null }>>({});
  const [cropTarget, setCropTarget] = useState<{ url: string; name: string; category: string; entity: string } | null>(null);

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
  const [charImporting, setCharImporting] = useState(false);
  const charFileRef = useRef<HTMLInputElement>(null);
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
        const [data, catData] = await Promise.all([
          apiRef.current.getDocumentTree(),
          apiRef.current.getDocumentCategories(),
        ]);
        setTree(data);
        setHierarchy(catData?.hierarchy || []);
        // 初始化所有类别为折叠状态
        setCollapsedNodes(new Set(data.map((c: DocTreeCategory) => c.category)));
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

  // ── Hierarchy helpers ──

  const catLevelMap = useMemo(() => {
    const map: Record<string, number> = {};
    const labels: Record<string, string> = {};
    for (const level of hierarchy) {
      labels[level.level] = level.label;
      for (const cat of level.categories) {
        map[cat] = level.level;
      }
    }
    return { map, labels };
  }, [hierarchy]);

  const sortCatsByLevel = useCallback(
    (cats: DocTreeCategory[]) =>
      [...cats].sort((a, b) => {
        const la = catLevelMap.map[a.category] ?? 99;
        const lb = catLevelMap.map[b.category] ?? 99;
        return la - lb || a.category.localeCompare(b.category);
      }),
    [catLevelMap]
  );

  // ── Load images ──

  const loadImages = useCallback(async () => {
    setImagesLoading(true);
    try {
      const data = await apiRef.current.getAssetImages();
      setAssetImages(data || []);
    } catch {
      setAssetImages([]);
    } finally {
      setImagesLoading(false);
    }
  }, []);

  const handleImageUpload = async (file: File, category: string, subdir?: string) => {
    try {
      await apiRef.current.uploadAssetImage(category, file, subdir);
      showToast(`图片 "${file.name}" 已上传`);
      loadImages();
    } catch (err: any) {
      showToast(err.message || "上传失败", "error");
    }
  };

  const handleImageDelete = async (category: string, fullPath: string) => {
    // fullPath example: "characters/阿米娅/avatar/char_002_amiya.png"
    // The API expects path relative to category dir: "阿米娅/avatar/char_002_amiya.png"
    const relativePath = fullPath.startsWith(category + "/")
      ? fullPath.slice(category.length + 1)
      : fullPath;
    try {
      await apiRef.current.deleteAssetImage(category, relativePath);
      showToast("图片已删除");
      loadImages();
    } catch (err: any) {
      showToast(err.message || "删除失败", "error");
    }
  };

  const loadDefaultImages = useCallback(async () => {
    const newDefaults: Record<string, { default_avatar: string; default_skin: string; card_face: string; card_face_crop: SkinCrop | null }> = {};
    for (const item of assetImages) {
      const key = `${item.category}/${item.entity}`;
      try {
        const data = await apiRef.current.getDefaultImage(item.category, item.entity);
        newDefaults[key] = {
          default_avatar: data.default_avatar || "",
          default_skin: data.default_skin || "",
          card_face: data.card_face || "",
          card_face_crop: data.card_face_crop || null,
        };
      } catch { /* skip */ }
    }
    setDefaultImages(newDefaults);
  }, [assetImages]);

  const handleSetDefaultImage = async (category: string, entity: string, type: "avatar" | "skin" | "card_face", filename: string, crop?: import("../types").SkinCrop | null) => {
    try {
      await apiRef.current.setDefaultImage(category, entity, type, filename, crop);
      const label = type === "avatar" ? "头像" : type === "skin" ? "立绘" : "卡面";
      showToast(`已设为默认${label}`);
      const key = `${category}/${entity}`;
      setDefaultImages((prev) => {
        const prevEntry = prev[key] || { default_avatar: "", default_skin: "", card_face: "", card_face_crop: null };
        if (type === "card_face") {
          return { ...prev, [key]: { ...prevEntry, card_face: filename, card_face_crop: crop ?? null } };
        }
        return { ...prev, [key]: { ...prevEntry, [`default_${type}`]: filename } };
      });
      // card_face 会复制新文件，刷新图片列表以显示 card_face 子目录分组
      if (type === "card_face") {
        loadImages();
      }
    } catch (err: any) {
      showToast(err.message || "设置失败", "error");
    }
  };

  const handleCropSave = async (crop: SkinCrop) => {
    if (!cropTarget) return;
    await handleSetDefaultImage(cropTarget.category, cropTarget.entity, "card_face", cropTarget.name, crop);
    setCropTarget(null);
  };

  useEffect(() => {
    if (activeTab === "images") {
      loadImages().then(() => {
        // loadDefaultImages depends on assetImages, so we trigger it after
      });
    }
  }, [activeTab, loadImages]);

  useEffect(() => {
    if (activeTab === "images" && assetImages.length > 0) {
      loadDefaultImages();
    }
  }, [assetImages, activeTab, loadDefaultImages]);

  const loadCardsTree = useCallback(async () => {
    try {
      const data = await apiRef.current.getCardsTree();
      setCardsTree(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (activeTab === "cards") {
      loadCardsTree();
    }
  }, [activeTab, loadCardsTree]);

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
    setSelectedImage(null);
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
      await api.saveDocument(
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

  // ── Index handlers ──

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

  // ── 角色卡导入（第三方 SillyTavern 角色卡 → data/characters + 内嵌世界书） ──

  const handleImportCharacterCard = async (file: File) => {
    setCharImporting(true);
    try {
      const res = await apiRef.current.importCharacterCard(file);
      const c = res.character;
      const wb = res.worldbook;
      showToast(
        `角色「${c.name}」已导入` + (wb ? `，内嵌世界书 ${wb.name}（${wb.entry_count} 条）` : ""),
        "success"
      );
      await loadTree();
      if (c.path) {
        const [cat, ...rest] = c.path.split("/");
        if (cat && rest.length) handleSelect(cat, rest.join("/"));
      }
    } catch (err: any) {
      showToast(err.message || "角色卡导入失败", "error");
    } finally {
      setCharImporting(false);
    }
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

  // 依赖引用管理已收敛到「索引」Tab（内容中心内），此处不再重复实现。

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
    const hasChildren = node.children && node.children.length > 0;

    // 隐藏纯文件夹节点，直接渲染子节点（保留层级缩进）
    if (node.type === "folder") {
      if (!node.children || node.children.length === 0) return null;
      return (
        <div key={key}>
          {node.children.map((child) =>
            renderTreeNode(child, category, depth, parentPath)
          )}
        </div>
      );
    }

    // Document node — may also have children (entity folder with sub-documents)
    return (
      <div key={key}>
        <div
          className={`group flex items-center gap-1 cursor-pointer rounded text-sm transition-colors select-none ${
            isSelected
              ? "bg-blue-600/20 text-blue-300"
              : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
          }`}
          style={{ paddingLeft: depth * 16 + 4 }}
          onContextMenu={(e) => handleContextMenu(e, category, node)}
        >
          {hasChildren ? (
            <span
              className="w-4 text-center text-gray-500 shrink-0"
              onClick={(e) => { e.stopPropagation(); toggleCollapse(key); }}
            >
              {collapsed ? "▶" : "▼"}
            </span>
          ) : (
            <span className="w-4 text-center shrink-0" />
          )}
          <span
            className="flex-1 flex items-center gap-1 truncate"
            onClick={() => handleSelect(category, node.id!)}
          >
            <span className="w-4 text-center text-blue-500 shrink-0">{hasChildren ? "📑" : "📄"}</span>
            <span className="truncate">{node.name}</span>
          </span>
        </div>
        {hasChildren && !collapsed && node.children && (
          <div>
            {node.children.map((child) =>
              renderTreeNode(child, category, depth + 1, nodePath)
            )}
          </div>
        )}
      </div>
    );
  };

  // ── Render: image tree ──

  const renderImageTree = () => {
    // 按名称过滤
    let filtered = assetImages;
    if (imageFilter.trim()) {
      const q = imageFilter.toLowerCase();
      filtered = assetImages.filter((item: any) =>
        item.entity_name.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q) ||
        item.images.some((img: any) => img.name.toLowerCase().includes(q))
      );
    }

    // 按 category 分组
    const grouped: Record<string, any[]> = {};
    for (const item of filtered) {
      const cat = item.category;
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(item);
    }

    return (
      <div>
        <div className="flex items-center gap-1 mb-2">
          <input
            className="input text-xs flex-1"
            placeholder="过滤图片名称..."
            value={imageFilter}
            onChange={(e) => setImageFilter(e.target.value)}
          />
          <button
            onClick={() => {
              if (collapsedImageKeys.size > 0) {
                setCollapsedImageKeys(new Set());
              } else {
                const allKeys = new Set<string>();
                for (const item of filtered) {
                  allKeys.add(`${item.category}/${item.entity}`);
                }
                setCollapsedImageKeys(allKeys);
              }
            }}
            className="text-[10px] text-gray-500 hover:text-gray-300 whitespace-nowrap px-1.5 py-1 rounded hover:bg-gray-700/50 transition-colors"
            title={collapsedImageKeys.size > 0 ? "展开全部" : "折叠全部"}
          >
            {collapsedImageKeys.size > 0 ? "展开" : "折叠"}
          </button>
        </div>
        {filtered.length === 0 && (
          <p className="text-xs text-gray-500 text-center py-4">
            {imageFilter ? "无匹配结果" : "暂无图像资产"}
          </p>
        )}
        {Object.entries(grouped).map(([cat, items]) => (
          <div key={cat} className="mb-3">
            <div className="flex items-center gap-1 text-xs font-semibold text-gray-500 uppercase tracking-wider py-1 mb-1">
              <span>{cat}</span>
              <div className="flex-1" />
              <label className="text-[10px] text-blue-400 hover:text-blue-300 cursor-pointer" title="上传到该分类">
                + 上传
                <input
                  type="file"
                  accept=".png,.jpg,.jpeg,.gif,.webp,.svg,.bmp"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) { handleImageUpload(file, cat); e.target.value = ""; }
                  }}
                />
              </label>
            </div>
            {items.map((item: any) => {
              const entityKey = `${item.category}/${item.entity}`;
              const defaults = defaultImages[entityKey];
              // 按 subdir 分组图片
              const subdirGroups: Record<string, any[]> = {};
              for (const img of item.images) {
                const sd = img.subdir || "";
                if (!subdirGroups[sd]) subdirGroups[sd] = [];
                subdirGroups[sd].push(img);
              }

              const isEntityCollapsed = collapsedImageKeys.has(entityKey);

              return (
                <div key={entityKey} className="mb-2 ml-1">
                  <div
                    className="flex items-center gap-1 text-xs text-gray-400 px-1 mb-1 cursor-pointer hover:text-gray-300 transition-colors select-none"
                    onClick={() => {
                      setCollapsedImageKeys((prev) => {
                        const next = new Set(prev);
                        if (next.has(entityKey)) next.delete(entityKey);
                        else next.add(entityKey);
                        return next;
                      });
                    }}
                  >
                    <span className="text-[10px] w-3 text-center flex-shrink-0">{isEntityCollapsed ? "▶" : "▼"}</span>
                    <span className="truncate flex-1" title={item.entity_name}>
                      {item.entity_name}
                    </span>
                    <label className="text-[10px] text-blue-400 hover:text-blue-300 cursor-pointer shrink-0" title="上传到该实体" onClick={(e) => e.stopPropagation()}>
                      +
                      <input
                        type="file"
                        accept=".png,.jpg,.jpeg,.gif,.webp,.svg,.bmp"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) {
                            handleImageUpload(file, cat, item.entity);
                            e.target.value = "";
                          }
                        }}
                      />
                    </label>
                  </div>
                  {!isEntityCollapsed && Object.entries(subdirGroups).map(([subdir, imgs]) => (
                    <div key={subdir || "__root__"} className="mb-1 ml-1">
                      {subdir && (
                        <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-1 px-1">
                          {subdir === "card_face" ? "card art" : subdir}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-1">
                        {imgs.map((img: any) => {
                          const isSelected = selectedImage?.path === img.path;
                          const isDefaultAvatar = defaults?.default_avatar === img.name;
                          const isDefaultSkin = defaults?.default_skin === img.name;
                          const isDefaultCardFace = defaults?.card_face === img.name;
                          const isDefault = isDefaultAvatar || isDefaultSkin || isDefaultCardFace;
                          return (
                            <div
                              key={img.path}
                              className={`relative group rounded overflow-hidden border-2 transition-colors cursor-pointer ${
                                isSelected
                                  ? "border-blue-400"
                                  : isDefault
                                  ? "border-yellow-500/60"
                                  : "border-gray-700 hover:border-blue-500/50"
                              }`}
                              style={{ width: 64, height: 64 }}
                              onClick={() => setSelectedImage({
                                url: img.url,
                                name: img.name,
                                size: img.size,
                                subdir: img.subdir || "",
                                path: img.path,
                                category: item.category,
                                entity: item.entity,
                              })}
                            >
                              <img
                                src={img.url}
                                alt={img.name}
                                className="w-full h-full object-cover"
                                loading="lazy"
                              />
                              {isDefault && (
                                <span
                                  className="absolute top-0 left-0 text-yellow-400 text-[10px] px-0.5"
                                  title={isDefaultAvatar ? "默认头像" : isDefaultSkin ? "默认立绘" : "卡面"}
                                >
                                  ★
                                </span>
                              )}
                              <button
                                className="absolute top-0 right-0 bg-red-600/80 text-white text-[10px] px-1 rounded-bl opacity-0 group-hover:opacity-100 transition-opacity"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (confirm(`确定要删除 "${img.name}" 吗？`)) {
                                    handleImageDelete(cat, img.path);
                                  }
                                }}
                                title="删除"
                              >
                                ✕
                              </button>
                              <div className="absolute bottom-0 left-0 right-0 bg-black/70 text-[10px] text-gray-300 px-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                                <div className="truncate">{img.name}</div>
                                {img.size != null && (
                                  <div className="text-gray-500">{formatFileSize(img.size)}</div>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    );
  };

  // ── Render: category ──

  const renderCategory = (cat: DocTreeCategory) => {
    const key = nodeKey(cat.category);
    const collapsed = isCollapsed(key);
    const hasChildren = cat.children && cat.children.length > 0;

    return (
      <div key={cat.category} className="mb-2">
        <div
          className="group flex items-center gap-1 cursor-pointer rounded text-xs font-medium text-gray-400 hover:text-gray-200 py-0.5 select-none"
          onClick={() => toggleCollapse(key)}
          onContextMenu={(e) => handleContextMenu(e, cat.category)}
        >
          <span className="w-3 text-center shrink-0">
            {collapsed ? "▶" : "▼"}
          </span>
          <span className="truncate">{catLabel(cat.category)}</span>
        </div>
        {!collapsed && (
          <div className="ml-3 border-l border-gray-700/30 pl-2">
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

  // ── Render: tree with hierarchy grouping ──

  const renderTree = () => {
    if (tree.length === 0) return null;

    // Group categories by hierarchy level
    const sorted = sortCatsByLevel(tree);
    const grouped: { level: number; label: string; cats: DocTreeCategory[] }[] = [];
    const ungrouped: DocTreeCategory[] = [];
    let currentLevel = -1;
    for (const cat of sorted) {
      const level = catLevelMap.map[cat.category] ?? 99;
      if (level === 99) {
        ungrouped.push(cat);
        continue;
      }
      if (level !== currentLevel) {
        currentLevel = level;
        grouped.push({
          level,
          label: `L${level} ${catLevelMap.labels[level] || `Level ${level}`}`,
          cats: [],
        });
      }
      grouped[grouped.length - 1].cats.push(cat);
    }

    return (
      <div className="space-y-3">
        {grouped.map((g) => (
          <div key={`level-${g.level}`}>
            <div className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider px-1 mb-1">
              {g.label}
            </div>
            {g.cats.map((cat) => renderCategory(cat))}
          </div>
        ))}
        {ungrouped.length > 0 && (
          <div>
            <div className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider px-1 mb-1">
              未分类
            </div>
            {ungrouped.map((cat) => renderCategory(cat))}
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

  // ── 统一检索跳转：打开指定文档（内容中心搜索命中） ──
  useEffect(() => {
    if (docJumpTarget) {
      handleSelect(docJumpTarget.category, docJumpTarget.id);
      setDocJumpTarget(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docJumpTarget]);

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
        {/* Tabs */}
        <div className="flex items-center gap-1 mb-3">
          <button
            className={`text-xs px-3 py-1 rounded transition-colors ${
              activeTab === "docs"
                ? "bg-blue-600/30 text-blue-300"
                : "text-gray-500 hover:text-gray-300"
            }`}
            onClick={() => { setActiveTab("docs"); setSelectedImage(null); setSelectedCardEntity(null); setSelectedCardEntityType(null); }}
          >
            文档
          </button>
          <button
            className={`text-xs px-3 py-1 rounded transition-colors ${
              activeTab === "images"
                ? "bg-blue-600/30 text-blue-300"
                : "text-gray-500 hover:text-gray-300"
            }`}
            onClick={() => { setActiveTab("images"); setSelectedCardEntity(null); setSelectedCardEntityType(null); }}
          >
            图像
          </button>
          <button
            className={`text-xs px-3 py-1 rounded transition-colors ${
              activeTab === "cards"
                ? "bg-blue-600/30 text-blue-300"
                : "text-gray-500 hover:text-gray-300"
            }`}
            onClick={() => { setActiveTab("cards"); setSelectedPath(null); setSelectedImage(null); }}
          >
            卡牌
          </button>
          <div className="flex-1" />
          {activeTab === "docs" && (
            <button
              onClick={() => charFileRef.current?.click()}
              disabled={charImporting}
              className="text-xs px-2 py-0.5 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 disabled:opacity-50 shrink-0"
              title="导入 SillyTavern 角色卡（PNG 或 JSON）：角色设定 + 内嵌世界书"
            >
              {charImporting ? "导入中…" : "⬆角色卡"}
            </button>
          )}
          <input
            ref={charFileRef}
            type="file"
            accept=".png,.json,.webp,.jpg,.jpeg"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleImportCharacterCard(f);
              e.target.value = "";
            }}
          />
          <button
            onClick={async () => {
              try {
                const { path } = await apiRef.current.getDataDir();
                if (window.electronAPI) {
                  await window.electronAPI.openDirectory(path);
                } else {
                  // Web 模式：复制路径到剪贴板
                  await navigator.clipboard.writeText(path);
                  showToast("路径已复制: " + path);
                }
              } catch { /* ignore */ }
            }}
            className="text-xs text-gray-500 hover:text-gray-300 px-1"
            title="打开资产文件夹"
          >
            📂
          </button>
          <button
            onClick={() => {
              if (activeTab === "docs") loadTree();
              else if (activeTab === "images") loadImages();
              else loadCardsTree();
            }}
            className="text-xs text-gray-500 hover:text-gray-300"
            title="刷新"
          >
            ↻
          </button>
        </div>

        {error && !selectedPath && activeTab === "docs" && (
          <p className="text-red-400 text-xs mb-2">{error}</p>
        )}

        {/* ── 文档 Tab ── */}
        {activeTab === "docs" && (
          tree.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
          ) : (
            renderTree()
          )
        )}

        {/* ── 图像 Tab ── */}
        {activeTab === "images" && (
          imagesLoading && assetImages.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
          ) : assetImages.length === 0 ? (
            <p className="text-gray-500 text-sm text-center py-4">暂无图像资产</p>
          ) : (
            renderImageTree()
          )
        )}

        {/* ── 卡牌 Tab ── */}
        {activeTab === "cards" && (
          !cardsTree ? (
            <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
          ) : (
            <div className="space-y-2">
              {/* Characters group */}
              <div>
                <div
                  className="flex items-center gap-1 cursor-pointer rounded text-xs font-medium text-gray-400 hover:text-gray-200 py-0.5 select-none"
                  onClick={() => setCardsCollapsed((c) => ({ ...c, characters: !c.characters }))}
                >
                  <span className="w-3 text-center shrink-0">{cardsCollapsed.characters ? "▶" : "▼"}</span>
                  <span>角色卡牌</span>
                </div>
                {!cardsCollapsed.characters && (
                  <div className="ml-3 border-l border-gray-700/30 pl-2">
                    {cardsTree.characters.length === 0 ? (
                      <p className="text-xs text-gray-600 italic pl-5">(空)</p>
                    ) : (
                      cardsTree.characters.map((name) => (
                        <div
                          key={name}
                          className={`group flex items-center gap-1 cursor-pointer rounded text-sm transition-colors select-none py-0.5 ${
                            selectedCardEntity === name && selectedCardEntityType === "character"
                              ? "bg-blue-600/20 text-blue-300"
                              : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
                          }`}
                          style={{ paddingLeft: 20 }}
                          onClick={() => {
                            setSelectedPath(null);
                            setSelectedImage(null);
                            setSelectedCardEntity(name);
                            setSelectedCardEntityType("character");
                          }}
                        >
                          <span className="w-4 text-center text-purple-500 shrink-0">🃏</span>
                          <span className="truncate">{name}</span>
                          {cardsTree.character_class_map[name] && (
                            <span className="text-[10px] text-gray-600 ml-1">{cardsTree.character_class_map[name]}</span>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>

              {/* Classes group */}
              <div>
                <div
                  className="flex items-center gap-1 cursor-pointer rounded text-xs font-medium text-gray-400 hover:text-gray-200 py-0.5 select-none"
                  onClick={() => setCardsCollapsed((c) => ({ ...c, classes: !c.classes }))}
                >
                  <span className="w-3 text-center shrink-0">{cardsCollapsed.classes ? "▶" : "▼"}</span>
                  <span>职业卡牌</span>
                </div>
                {!cardsCollapsed.classes && (
                  <div className="ml-3 border-l border-gray-700/30 pl-2">
                    {cardsTree.classes.length === 0 ? (
                      <p className="text-xs text-gray-600 italic pl-5">(空)</p>
                    ) : (
                      cardsTree.classes.map((name) => (
                        <div
                          key={name}
                          className={`group flex items-center gap-1 cursor-pointer rounded text-sm transition-colors select-none py-0.5 ${
                            selectedCardEntity === name && selectedCardEntityType === "class"
                              ? "bg-blue-600/20 text-blue-300"
                              : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
                          }`}
                          style={{ paddingLeft: 20 }}
                          onClick={() => {
                            setSelectedPath(null);
                            setSelectedImage(null);
                            setSelectedCardEntity(name);
                            setSelectedCardEntityType("class");
                          }}
                        >
                          <span className="w-4 text-center text-amber-500 shrink-0">🃏</span>
                          <span className="truncate">{name}</span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        )}
      </div>

      {/* ── Editor / Preview panel ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedPath && !selectedImage && !selectedCardEntity ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p>{activeTab === "images" ? "选择左侧图片预览" : activeTab === "cards" ? "选择左侧卡牌进行编辑" : "选择左侧文档查看或编辑"}</p>
          </div>
        ) : selectedCardEntity && selectedCardEntityType ? (
          /* ── 卡牌编辑器面板 ── */
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
              <h2 className="text-sm font-medium text-gray-300 truncate max-w-[60%]">
                {selectedCardEntityType === "character" ? "角色" : "职业"}: {selectedCardEntity}
              </h2>
              <button
                onClick={() => { setSelectedCardEntity(null); setSelectedCardEntityType(null); }}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                ✕ 关闭
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              <CardEditor
                key={`${selectedCardEntityType}-${selectedCardEntity}`}
                embedded
                entityName={selectedCardEntity}
                entityType={selectedCardEntityType}
              />
            </div>
          </div>
        ) : activeTab === "images" && selectedImage && !selectedPath ? (
          /* ── 图片预览面板 ── */
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
              <h2 className="text-sm font-medium text-gray-300 truncate max-w-[60%]">
                {selectedImage.name}
              </h2>
              <button
                onClick={() => setSelectedImage(null)}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                ✕ 关闭
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 flex flex-col items-center">
              <div className="max-w-lg w-full">
                <img
                  src={selectedImage.url}
                  alt={selectedImage.name}
                  className="w-full max-h-96 object-contain rounded bg-gray-900/50"
                />
                <div className="mt-4 space-y-1 text-xs text-gray-400">
                  <div className="flex justify-between">
                    <span className="text-gray-500">文件名</span>
                    <span>{selectedImage.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">大小</span>
                    <span>{formatFileSize(selectedImage.size)}</span>
                  </div>
                  {selectedImage.subdir && (
                    <div className="flex justify-between">
                      <span className="text-gray-500">子目录</span>
                      <span>{selectedImage.subdir === "card_face" ? "card art" : selectedImage.subdir}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-500">路径</span>
                    <span className="text-gray-600">{selectedImage.path}</span>
                  </div>
                </div>
                {/* Set as default buttons */}
                <div className="mt-4 flex gap-2 justify-center flex-wrap">
                  {selectedImage.subdir === "avatar" && (
                    <button
                      onClick={() => handleSetDefaultImage(
                        selectedImage.category,
                        selectedImage.entity,
                        "avatar",
                        selectedImage.name
                      )}
                      className="text-xs px-3 py-1.5 rounded bg-blue-600/20 text-blue-400 hover:bg-blue-600/40 transition-colors"
                    >
                      设为默认头像
                    </button>
                  )}
                  {selectedImage.subdir === "skin" && (
                    <button
                      onClick={() => handleSetDefaultImage(
                        selectedImage.category,
                        selectedImage.entity,
                        "skin",
                        selectedImage.name
                      )}
                      className="text-xs px-3 py-1.5 rounded bg-purple-600/20 text-purple-400 hover:bg-purple-600/40 transition-colors"
                    >
                      设为默认立绘
                    </button>
                  )}
                  {(selectedImage.subdir === "avatar" || selectedImage.subdir === "skin") && (
                    <button
                      onClick={() => handleSetDefaultImage(
                        selectedImage.category,
                        selectedImage.entity,
                        "card_face",
                        selectedImage.name
                      )}
                      className="text-xs px-3 py-1.5 rounded bg-amber-600/20 text-amber-400 hover:bg-amber-600/40 transition-colors"
                    >
                      设为卡面
                    </button>
                  )}
                  {selectedImage.subdir === "card_face" && (
                    <>
                      <button
                        onClick={() => handleSetDefaultImage(
                          selectedImage.category,
                          selectedImage.entity,
                          "card_face",
                          selectedImage.name
                        )}
                        className="text-xs px-3 py-1.5 rounded bg-amber-600/20 text-amber-400 hover:bg-amber-600/40 transition-colors"
                      >
                        设为默认卡面
                      </button>
                      <button
                        onClick={() => setCropTarget(selectedImage)}
                        className="text-xs px-3 py-1.5 rounded bg-green-600/20 text-green-400 hover:bg-green-600/40 transition-colors"
                      >
                        裁剪卡面
                      </button>
                    </>
                  )}
                </div>
                {selectedImage.subdir && selectedImage.subdir !== "avatar" && selectedImage.subdir !== "skin" && selectedImage.subdir !== "card_face" && (
                  <p className="text-xs text-gray-600 text-center mt-3">
                    仅 avatar/、skin/ 和 card art/ 子目录的图片可设为默认
                  </p>
                )}
              </div>
            </div>
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
                <MarkdownRenderer content={docContent?.content || ""} />
              )}
            </div>

            {/* ── 依赖管理（收敛到索引 Tab，此处仅保留入口） ── */}
            {!loading && selectedPath && (
              <div className="border-t border-gray-700 px-4 py-2 flex items-center gap-2">
                <span className="text-xs text-gray-500">依赖引用管理已统一到「索引」</span>
                <button
                  onClick={() => setContentHubTab("index")}
                  className="text-xs px-2 py-0.5 rounded bg-blue-600/20 text-blue-300 hover:bg-blue-600/40 transition-colors"
                >
                  🔗 在索引中管理
                </button>
              </div>
            )}

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
        )
      }
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

      {/* ── CropModal ── */}
      {cropTarget && (
        <CropModal
          imageUrl={cropTarget.url}
          onSave={handleCropSave}
          onClose={() => setCropTarget(null)}
        />
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
