interface NarrationTextProps {
  text: string;
}

export default function NarrationText({ text }: NarrationTextProps) {
  return (
    <div className="text-sm text-amber-100/90 italic leading-relaxed my-2 px-4 py-2.5 rounded-xl bg-amber-900/30 border border-amber-700/20 whitespace-pre-wrap">
      {text}
    </div>
  );
}
