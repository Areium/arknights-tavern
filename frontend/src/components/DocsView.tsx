import { useMemo, useState } from "react";
import MarkdownRenderer from "./MarkdownRenderer";
import tutorialMd from "../../../docs/tutorial.md?raw";

interface TocItem {
  id: string;
  text: string;
  level: number;
}

/** 从 Markdown 源码提取标题目录（跳过代码围栏），id 与 MarkdownRenderer 生成的锚点一致 */
function extractToc(md: string): TocItem[] {
  const items: TocItem[] = [];
  let inFence = false;
  for (const line of md.split("\n")) {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^(#{2,4})\s+(.+)$/.exec(line);
    if (m) {
      const text = m[2].trim().replace(/`/g, "").replace(/\*\*/g, "");
      items.push({ id: encodeURIComponent(text), text, level: m[1].length });
    }
  }
  return items;
}

export default function DocsView() {
  const toc = useMemo(() => extractToc(tutorialMd), []);
  const [active, setActive] = useState<string>("");

  const scrollTo = (id: string, text: string) => {
    setActive(text);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="flex h-full bg-gray-900">
      {/* 左侧目录 */}
      <aside className="w-60 border-r border-gray-700 flex flex-col shrink-0 bg-gray-850">
        <div className="px-4 py-3 border-b border-gray-700">
          <h2 className="text-sm font-semibold text-amber-400">📘 使用教程</h2>
          <p className="text-xs text-gray-500 mt-0.5">目录</p>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-0.5">
          {toc.map((item) => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id, item.text)}
              className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors ${
                item.level === 2 ? "font-medium" : "pl-6"
              } ${
                active === item.text
                  ? "bg-blue-600/20 text-blue-300"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
              }`}
            >
              {item.text}
            </button>
          ))}
        </nav>
      </aside>

      {/* 右侧正文 */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6">
          <MarkdownRenderer content={tutorialMd} />
        </div>
      </div>
    </div>
  );
}
