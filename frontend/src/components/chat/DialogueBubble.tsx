import AvatarPlaceholder from "./AvatarPlaceholder";

function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!m) return null;
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

interface DialogueBubbleProps {
  text: string;
  speaker?: string;
  color?: string;
}

const FALLBACK_NAME_COLOR = "#d8b4fe";
const FALLBACK_BG = "rgba(88, 28, 135, 0.25)";
const FALLBACK_BORDER = "rgba(147, 51, 234, 0.3)";

export default function DialogueBubble({ text, speaker, color }: DialogueBubbleProps) {
  const isUnknown = !speaker;

  const rgb = color ? hexToRgb(color) : null;
  const nameStyle = rgb ? { color } : { color: FALLBACK_NAME_COLOR };
  const bubbleBg = rgb
    ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.18)`
    : FALLBACK_BG;
  const bubbleBorder = rgb
    ? `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.35)`
    : FALLBACK_BORDER;

  return (
    <div className="flex items-start gap-3 my-2">
      {isUnknown ? (
        <div className="w-8 h-8 rounded-full flex-shrink-0 border border-dashed border-gray-600/50" />
      ) : (
        <AvatarPlaceholder name={speaker!} size="sm" />
      )}

      <div className="flex flex-col max-w-[75%]">
        {speaker && (
          <span className="text-xs font-bold mb-0.5 ml-1" style={nameStyle}>
            {speaker}
          </span>
        )}

        <div
          className="border rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed text-gray-100"
          style={{
            backgroundColor: isUnknown ? "rgba(55, 65, 81, 0.4)" : bubbleBg,
            borderColor: isUnknown ? "rgba(75, 85, 99, 0.3)" : bubbleBorder,
          }}
        >
          <div className="whitespace-pre-wrap">{text}</div>
        </div>
      </div>
    </div>
  );
}
