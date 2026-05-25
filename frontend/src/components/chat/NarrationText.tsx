interface NarrationTextProps {
  text: string;
}

export default function NarrationText({ text }: NarrationTextProps) {
  return (
    <div className="text-sm text-amber-100/70 italic leading-relaxed my-2 ml-11">
      {text}
    </div>
  );
}
