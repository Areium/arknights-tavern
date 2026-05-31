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

/** Mirror of Python resolve_targets() in src/combat_engine/grid.py.
 *  Given a card's target pattern and origin cell, return affected positions. */
export function resolveTargetPattern(
  pattern: string,
  origin: [number, number],
  gridSize: number,
  direction: [number, number] = [0, 1],
): [number, number][] {
  const [r, c] = origin;
  let cells: [number, number][] = [];

  switch (pattern) {
    case "SINGLE":
    case "SELF":
      cells = [origin];
      break;
    case "ADJACENT":
      cells = [origin];
      for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]] as [number, number][]) {
        cells.push([r + dr, c + dc]);
      }
      break;
    case "CROSS":
      cells = [origin];
      for (const [dr, dc] of [[-2, 0], [-1, 0], [1, 0], [2, 0], [0, -2], [0, -1], [0, 1], [0, 2]] as [number, number][]) {
        cells.push([r + dr, c + dc]);
      }
      break;
    case "LINE_3": {
      const [dr, dc] = direction;
      for (let i = 0; i < 3; i++) {
        cells.push([r + dr * i, c + dc * i]);
      }
      break;
    }
    case "ROW":
      for (let col = 0; col < gridSize; col++) {
        cells.push([r, col]);
      }
      break;
    case "AREA_2X2":
      for (let dr = 0; dr < 2; dr++) {
        for (let dc = 0; dc < 2; dc++) {
          cells.push([r + dr, c + dc]);
        }
      }
      break;
    default:
      cells = [origin];
  }

  return cells.filter(([rr, cc]) => rr >= 0 && rr < gridSize && cc >= 0 && cc < gridSize);
}
