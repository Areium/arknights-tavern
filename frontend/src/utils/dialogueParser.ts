export interface DialogueSegment {
  type: "narration" | "dialogue";
  text: string;
  speaker?: string;
}

/**
 * Parse narrative text into dialogue and narration segments.
 *
 * Extracts text wrapped in 「」 as dialogue bubbles; everything else
 * becomes narration text. Speaker identification relies solely on
 * matching scene character names in the preceding narration text.
 * Adjacent 「」 pairs with little/no gap inherit the last speaker.
 */
export function parseDialogue(
  text: string,
  knownSpeaker: string | undefined,
  sceneCharacters: string[],
): DialogueSegment[] {
  if (!text) return [];

  const segments: DialogueSegment[] = [];
  const regex = /([^「]*)「([^」]+)」/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let lastSpeaker: string | undefined;

  while ((match = regex.exec(text)) !== null) {
    const rawBefore = match[1];
    const dialogue = match[2];
    let before = rawBefore;

    // 说话人优先取引号前的“角色名：/角色说：”前缀，并把前缀从叙述里剥离，
    // 避免“银灰：”这类署名残留在叙述文字中。
    let speaker: string | undefined = knownSpeaker;
    if (!speaker) {
      const extracted = extractSpeakerBefore(rawBefore, sceneCharacters);
      speaker = extracted.speaker;
      before = extracted.cleanBefore;
    }

    if (!speaker && sceneCharacters.length > 0) {
      if (before) {
        speaker = inferSpeaker(before, sceneCharacters);
      }
      if (!speaker && lastSpeaker && (!before || before.trim().length < 15)) {
        speaker = lastSpeaker;
      }
    }

    if (speaker) {
      lastSpeaker = speaker;
    }

    if (before && before.trim()) {
      segments.push({ type: "narration", text: before });
    }
    segments.push({ type: "dialogue", text: dialogue, speaker });

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    const remainder = text.slice(lastIndex);
    if (remainder.trim()) {
      segments.push({ type: "narration", text: remainder });
    }
  }

  if (segments.length === 0) {
    return [{ type: "narration", text }];
  }

  return segments;
}

/**
 * Normalize dialogue segments before rendering — LLM 输出的结构化片段
 * 可能缺字段/含非法类型，这里做容错规范化：
 * - 过滤 text 为空或非字符串的段
 * - dialogue 缺 speaker 时继承上一条 dialogue 的说话人（连续对话场景）
 * - 未知 type 降级为叙述，避免产生错误气泡
 */
export function normalizeSegments(
  segments: ReadonlyArray<{ type?: string; text?: unknown; speaker?: unknown }>,
): DialogueSegment[] {
  if (!Array.isArray(segments)) return [];
  const result: DialogueSegment[] = [];
  let lastSpeaker: string | undefined;

  for (const seg of segments) {
    if (!seg || typeof seg !== "object") continue;
    const text = typeof seg.text === "string" ? seg.text.trim() : "";
    if (!text) continue;

    if (seg.type === "narration") {
      result.push({ type: "narration", text });
      continue;
    }

    if (seg.type === "dialogue") {
      let speaker =
        typeof seg.speaker === "string" && seg.speaker.trim()
          ? seg.speaker.trim()
          : undefined;
      if (!speaker) speaker = lastSpeaker;
      if (speaker) lastSpeaker = speaker;
      result.push({ type: "dialogue", text, speaker });
      continue;
    }

    // 未知 type：降级为叙述，避免渲染出错误气泡
    result.push({ type: "narration", text });
  }

  return result;
}

/**
 * 从引号前的叙述中提取“角色名：/角色名说道：”这类署名。
 * 若命中且名字在场景角色列表内，返回说话人并清掉该前缀（cleanBefore）。
 */
function extractSpeakerBefore(
  before: string,
  sceneCharacters: string[],
): { speaker?: string; cleanBefore: string } {
  if (!before) return { cleanBefore: before };

  // 角色：「...」
  let m = /([\u4e00-\u9fa5·A-Za-z0-9_-]{1,15})\s*[：:]\s*$/.exec(before);
  if (m && sceneCharacters.includes(m[1])) {
    return { speaker: m[1], cleanBefore: before.slice(0, m.index) };
  }

  // 角色说道：「...」/ 角色低声说：「...」
  m = /([\u4e00-\u9fa5·A-Za-z0-9_-]{1,15})(?:说道|轻声说|低声说|沉声说|笑着说|淡淡道|冷冷地说|冷冷道|问道|喊道|答道|回答(?:道)?|开口(?:道)?|喃喃道?|提醒道?|补充道?|重复道?|叹道?|解释(?:道)?|说|道|问|答|喊)\s*[：:]\s*$/.exec(before);
  if (m && sceneCharacters.includes(m[1])) {
    return { speaker: m[1], cleanBefore: before.slice(0, m.index) };
  }

  return { cleanBefore: before };
}

/**
 * Find a scene character name in the text preceding 「.
 * Searches the entire preceding text, preferring the name closest
 * to the dialogue bracket.
 */
function inferSpeaker(before: string, sceneCharacters: string[]): string | undefined {
  const sorted = [...sceneCharacters].sort((a, b) => b.length - a.length);
  let bestMatch: string | undefined;
  let bestPos = -1;

  for (const name of sorted) {
    const pos = before.lastIndexOf(name);
    if (pos > bestPos) {
      bestPos = pos;
      bestMatch = name;
    }
  }

  return bestMatch;
}
