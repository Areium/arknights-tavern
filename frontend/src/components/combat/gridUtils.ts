export type Point = { x: number; y: number };

/** Get the screen-space center of a grid cell by walking the DOM.
 *  Works correctly under any CSS 3D transform (rotateX, rotateZ, perspective). */
export function getCellCenter(
  gridEl: HTMLElement,
  row: number,
  col: number,
): Point | null {
  try {
    const rowEl = gridEl.children[row + 1]; // +1 skip column-labels row
    if (!rowEl) return null;
    // rowEl.children: [0]=row label, [1]=cells container div
    const cellsContainer = rowEl.children[1] as HTMLElement | undefined;
    if (!cellsContainer) return null;
    const cellEl = cellsContainer.children[col] as HTMLElement | undefined;
    if (!cellEl) return null;
    const r = cellEl.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  } catch {
    return null;
  }
}

/** Get cell center relative to a parent element (for absolute positioning of overlays). */
export function getCellParentRelative(
  gridEl: HTMLElement,
  parentEl: HTMLElement,
  row: number,
  col: number,
): Point | null {
  const screen = getCellCenter(gridEl, row, col);
  if (!screen) return null;
  const pr = parentEl.getBoundingClientRect();
  return { x: screen.x - pr.left, y: screen.y - pr.top };
}
