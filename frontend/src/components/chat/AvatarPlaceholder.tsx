import { useState, useEffect } from "react";
import { useAppStore } from "../../stores/appStore";

const COLORS = [
  "#c44b3c", "#3c8c4a", "#8b5ca8", "#4a6b8a",
  "#c4a83c", "#d4a574", "#5c9a8b", "#6b5c8a",
];

function nameToColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash += name.charCodeAt(i);
  }
  return COLORS[hash % COLORS.length];
}

function avatarUrl(name: string, sessionId?: string, version = 0): string {
  const base = `/api/characters/${encodeURIComponent(name)}/avatar`;
  if (!sessionId) return base;
  // 会话覆盖优先；v 参数用于上传覆盖后强制刷新浏览器缓存
  return `${base}?session_id=${encodeURIComponent(sessionId)}&v=${version}`;
}

interface AvatarPlaceholderProps {
  name: string;
  size?: "sm" | "md";
  /** 传入会话 ID 时走会话覆盖头像（会话优先，回退全局） */
  sessionId?: string;
}

export default function AvatarPlaceholder({ name, size = "sm", sessionId }: AvatarPlaceholderProps) {
  const bg = nameToColor(name);
  const initial = name.charAt(0);
  const sizeClass = size === "sm" ? "w-8 h-8 text-xs" : "w-10 h-10 text-sm";
  const resourceVersion = useAppStore((s) => s.resourceVersion);
  const [imgOk, setImgOk] = useState(true);
  useEffect(() => { setImgOk(true); }, [name, sessionId]);

  if (imgOk) {
    return (
      <img
        src={avatarUrl(name, sessionId, resourceVersion)}
        alt={name}
        className={`${sizeClass} rounded-full object-cover flex-shrink-0`}
        onError={() => setImgOk(false)}
      />
    );
  }

  return (
    <div
      className={`${sizeClass} rounded-full flex items-center justify-center font-bold text-white/90 flex-shrink-0`}
      style={{ backgroundColor: bg }}
      title={name}
    >
      {initial}
    </div>
  );
}
