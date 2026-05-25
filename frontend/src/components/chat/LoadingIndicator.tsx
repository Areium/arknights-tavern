/**
 * LLM 思考中加载指示器 — 脉冲动画 + 等待计时
 */
export default function LoadingIndicator({ elapsedSeconds }: { elapsedSeconds: number }) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 text-gray-400 text-sm">
      <span className="flex gap-1">
        <span
          className="w-2 h-2 bg-amber-400/60 rounded-full animate-pulse"
          style={{ animationDelay: "0ms" }}
        />
        <span
          className="w-2 h-2 bg-amber-400/60 rounded-full animate-pulse"
          style={{ animationDelay: "150ms" }}
        />
        <span
          className="w-2 h-2 bg-amber-400/60 rounded-full animate-pulse"
          style={{ animationDelay: "300ms" }}
        />
      </span>
      <span>
        AI 思考中
        {elapsedSeconds > 0 && ` (${elapsedSeconds}s)`}...
      </span>
    </div>
  );
}
