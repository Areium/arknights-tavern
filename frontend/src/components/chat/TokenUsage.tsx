interface UsageData {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/**
 * Token 消耗展示 — 显示输入/输出/总计 token 数
 */
export default function TokenUsage({ usage }: { usage: UsageData }) {
  if (
    usage.prompt_tokens == null ||
    usage.completion_tokens == null ||
    usage.total_tokens == null
  ) {
    return null;
  }

  return (
    <div className="text-[10px] text-gray-600 mt-1 select-none">
      {usage.total_tokens} tokens
      <span className="text-gray-700">
        {" "}(输入 {usage.prompt_tokens} + 输出 {usage.completion_tokens})
      </span>
    </div>
  );
}
