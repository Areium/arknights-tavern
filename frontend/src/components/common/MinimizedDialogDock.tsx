/**
 * 最小化对话框的恢复入口（全局单例）。
 *
 * 每个被最小化的对话框在此占一条，点击即还原对应的那个对话框，
 * 多个对话框各自独立、互不干扰。
 *
 * 层级说明：z-40 < 对话框遮罩的 z-50，所以有其它对话框展开时恢复条会被遮罩盖住，
 * 不会破坏既有遮罩层与点击穿透行为。
 */
import { useAppStore } from "../../stores/appStore";

export default function MinimizedDialogDock() {
  const dialogs = useAppStore((s) => s.minimizedDialogs);
  const entries = Object.entries(dialogs);

  if (entries.length === 0) return null;

  return (
    <div className="fixed bottom-4 left-4 z-40 flex flex-col-reverse gap-2">
      {entries.map(([id, entry]) => (
        <button
          key={id}
          onClick={entry.restore}
          title={`展开「${entry.title}」`}
          aria-label={`展开${entry.title}`}
          className="flex items-center gap-2 max-w-[280px] px-3 py-1.5 rounded-lg
                     border border-amber-600/40 bg-gray-800/95 text-amber-300 shadow-lg
                     hover:bg-amber-600/20 transition-colors text-xs"
        >
          <span className="truncate">{entry.title}</span>
          <span className="text-[10px] text-amber-200/70 shrink-0">展开 ▲</span>
        </button>
      ))}
    </div>
  );
}
