/**
 * 全局错误边界 — 组件渲染异常时展示可恢复的兜底界面，避免整页白屏。
 */
import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** 错误发生后尝试恢复（例如重置内容中心 Tab） */
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  message: string;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(err: unknown): State {
    return {
      hasError: true,
      message: err instanceof Error ? err.message : String(err),
    };
  }

  componentDidCatch(err: unknown) {
    console.error("[ErrorBoundary]", err);
  }

  private reset = () => {
    this.setState({ hasError: false, message: "" });
    this.props.onReset?.();
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="h-full w-full flex flex-col items-center justify-center gap-3 bg-gray-950 text-gray-300 p-6">
        <div className="text-3xl">⚠️</div>
        <h2 className="text-base font-medium text-amber-300">界面渲染出错</h2>
        <p className="text-xs text-gray-500 max-w-md text-center break-all">
          {this.state.message || "未知错误"}
        </p>
        <div className="flex gap-2">
          <button
            onClick={this.reset}
            className="text-xs px-3 py-1.5 rounded bg-amber-600/20 text-amber-300 hover:bg-amber-600/40 transition-colors"
          >
            重试
          </button>
          <button
            onClick={() => window.location.reload()}
            className="text-xs px-3 py-1.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
          >
            刷新页面
          </button>
        </div>
      </div>
    );
  }
}
