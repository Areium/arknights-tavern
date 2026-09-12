/**
 * 资产目录 — 图片资产管理（上传 / 裁剪 / 默认图）。
 *
 * 由内容中心「资产」Tab 挂载（原 DocumentManager 图像 Tab 独立成组件，
 * 文档管理功能已迁移至世界书整合包）。
 *
 * 来源标注：每个实体显示上级目录与来源世界书（index.md frontmatter 的
 * worldbook_id），支持按世界书筛选，详情面板可修改归属。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import type { AssetEntityGroupDTO, SkinCrop, WorldBookSummary } from "../types";
import CropModal from "./assets/CropModal";

interface ToastState {
  message: string;
  type: "success" | "error";
}

function formatFileSize(bytes: number): string {
  if (!bytes || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function AssetManager() {
  const api = useApi();
  const apiRef = useRef(api);
  apiRef.current = api;

  // ── 数据 ──
  const [assetImages, setAssetImages] = useState<AssetEntityGroupDTO[]>([]);
  const [imagesLoading, setImagesLoading] = useState(false);
  const [imageFilter, setImageFilter] = useState("");
  const [worldbooks, setWorldbooks] = useState<WorldBookSummary[]>([]);
  /** 来源筛选："" = 全部，"__none__" = 未标注，否则为 book id */
  const [bookFilter, setBookFilter] = useState("");
  const [collapsedImageKeys, setCollapsedImageKeys] = useState<Set<string>>(new Set());
  const [selectedImage, setSelectedImage] = useState<{
    url: string; name: string; size: number; subdir: string;
    path: string; category: string; entity: string;
  } | null>(null);
  const [defaultImages, setDefaultImages] = useState<Record<string, { default_avatar: string; default_skin: string; card_face: string; card_face_crop: SkinCrop | null }>>({});
  const [cropTarget, setCropTarget] = useState<{ url: string; name: string; category: string; entity: string } | null>(null);

  // ── Toast ──
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();
  const showToast = useCallback((message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

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

  const loadWorldbooks = useCallback(async () => {
    try {
      const res = await apiRef.current.listWorldbooks();
      setWorldbooks(res.books || []);
    } catch { /* 后端不可用时不阻塞资产管理 */ }
  }, []);

  useEffect(() => {
    loadImages();
    loadWorldbooks();
  }, [loadImages, loadWorldbooks]);

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

  useEffect(() => {
    if (assetImages.length > 0) loadDefaultImages();
  }, [assetImages, loadDefaultImages]);

  // ── 图片操作 ──

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

  const handleSetDefaultImage = async (category: string, entity: string, type: "avatar" | "skin" | "card_face", filename: string, crop?: SkinCrop | null) => {
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

  /** 修改实体来源世界书标注 */
  const handleSetEntityWorldbook = async (item: AssetEntityGroupDTO, bookId: string) => {
    try {
      await apiRef.current.setEntityWorldbook(item.category, item.entity, bookId);
      showToast(bookId ? "来源世界书已标注" : "已清除标注");
      setAssetImages((prev) => prev.map((g) =>
        g.category === item.category && g.entity === item.entity
          ? { ...g, worldbook_id: bookId }
          : g,
      ));
    } catch (err: any) {
      showToast(err.message || "标注失败", "error");
    }
  };

  const bookName = (id: string) => worldbooks.find((b) => b.id === id)?.name || id;

  // ── 筛选：名称 + 来源世界书 ──

  const filtered = assetImages.filter((item) => {
    if (bookFilter === "__none__" && item.worldbook_id) return false;
    if (bookFilter && bookFilter !== "__none__" && item.worldbook_id !== bookFilter) return false;
    if (!imageFilter.trim()) return true;
    const q = imageFilter.toLowerCase();
    return item.entity_name.toLowerCase().includes(q) ||
      item.category.toLowerCase().includes(q) ||
      item.images.some((img) => img.name.toLowerCase().includes(q));
  });

  // 按世界书归类（有标注的实体归入其世界书分组，未标注的归入「未标注」）
  const groupedByBook: { key: string; label: string; items: AssetEntityGroupDTO[] }[] = [];
  if (bookFilter) {
    const groups: Record<string, AssetEntityGroupDTO[]> = {};
    for (const item of filtered) {
      const key = item.worldbook_id || "__none__";
      (groups[key] = groups[key] || []).push(item);
    }
    for (const [key, items] of Object.entries(groups)) {
      groupedByBook.push({
        key,
        label: key === "__none__" ? "未标注" : bookName(key),
        items,
      });
    }
  }

  // 按类别分组
  const grouped: Record<string, AssetEntityGroupDTO[]> = {};
  for (const item of filtered) {
    (grouped[item.category] = grouped[item.category] || []).push(item);
  }

  const renderEntityGroup = (item: AssetEntityGroupDTO) => {
    const entityKey = `${item.category}/${item.entity}`;
    const defaults = defaultImages[entityKey];
    // 按 subdir 分组图片
    const subdirGroups: Record<string, AssetEntityGroupDTO["images"]> = {};
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
          <span className="truncate flex-1" title={`${item.entity_name}（上级目录 ${item.parent_dir}）`}>
            {item.entity_name}
          </span>
          {item.worldbook_id ? (
            <span
              className="text-[9px] px-1 rounded bg-amber-600/15 text-amber-300 border border-amber-700/40 shrink-0"
              title={`来源世界书：${bookName(item.worldbook_id)}`}
            >
              📖 {bookName(item.worldbook_id)}
            </span>
          ) : (
            <span className="text-[9px] text-gray-600 shrink-0" title="未标注来源世界书">未标注</span>
          )}
          <label className="text-[10px] text-blue-400 hover:text-blue-300 cursor-pointer shrink-0" title="上传到该实体" onClick={(e) => e.stopPropagation()}>
            +
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.gif,.webp,.svg,.bmp"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) {
                  handleImageUpload(file, item.category, item.entity);
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
              {imgs.map((img) => {
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
                          handleImageDelete(item.category, img.path);
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
  };

  const renderImageTree = () => (
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
      <select
        className="w-full bg-gray-800/80 border border-gray-700 rounded px-2 py-1 text-[11px] text-gray-300 mb-2"
        value={bookFilter}
        onChange={(e) => setBookFilter(e.target.value)}
        title="按来源世界书筛选"
      >
        <option value="">📚 全部世界书</option>
        <option value="__none__">未标注来源</option>
        {worldbooks.map((b) => (
          <option key={b.id} value={b.id}>📖 {b.name}</option>
        ))}
      </select>
      {filtered.length === 0 && (
        <p className="text-xs text-gray-500 text-center py-4">
          {imageFilter || bookFilter ? "无匹配结果" : "暂无图像资产"}
        </p>
      )}
      {bookFilter ? (
        // 按世界书归类展示
        groupedByBook.map((group) => (
          <div key={group.key} className="mb-3">
            <div className="text-xs font-semibold text-amber-300/80 py-1 mb-1">
              📖 {group.label}
              <span className="text-[10px] text-gray-600 font-normal ml-1">({group.items.length})</span>
            </div>
            {group.items.map(renderEntityGroup)}
          </div>
        ))
      ) : (
        Object.entries(grouped).map(([cat, items]) => (
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
            {items.map(renderEntityGroup)}
          </div>
        ))
      )}
    </div>
  );

  // ── 渲染 ──

  return (
    <div className="flex h-full">
      {/* ── 实体树侧栏 ── */}
      <div className="w-72 border-r border-gray-700 overflow-y-auto p-3 shrink-0" id="asset-tree-sidebar">
        <div className="flex items-center gap-1 mb-3">
          <span className="text-xs px-3 py-1 rounded bg-blue-600/30 text-blue-300">🖼️ 资产</span>
          <div className="flex-1" />
          <button
            onClick={async () => {
              try {
                const { path } = await apiRef.current.getDataDir();
                if (window.electronAPI) {
                  await window.electronAPI.openDirectory(path);
                } else {
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
            onClick={loadImages}
            className="text-xs text-gray-500 hover:text-gray-300"
            title="刷新"
          >
            ↻
          </button>
        </div>

        {imagesLoading && assetImages.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-4">加载中...</p>
        ) : assetImages.length === 0 ? (
          <p className="text-gray-500 text-sm text-center py-4">暂无图像资产</p>
        ) : (
          renderImageTree()
        )}
      </div>

      {/* ── 预览面板 ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedImage ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p>选择左侧图片预览</p>
          </div>
        ) : (
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
                    <span className="text-gray-500">上级目录</span>
                    <span className="text-gray-600 font-mono">
                      {selectedImage.category}/{selectedImage.entity}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">路径</span>
                    <span className="text-gray-600">{selectedImage.path}</span>
                  </div>
                  <div className="flex justify-between items-center pt-1">
                    <span className="text-gray-500">来源世界书</span>
                    <WorldbookSelect
                      value={assetImages.find(
                        (g) => g.category === selectedImage.category && g.entity === selectedImage.entity,
                      )?.worldbook_id || ""}
                      worldbooks={worldbooks}
                      onChange={(id) => {
                        const item = assetImages.find(
                          (g) => g.category === selectedImage.category && g.entity === selectedImage.entity,
                        );
                        if (item) handleSetEntityWorldbook(item, id);
                      }}
                    />
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
        )}
      </div>

      {cropTarget && (
        <CropModal
          imageUrl={cropTarget.url}
          onSave={handleCropSave}
          onClose={() => setCropTarget(null)}
        />
      )}

      {toast && (
        <div
          className={`fixed bottom-16 right-6 px-4 py-2 rounded-lg shadow-lg text-sm z-50 ${
            toast.type === "success"
              ? "bg-green-800/90 text-green-100"
              : "bg-red-800/90 text-red-100"
          }`}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

/** 来源世界书下拉（资产/卡牌共用的小控件） */
export function WorldbookSelect({
  value, worldbooks, onChange,
}: {
  value: string;
  worldbooks: WorldBookSummary[];
  onChange: (bookId: string) => void;
}) {
  return (
    <select
      className="bg-gray-800/80 border border-gray-700 rounded px-1.5 py-0.5 text-[11px] text-gray-300 max-w-[12rem]"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      title="标注来源世界书"
    >
      <option value="">（未标注）</option>
      {worldbooks.map((b) => (
        <option key={b.id} value={b.id}>{b.name}</option>
      ))}
    </select>
  );
}
