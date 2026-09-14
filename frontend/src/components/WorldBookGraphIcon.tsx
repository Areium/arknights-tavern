export type WorldBookGraphIconName = "graph" | "search" | "folder" | "link" | "pin" | "fit" | "layout" | "panel" | "close" | "preview" | "tree" | "tag";

const PATHS: Record<WorldBookGraphIconName, string> = {
  graph: "M8 6h8M6 8v8m12-8v8M8 18h8M8 8l8 8M8 16l8-8 M8 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0M20 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  search: "m16 16 4 4M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  folder: "M3 7V5h6l2 2h10v12H3V7Z",
  link: "m10 13 4-4m-6 6-2 2a3 3 0 0 1-4-4l4-4a3 3 0 0 1 4 0m4 0 2-2a3 3 0 0 1 4 4l-4 4a3 3 0 0 1-4 0",
  pin: "m9 3 6 0-1 6 4 4H6l4-4-1-6ZM12 13v8",
  fit: "M3 9V3h6m6 0h6v6m0 6v6h-6m-6 0H3v-6M8 8h8v8H8Z",
  layout: "M4 4h5v5H4ZM15 4h5v5h-5ZM9 15h6v5H9ZM6 9v3h12V9m-6 3v3",
  panel: "M3 4h18v16H3ZM9 4v16M5 8h2m-2 4h2",
  close: "m6 6 12 12M6 18 18 6",
  preview: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  tree: "M12 4v4M6 12v2M18 12v2M12 8H6v4M12 8h6v4M4 17h4M10 17h4M16 17h4",
  tag: "M3 4h9l9 8-9 8H3V4Zm4 6.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3Z",
};

export default function WorldBookGraphIcon({ name, size = 16 }: { name: WorldBookGraphIconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={PATHS[name]} /></svg>;
}
