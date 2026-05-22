import { useAppStore } from "../stores/appStore";

const STATUS_COLORS: Record<string, string> = {
  connecting: "text-yellow-400",
  connected: "text-green-400",
  disconnected: "text-red-400",
  error: "text-red-500",
};

const STATUS_LABELS: Record<string, string> = {
  connecting: "连接中...",
  connected: "已连接",
  disconnected: "未连接",
  error: "错误",
};

export default function StatusBar() {
  const { backend, llmStatus } = useAppStore();

  const llmName = llmStatus?.primary?.name ?? "未配置";
  const llmOnline = llmStatus?.available ?? false;

  return (
    <footer className="h-7 bg-gray-850 border-t border-gray-700 flex items-center px-4 text-xs text-gray-500 shrink-0">
      <div className="flex items-center gap-4">
        {/* Backend status */}
        <span className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              backend.status === "connected" ? "bg-green-400" : "bg-red-400"
            }`}
          />
          <span className={STATUS_COLORS[backend.status]}>
            {STATUS_LABELS[backend.status]}
          </span>
        </span>

        {/* LLM status */}
        <span className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              llmOnline ? "bg-green-400" : "bg-gray-600"
            }`}
          />
          <span>{llmName}</span>
        </span>
      </div>
    </footer>
  );
}
