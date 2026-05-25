import { useState, useEffect } from "react";

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

function avatarUrl(name: string): string {
  return `/api/characters/${encodeURIComponent(name)}/avatar`;
}

interface AvatarPlaceholderProps {
  name: string;
  size?: "sm" | "md";
}

export default function AvatarPlaceholder({ name, size = "sm" }: AvatarPlaceholderProps) {
  const bg = nameToColor(name);
  const initial = name.charAt(0);
  const sizeClass = size === "sm" ? "w-8 h-8 text-xs" : "w-10 h-10 text-sm";
  const [imgOk, setImgOk] = useState(true);
  useEffect(() => { setImgOk(true); }, [name]);

  if (imgOk) {
    return (
      <img
        src={avatarUrl(name)}
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
