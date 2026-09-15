import { useEffect, useState } from "react";
import { useApi } from "../../hooks/useApi";
import type { WorldBookDetail, WorldBookScopePreviewDTO } from "../../types";
import type { WorldBookDraft } from "../../hooks/useWorldbookDraft";

/** 三个视图共享的页面级状态：同一份统一草稿、同一条预览与保存路径。 */
export interface WorldBookPanelProps {
  detail: WorldBookDetail;
  draft: WorldBookDraft;
  patch: (changes: Partial<WorldBookDraft>) => void;
  /** 显式改用按需载入（v3）：独立、可撤销的动作，迁移映射由服务端计算 */
  adoptV3: () => void;
  dirty: boolean;
  saving: boolean;
  saveError: string;
  conflict: boolean;
  save: () => Promise<void>;
  undo: () => void;
  preview: WorldBookScopePreviewDTO | null;
  previewing: boolean;
  previewError: string;
  /** 试选阵容：只用于预览「本次范围」，不影响已保存配置 */
  roster: string[];
  setRoster: React.Dispatch<React.SetStateAction<string[]>>;
}

export interface CharacterInfo { id: string; name: string; title?: string }

/** 角色目录：界面显示名与头像，实际写入配置的仍然是目录 ID（slug）。 */
export function useCharacterDirectory() {
  const api = useApi();
  const [characters, setCharacters] = useState<CharacterInfo[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getCharacters()
      .then((items) => { if (!cancelled) setCharacters((items || []).map((c: any) => ({
        id: c.id || c.name || "", name: c.name || c.title || c.id || "", title: c.title,
      }))); })
      .catch(() => { if (!cancelled) setCharacters([]); });
    return () => { cancelled = true; };
  }, [api]);
  return characters;
}

export const avatarUrl = (id: string) => `/api/characters/${encodeURIComponent(id)}/avatar`;

export const characterName = (characters: CharacterInfo[] | null, id: string) =>
  characters?.find((character) => character.id === id)?.name || id;

/** 条目 uid → 显示名（缺失时回落到 uid，不隐藏问题） */
export const makeLabeler = (detail: WorldBookDetail) => {
  const names = new Map(detail.entries.map((entry) => [entry.uid, entry.name || entry.uid]));
  return (uid: string) => names.get(uid) || uid;
};

export const ACTIVATION_LABELS: Record<string, string> = {
  always: "基础设定（所有会话候选）",
  roster_any: "角色入队时选用",
  manual: "仅手动追加",
};
export const EXPANSION_LABELS: Record<string, string> = {
  none: "只含自身",
  requires_closure: "补齐必要依赖",
  legacy_depth: "按旧深度展开",
};
