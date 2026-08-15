/**
 * 来源标识徽章 — 统一区分「预装整合包」与「用户导入」内容。
 * 两者在同一列表、同一套规则下管理，徽章仅作来源说明。
 */
export default function SourceBadge({
  source,
  size = "sm",
}: {
  source: string;
  size?: "xs" | "sm";
}) {
  const isPreinstalled = source === "preinstalled";
  const cls =
    size === "xs"
      ? "text-[10px] px-1 py-px rounded"
      : "text-[11px] px-1.5 py-0.5 rounded";
  if (isPreinstalled) {
    return (
      <span
        className={`${cls} bg-cyan-600/20 text-cyan-300 border border-cyan-500/30 shrink-0`}
        title="预装整合包：随程序分发，首次启动自动安装；可编辑/停用/删除，删除后可一键重装"
      >
        预装
      </span>
    );
  }
  return (
    <span
      className={`${cls} bg-violet-600/20 text-violet-300 border border-violet-500/30 shrink-0`}
      title="用户导入：第三方世界书或自制内容，完全可写"
    >
      导入
    </span>
  );
}
