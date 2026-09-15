import type { WorldBookExpansion, WorldBookRootDTO } from "../types";

/**
 * 用户改写 AI / 规则生成的根后，它就成为人工配置。
 *
 * 用白名单重建对象，避免把模型、提示词、证据、正文哈希或旧 job 身份继续挂在
 * 已被人工改变的结论上；激活条件、角色范围与锁定状态仍属于根本身的有效语义。
 */
export const withManualExpansion = (
  root: WorldBookRootDTO,
  expansion: WorldBookExpansion,
): WorldBookRootDTO => {
  const next: WorldBookRootDTO = {
    entry_uid: root.entry_uid,
    activation: root.activation,
    expansion,
    origin: "manual",
  };
  if (root.character_ids !== undefined) next.character_ids = [...root.character_ids];
  if (root.locked !== undefined) next.locked = root.locked;
  if (expansion === "legacy_depth" && root.max_depth !== undefined) next.max_depth = root.max_depth;
  return next;
};
