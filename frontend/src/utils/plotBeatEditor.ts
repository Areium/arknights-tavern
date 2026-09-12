/**
 * 剧情节拍编辑 — 对 data/plots/<plot_id>/index.md 的章节/节拍结构做文本手术。
 *
 * 剧情叙述区的结构约定（与后端 combat_nodes.plot_flows / session_overlay 的
 * 节拍解析一致）：
 *   ## 章节 N：标题
 *   ### 关键节拍
 *   #### beat_xxx（keep_on_deviate: true）
 *   ……节拍正文……
 *   ## 关键对话参考   ← 剧情叙述区到此结束（之后的配置区不参与节拍解析）
 */

export interface BeatRange {
  /** 节拍头行（`#### beat_xxx …`）行号 */
  headerLine: number;
  /** 节拍正文结束行号（不含；下一个 h1–h4 标题行或文件尾） */
  endLine: number;
}

const BEAT_HEADER_RE = /^####\s+(beat_[A-Za-z0-9_]+)\s*(（.*)?$/;
const CHAPTER_HEADER_RE = /^##\s*章节\s*(\d+)\s*[：:]\s*(.*)$/;
const HEADER_RE = /^(#{1,4})\s/;

/** 节拍头行号 → beat id（无则 null） */
export function beatIdOf(line: string): string | null {
  const m = BEAT_HEADER_RE.exec(line.trim());
  return m ? m[1] : null;
}

/** 定位节拍区段（头行 + 正文结束行） */
export function findBeatRange(md: string, beatId: string): BeatRange | null {
  const lines = md.split("\n");
  let headerLine = -1;
  for (let i = 0; i < lines.length; i++) {
    if (beatIdOf(lines[i]) === beatId) { headerLine = i; break; }
  }
  if (headerLine < 0) return null;
  let endLine = lines.length;
  for (let i = headerLine + 1; i < lines.length; i++) {
    if (HEADER_RE.test(lines[i])) { endLine = i; break; }
  }
  return { headerLine, endLine };
}

/** 读取节拍正文（去首尾空行） */
export function getBeatBody(md: string, beatId: string): string {
  const range = findBeatRange(md, beatId);
  if (!range) return "";
  return md.split("\n").slice(range.headerLine + 1, range.endLine).join("\n").trim();
}

/** 章节区段行范围（[头行, 结束行)；无该章节返回 null） */
export function findChapterRange(md: string, chapterIdx: number): { headerLine: number; endLine: number } | null {
  const lines = md.split("\n");
  let headerLine = -1;
  for (let i = 0; i < lines.length; i++) {
    const m = CHAPTER_HEADER_RE.exec(lines[i].trim());
    if (m && parseInt(m[1], 10) === chapterIdx) { headerLine = i; break; }
  }
  if (headerLine < 0) return null;
  let endLine = lines.length;
  for (let i = headerLine + 1; i < lines.length; i++) {
    if (/^##\s/.test(lines[i])) { endLine = i; break; }
  }
  return { headerLine, endLine };
}

/** 生成未占用的 beat id */
export function nextBeatId(md: string, prefix = "beat_new"): string {
  const used = new Set<string>();
  for (const line of md.split("\n")) {
    const id = beatIdOf(line);
    if (id) used.add(id);
  }
  if (!used.has(prefix)) return prefix;
  for (let i = 2; ; i++) {
    if (!used.has(`${prefix}_${i}`)) return `${prefix}_${i}`;
  }
}

function beatBlock(beatId: string, body: string, keepOnDeviate: boolean): string[] {
  const flag = keepOnDeviate ? "true" : "false";
  return [`#### ${beatId}（keep_on_deviate: ${flag}）`, "", body.trim() || "（待补充）", ""];
}

/** 更新节拍：替换正文与/或改写 keep_on_deviate 标记；返回新 md（节拍不存在返回原文） */
export function updateBeat(
  md: string, beatId: string,
  opts: { body?: string; keepOnDeviate?: boolean },
): string {
  const range = findBeatRange(md, beatId);
  if (!range) return md;
  const lines = md.split("\n");
  const header = lines[range.headerLine];
  const flag = opts.keepOnDeviate === undefined
    ? null
    : `#### ${beatId}（keep_on_deviate: ${opts.keepOnDeviate ? "true" : "false"}）`;
  const bodyLines = opts.body === undefined
    ? lines.slice(range.headerLine + 1, range.endLine)
    : (opts.body.trim() || "（待补充）").split("\n");
  const next = [
    ...lines.slice(0, range.headerLine),
    ...(flag ? [flag] : [header]),
    "",
    ...bodyLines,
    "",
    ...lines.slice(range.endLine),
  ];
  return next.join("\n");
}

/** 删除节拍（连同其正文）；返回新 md（节拍不存在返回原文） */
export function deleteBeat(md: string, beatId: string): string {
  const range = findBeatRange(md, beatId);
  if (!range) return md;
  const lines = md.split("\n");
  return [
    ...lines.slice(0, range.headerLine),
    ...lines.slice(range.endLine),
  ].join("\n");
}

/** 在章节内插入新节拍：afterBeatId 之后，或章节末尾（chapterIdx）。
 * 返回新 md；章节不存在时返回原文。 */
export function insertBeat(
  md: string,
  chapterIdx: number,
  afterBeatId: string | null,
  beatId: string,
  body = "",
  keepOnDeviate = true,
): string {
  const lines = md.split("\n");
  let insertAt = -1;
  if (afterBeatId) {
    const range = findBeatRange(md, afterBeatId);
    if (range) insertAt = range.endLine;
  }
  if (insertAt < 0) {
    const chapter = findChapterRange(md, chapterIdx);
    if (!chapter) return md;
    insertAt = chapter.endLine;
  }
  const block = ["", ...beatBlock(beatId, body, keepOnDeviate)];
  return [
    ...lines.slice(0, insertAt),
    ...block,
    ...lines.slice(insertAt),
  ].join("\n");
}

/** 在剧情叙述区末尾追加新章节（含首个占位节拍），返回新 md。
 * 插入点 = 第一个章节起、之后第一个非章节 h2（如「关键对话参考」）之前；
 * 没有任何章节时追加到文件末尾（测试剧情形态）。 */
export function addChapter(
  md: string,
  chapterIdx: number,
  title: string,
  beatId: string,
): string {
  const lines = md.split("\n");
  let firstChapter = -1;
  for (let i = 0; i < lines.length; i++) {
    if (CHAPTER_HEADER_RE.test(lines[i].trim())) { firstChapter = i; break; }
  }
  let insertAt = lines.length;
  if (firstChapter >= 0) {
    for (let i = firstChapter + 1; i < lines.length; i++) {
      if (/^##\s/.test(lines[i]) && !CHAPTER_HEADER_RE.test(lines[i].trim())) {
        insertAt = i;
        break;
      }
    }
  }
  const block = [
    "",
    `## 章节 ${chapterIdx}：${title || "新章节"}`,
    "",
    "### 关键节拍",
    "",
    ...beatBlock(beatId, "（待补充）", true),
  ];
  return [...lines.slice(0, insertAt), ...block, ...lines.slice(insertAt)].join("\n");
}

/** 剧情叙述区的下一个章节序号（无章节时为 1） */
export function nextChapterIdx(md: string): number {
  let max = 0;
  for (const line of md.split("\n")) {
    const m = CHAPTER_HEADER_RE.exec(line.trim());
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return max + 1;
}
