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
    const before = match[1];
    const dialogue = match[2];

    if (before) {
      segments.push({ type: "narration", text: before });
    }

    let speaker: string | undefined;
    if (knownSpeaker) {
      speaker = knownSpeaker;
    } else if (sceneCharacters.length > 0) {
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
