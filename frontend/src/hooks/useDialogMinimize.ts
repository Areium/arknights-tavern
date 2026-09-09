/**
 * 对话框最小化：把「关闭」与「最小化」拆成两个独立操作。
 *
 * 设计要点：
 * 1) 最小化只切换 CSS（invisible + pointer-events-none），对话框 DOM 始终保留，
 *    因此输入内容、滚动位置、勾选/选中项等内部状态原样保留。
 *    这里刻意不用 `hidden`（display:none）——display:none 会销毁布局盒，滚动位置可能丢失；
 *    visibility:hidden 仍保留布局盒，且不参与命中测试与 Tab 焦点序列。
 * 2) 每个对话框用稳定 id 注册恢复入口，多个对话框的最小化状态互不干扰。
 * 3) 对话框真正关闭（isOpen 变 false）时自动退出最小化，避免下次打开直接是隐藏态。
 * 4) 还原时把焦点交还对话框卡片，避免焦点停在被移除的恢复条上。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { useAppStore } from "../stores/appStore";

export interface DialogMinimizeApi {
  /** 是否处于最小化态；对话框关闭时恒为 false */
  minimized: boolean;
  /** 最小化时追加到根节点的类：保留 DOM 与状态，仅隐藏并禁用命中测试 */
  minimizedClass: string;
  /** 对话框卡片 ref：还原时用于把焦点交还给对话框（卡片需带 tabIndex={-1}） */
  containerRef: RefObject<HTMLDivElement>;
  /** 最小化 */
  minimize: () => void;
  /** 还原 */
  restore: () => void;
}

export function useDialogMinimize(
  id: string,
  title: string,
  isOpen: boolean,
): DialogMinimizeApi {
  const [minimized, setMinimized] = useState(false);
  const setMinimizedDialog = useAppStore((s) => s.setMinimizedDialog);
  const containerRef = useRef<HTMLDivElement>(null);
  const wasMinimized = useRef(false);

  const minimize = useCallback(() => setMinimized(true), []);
  const restore = useCallback(() => setMinimized(false), []);

  // 关闭 → 退出最小化（下次打开必须是展开态）
  useEffect(() => {
    if (!isOpen && minimized) setMinimized(false);
  }, [isOpen, minimized]);

  const active = isOpen && minimized;

  // 注册 / 注销恢复入口：同一 id 覆盖，多对话框各自独立；组件卸载时清理
  useEffect(() => {
    setMinimizedDialog(id, active ? { title, restore } : null);
    return () => setMinimizedDialog(id, null);
  }, [id, title, active, restore, setMinimizedDialog]);

  // 还原时把焦点交还对话框
  useEffect(() => {
    if (wasMinimized.current && !active && isOpen) containerRef.current?.focus();
    wasMinimized.current = active;
  }, [active, isOpen]);

  return {
    minimized: active,
    minimizedClass: active ? "invisible pointer-events-none" : "",
    containerRef,
    minimize,
    restore,
  };
}
