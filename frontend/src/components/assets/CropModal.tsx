import { useState, useRef, useEffect, useCallback } from "react";
import type { SkinCrop } from "../../types";

interface Props {
  imageUrl: string;
  onSave: (crop: SkinCrop) => void;
  onClose: () => void;
}

const CARD_ASPECT = 154 / 80;

export default function CropModal({ imageUrl, onSave, onClose }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [imgNatural, setImgNatural] = useState<{ w: number; h: number } | null>(null);
  const [crop, setCrop] = useState<SkinCrop>({ x: 10, y: 10, w: 80, h: 70 });
  const cropRef = useRef(crop);
  cropRef.current = crop;

  type DragType = "move" | "resize_br" | "resize_tl" | "resize_tr" | "resize_bl";

  const dragRef = useRef<{
    type: DragType;
    sx: number; sy: number; start: SkinCrop;
  } | null>(null);

  // Locked aspect ratio in percentage space: w/h = CARD_ASPECT * (imgH / imgW)
  const pctAspect = imgNatural ? CARD_ASPECT * (imgNatural.h / imgNatural.w) : CARD_ASPECT;

  const clamp = useCallback((c: SkinCrop): SkinCrop => {
    const x = Math.max(0, Math.min(100 - Math.max(c.w, 5), c.x));
    const y = Math.max(0, Math.min(100 - Math.max(c.h, 5), c.y));
    const w = Math.max(5, Math.min(100 - x, c.w));
    const h = Math.max(5, Math.min(100 - y, c.h));
    return { x, y, w, h };
  }, []);

  const toPctDelta = useCallback((clientX: number, clientY: number, sx: number, sy: number) => {
    const rect = imgRef.current?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) return { dx: 0, dy: 0 };
    return { dx: ((clientX - sx) / rect.width) * 100, dy: ((clientY - sy) / rect.height) * 100 };
  }, []);

  const onMouseDown = (e: React.MouseEvent, type: DragType) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { type, sx: e.clientX, sy: e.clientY, start: { ...cropRef.current } };
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const { dx, dy } = toPctDelta(e.clientX, e.clientY, d.sx, d.sy);
      const start = d.start;
      let next: SkinCrop;

      if (d.type === "move") {
        next = { ...start, x: start.x + dx, y: start.y + dy };
      } else {
        const aspect = imgNatural
          ? CARD_ASPECT * (imgNatural.h / imgNatural.w)
          : CARD_ASPECT;
        if (d.type === "resize_br") {
          const nw = Math.max(5, start.w + dx);
          next = { ...start, w: nw, h: nw / aspect };
        } else if (d.type === "resize_tl") {
          const nw = Math.max(5, start.w - dx);
          const nh = nw / aspect;
          next = { x: start.x + start.w - nw, y: start.y + start.h - nh, w: nw, h: nh };
        } else if (d.type === "resize_tr") {
          const nw = Math.max(5, start.w + dx);
          const nh = nw / aspect;
          next = { ...start, y: start.y + start.h - nh, w: nw, h: nh };
        } else {
          // resize_bl
          const nw = Math.max(5, start.w - dx);
          const nh = nw / aspect;
          next = { ...start, x: start.x + start.w - nw, w: nw, h: nh };
        }
      }
      setCrop(clamp(next));
    };

    const onUp = () => { dragRef.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [clamp, toPctDelta, imgNatural]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Enter") onSave(cropRef.current);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onSave]);

  const handleImgLoad = () => {
    if (imgRef.current) {
      setImgNatural({ w: imgRef.current.naturalWidth, h: imgRef.current.naturalHeight });
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/85 flex flex-col items-center justify-center gap-4"
      onClick={onClose}
    >
      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap justify-center px-4">
        <span className="text-gray-400 text-xs">拖拽移动选框 · 拖拽边角缩放</span>
        <button
          onClick={() => setCrop({ x: 10, y: 10, w: 80, h: 70 })}
          className="px-3 py-1.5 text-xs rounded bg-gray-700/60 text-gray-300 hover:bg-gray-600/60 transition-colors"
        >
          重置
        </button>
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-xs rounded bg-gray-700/60 text-gray-300 hover:bg-gray-600/60 transition-colors"
        >
          取消
        </button>
        <button
          onClick={() => onSave(crop)}
          className="px-4 py-1.5 text-xs rounded bg-amber-600/80 text-white hover:bg-amber-500/80 transition-colors font-bold"
        >
          确定
        </button>
      </div>

      {/* Image + crop overlay */}
      <div className="relative" onClick={(e) => e.stopPropagation()}>
        <img
          ref={imgRef}
          src={imageUrl}
          alt=""
          onLoad={handleImgLoad}
          className="max-h-[72vh] max-w-[88vw] object-contain select-none"
          draggable={false}
        />

        {imgNatural && (
          <div
            className="absolute border-2 border-amber-400/80 cursor-move"
            style={{
              left: `${crop.x}%`,
              top: `${crop.y}%`,
              width: `${crop.w}%`,
              height: `${crop.h}%`,
              boxShadow: "0 0 0 9999px rgba(0,0,0,0.55)",
            }}
            onMouseDown={(e) => onMouseDown(e, "move")}
          >
            {/* 四角拖拽手柄 */}
            <div
              className="absolute -right-1.5 -bottom-1.5 w-3.5 h-3.5 bg-white rounded-full border border-gray-400 cursor-se-resize"
              onMouseDown={(e) => onMouseDown(e, "resize_br")}
            />
            <div
              className="absolute -left-1.5 -top-1.5 w-3.5 h-3.5 bg-white rounded-full border border-gray-400 cursor-nw-resize"
              onMouseDown={(e) => onMouseDown(e, "resize_tl")}
            />
            <div
              className="absolute -right-1.5 -top-1.5 w-3.5 h-3.5 bg-white rounded-full border border-gray-400 cursor-ne-resize"
              onMouseDown={(e) => onMouseDown(e, "resize_tr")}
            />
            <div
              className="absolute -left-1.5 -bottom-1.5 w-3.5 h-3.5 bg-white rounded-full border border-gray-400 cursor-sw-resize"
              onMouseDown={(e) => onMouseDown(e, "resize_bl")}
            />
          </div>
        )}
      </div>
    </div>
  );
}
