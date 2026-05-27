/**
 * 3D combat scene — replaces CombatGrid + ChibiSprite overlay.
 *
 * Uses react-three-fiber to render:
 *  - Isometric orthographic camera
 *  - Grid plane with cell highlight overlays
 *  - Spine-animated character instances per unit
 *  - Raycaster-based cell click / hover / drop detection
 *
 * Props mirror CombatGrid's public interface so CombatView can swap seamlessly.
 */
import { useCallback, useMemo, useRef, Suspense, forwardRef, useImperativeHandle } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrthographicCamera } from "@react-three/drei";
import * as THREE from "three";
import type { CombatUnitDTO } from "../../types";
import SpineCharacter from "./SpineCharacter";
import type { SpineCharacterHandle } from "./SpineCharacter";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** World-space size of one grid cell. */
const CELL_SIZE = 1.0;

/** Pre-defined highlight colours. */
const HIGHLIGHT_COLORS: Record<string, string> = {
  cursor: "#ffff88",
  target: "#ff4444",
  move: "#4488ff",
  selected: "#ffaa00",
  range: "#ff8800",
};

const HIGHLIGHT_OPACITY: Record<string, number> = {
  cursor: 0.4,
  target: 0.35,
  move: 0.25,
  selected: 0.3,
  range: 0.15,
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CombatScene3DHandle {
  /** Project a grid cell to its screen-space centre (or null if canvas isn't ready). */
  getCellScreenPos: (row: number, col: number) => { x: number; y: number } | null;
}

export interface CombatScene3DProps {
  gridSize: number;
  units: CombatUnitDTO[];
  moveHighlights: Set<string>;
  rangeHighlights: Set<string>;
  selectedUnitId: string | null;
  cursor: [number, number] | null;
  dragCell: [number, number] | null;
  onCellClick: (row: number, col: number) => void;
  onCellHover?: (row: number, col: number) => void;
  onCellLeave?: () => void;
  onCellDrop: (row: number, col: number) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Grid coordinate → world-space centre of the cell. */
function cellToWorld(row: number, col: number, gridSize: number): [number, number, number] {
  const offset = ((gridSize - 1) * CELL_SIZE) / 2;
  return [col * CELL_SIZE - offset, 0, row * CELL_SIZE - offset];
}

/** Convert a world-space point on the ground plane to grid (row, col). Returns null if outside. */
function worldToCell(x: number, z: number, gridSize: number): [number, number] | null {
  const offset = ((gridSize - 1) * CELL_SIZE) / 2;
  const col = Math.round((x + offset) / CELL_SIZE);
  const row = Math.round((z + offset) / CELL_SIZE);
  if (row < 0 || row >= gridSize || col < 0 || col >= gridSize) return null;
  return [row, col];
}

// ---------------------------------------------------------------------------
// Spine variant discovery (POC — hardcoded; later replaced by API)
// ---------------------------------------------------------------------------

const DEFAULT_SPINE_VARIANT: Record<string, string> = {
  "临光": "char_148_nearl",
  "佐菲娅": "char_265_sophia",
  "德克萨斯": "char_102_texas",
  "玛恩纳·临光": "char_4064_mlynar",
  "瑕光": "char_423_blemsh",
  "砾": "char_237_gravel",
  "银灰": "char_172_svrash",
  "闪灵": "char_147_shining",
  "阿米娅": "char_002_amiya",
  "陈": "char_010_chen",
};

function getSpineAssetUrl(name: string, direction: "Front" | "Back"): string {
  return `/api/assets/characters/${encodeURIComponent(name)}/spine/${DEFAULT_SPINE_VARIANT[name]}/${direction}`;
}

function getSpineFiles(name: string): { atlas: string; skel: string } {
  const variant = DEFAULT_SPINE_VARIANT[name];
  return {
    atlas: `${variant}.atlas`,
    skel: `${variant}.skel`,
  };
}

function hasSpine(name: string): boolean {
  return name in DEFAULT_SPINE_VARIANT;
}

// ---------------------------------------------------------------------------
// Grid cell highlight quad (single cell overlay)
// ---------------------------------------------------------------------------

function HighlightCell({
  row,
  col,
  gridSize,
  color,
  opacity,
}: {
  row: number;
  col: number;
  gridSize: number;
  color: string;
  opacity: number;
}) {
  const [cx, , cz] = cellToWorld(row, col, gridSize);
  const half = CELL_SIZE * 0.45;
  return (
    <mesh position={[cx, 0.005, cz]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[half * 2, half * 2]} />
      <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Grid plane with lines
// ---------------------------------------------------------------------------

function GridPlane({ gridSize }: { gridSize: number }) {
  const totalSize = gridSize * CELL_SIZE;
  const half = totalSize / 2;
  const lineColor = "#334466";
  const lineWidth = 0.02;

  // Each grid line is a thin box
  const lines: THREE.Vector3[] = [];
  for (let i = 0; i <= gridSize; i++) {
    const pos = i * CELL_SIZE - half;
    lines.push(new THREE.Vector3(pos, 0.001, -half)); // vertical line start
    lines.push(new THREE.Vector3(pos, 0.001, half));   // vertical line end
    lines.push(new THREE.Vector3(-half, 0.001, pos));   // horizontal line start
    lines.push(new THREE.Vector3(half, 0.001, pos));    // horizontal line end
  }

  return (
    <group>
      {/* Base plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[totalSize, totalSize]} />
        <meshStandardMaterial color="#1a1e2e" roughness={0.9} />
      </mesh>
      {/* Grid lines */}
      {Array.from({ length: gridSize + 1 }, (_, i) => {
        const pos = i * CELL_SIZE - half;
        return (
          <group key={i}>
            {/* vertical */}
            <mesh position={[pos, 0.002, 0]} scale={[lineWidth, 1, totalSize]}>
              <boxGeometry />
              <meshBasicMaterial color={lineColor} transparent opacity={0.5} depthWrite={false} />
            </mesh>
            {/* horizontal */}
            <mesh position={[0, 0.002, pos]} scale={[totalSize, 1, lineWidth]}>
              <boxGeometry />
              <meshBasicMaterial color={lineColor} transparent opacity={0.5} depthWrite={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

// ---------------------------------------------------------------------------
// User-interaction overlay (invisible plane for raycaster)
// ---------------------------------------------------------------------------

function ClickPlane({
  gridSize,
  onCellClick,
  onCellHover,
  onCellLeave,
  onCellDrop,
}: {
  gridSize: number;
  onCellClick: (r: number, c: number) => void;
  onCellHover?: (r: number, c: number) => void;
  onCellLeave?: () => void;
  onCellDrop: (r: number, c: number) => void;
}) {
  const planeRef = useRef<THREE.Mesh>(null);
  const totalSize = gridSize * CELL_SIZE;
  const raycaster = useMemo(() => new THREE.Raycaster(), []);
  const groundPlane = useMemo(() => new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), []);
  const lastCell = useRef<string | null>(null);

  const { camera, gl } = useThree();

  const pointerToCell = useCallback(
    (clientX: number, clientY: number): [number, number] | null => {
      const rect = gl.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((clientX - rect.left) / rect.width) * 2 - 1,
        -((clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(mouse, camera);
      const intersection = new THREE.Vector3();
      const hit = raycaster.ray.intersectPlane(groundPlane, intersection);
      if (!hit) return null;
      return worldToCell(intersection.x, intersection.z, gridSize);
    },
    [camera, gl, gridSize, raycaster, groundPlane],
  );

  return (
    <mesh
      ref={planeRef}
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, 0.003, 0]}
      visible={false}
      onClick={(e) => {
        const cell = pointerToCell(e.clientX, e.clientY);
        if (cell) onCellClick(cell[0], cell[1]);
      }}
      onPointerMove={(e) => {
        const cell = pointerToCell(e.clientX, e.clientY);
        const key = cell ? `${cell[0]},${cell[1]}` : null;
        if (key !== lastCell.current) {
          lastCell.current = key;
          if (cell) onCellHover?.(cell[0], cell[1]);
          else onCellLeave?.();
        }
      }}
      onPointerOut={() => {
        lastCell.current = null;
        onCellLeave?.();
      }}
      onPointerUp={(e) => {
        const cell = pointerToCell(e.clientX, e.clientY);
        if (cell) onCellDrop(cell[0], cell[1]);
      }}
    >
      <planeGeometry args={[totalSize, totalSize]} />
      <meshBasicMaterial visible={false} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Unit character controller — places a Spine animation on a grid cell
// ---------------------------------------------------------------------------

function UnitCharacter({
  unit,
  gridSize,
  selected,
}: {
  unit: CombatUnitDTO;
  gridSize: number;
  selected: boolean;
}) {
  const [wx, wy, wz] = cellToWorld(unit.pos[0], unit.pos[1], gridSize);
  const direction = unit.team === "player" ? "Front" : "Back";
  const assetPath = getSpineAssetUrl(unit.name, direction);
  const files = getSpineFiles(unit.name);
  const yRotation = unit.team === "player" ? 0 : Math.PI;

  // Debug: show a coloured box for units without spine data
  if (!hasSpine(unit.name)) {
    const color = unit.team === "player" ? "#4488cc" : "#cc4444";
    return (
      <group position={[wx, 0.3, wz]}>
        <mesh>
          <boxGeometry args={[0.4, 0.6, 0.4]} />
          <meshStandardMaterial color={color} />
        </mesh>
        {/* Selection ring */}
        {selected && (
          <mesh position={[0, -0.3, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.25, 0.3, 32]} />
            <meshBasicMaterial color="#ffaa00" side={THREE.DoubleSide} depthWrite={false} />
          </mesh>
        )}
      </group>
    );
  }

  return (
    <group position={[wx, 0, wz]}>
      <Suspense fallback={null}>
        <SpineCharacter
          assetPath={assetPath}
          atlasFile={files.atlas}
          skelFile={files.skel}
          animation="idle"
          scale={0.002}
          rotationY={yRotation}
        />
      </Suspense>
      {/* Selection ring */}
      {selected && (
        <mesh position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.25, 0.3, 32]} />
          <meshBasicMaterial color="#ffaa00" side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Scene content (rendered inside Canvas)
// ---------------------------------------------------------------------------

function SceneContent({
  gridSize,
  units,
  moveHighlights,
  rangeHighlights,
  selectedUnitId,
  cursor,
  dragCell,
  onCellClick,
  onCellHover,
  onCellLeave,
  onCellDrop,
  handleRef,
}: CombatScene3DProps & { handleRef: React.MutableRefObject<CombatScene3DHandle | null> }) {
  const totalSize = gridSize * CELL_SIZE;
  const camDist = totalSize * 1.2;
  const half = totalSize / 2;
  const { camera, gl } = useThree();

  // Expose cell-to-screen projection for outer drag/drop overlay
  useImperativeHandle(handleRef, () => ({
    getCellScreenPos(row: number, col: number) {
      const [wx, , wz] = cellToWorld(row, col, gridSize);
      const world = new THREE.Vector3(wx, 0, wz);
      world.project(camera);
      const canvas = gl.domElement;
      const rect = canvas.getBoundingClientRect();
      return {
        x: rect.left + (world.x * 0.5 + 0.5) * rect.width,
        y: rect.top + (-world.y * 0.5 + 0.5) * rect.height,
      };
    },
  }), [camera, gl, gridSize]);

  return (
    <>
      {/* Isometric orthographic camera */}
      <OrthographicCamera
        makeDefault
        position={[half * 1.5, half * 1.8, half * 1.5]}
        left={-half * 1.2}
        right={half * 1.2}
        top={half * 1.2}
        bottom={-half * 1.2}
        near={0.1}
        far={camDist * 4}
      />
      {/* Look at centre */}
      <directionalLight position={[5, 10, 5]} intensity={0.8} />
      <ambientLight intensity={0.4} />

      {/* Grid */}
      <GridPlane gridSize={gridSize} />

      {/* Highlights */}
      {cursor && (
        <HighlightCell
          row={cursor[0]} col={cursor[1]} gridSize={gridSize}
          color={HIGHLIGHT_COLORS.cursor} opacity={HIGHLIGHT_OPACITY.cursor}
        />
      )}
      {dragCell && (
        <HighlightCell
          row={dragCell[0]} col={dragCell[1]} gridSize={gridSize}
          color={HIGHLIGHT_COLORS.target} opacity={HIGHLIGHT_OPACITY.target}
        />
      )}
      {[...moveHighlights].map((key) => {
        const [r, c] = key.split(",").map(Number);
        return (
          <HighlightCell
            key={`move-${key}`} row={r} col={c} gridSize={gridSize}
            color={HIGHLIGHT_COLORS.move} opacity={HIGHLIGHT_OPACITY.move}
          />
        );
      })}
      {[...rangeHighlights].map((key) => {
        const [r, c] = key.split(",").map(Number);
        return (
          <HighlightCell
            key={`range-${key}`} row={r} col={c} gridSize={gridSize}
            color={HIGHLIGHT_COLORS.range} opacity={HIGHLIGHT_OPACITY.range}
          />
        );
      })}
      {units
        .filter((u) => u.is_alive && u.unit_id === selectedUnitId)
        .map((u) => (
          <HighlightCell
            key={`sel-${u.unit_id}`} row={u.pos[0]} col={u.pos[1]} gridSize={gridSize}
            color={HIGHLIGHT_COLORS.selected} opacity={HIGHLIGHT_OPACITY.selected}
          />
        ))}

      {/* Units */}
      {units
        .filter((u) => u.is_alive)
        .map((u) => (
          <UnitCharacter
            key={u.unit_id}
            unit={u}
            gridSize={gridSize}
            selected={u.unit_id === selectedUnitId}
          />
        ))}

      {/* Invisible click surface */}
      <ClickPlane
        gridSize={gridSize}
        onCellClick={onCellClick}
        onCellHover={onCellHover}
        onCellLeave={onCellLeave}
        onCellDrop={onCellDrop}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Public component wrapper
// ---------------------------------------------------------------------------

const CombatScene3D = forwardRef<CombatScene3DHandle, CombatScene3DProps>(function CombatScene3D(props, ref) {
  const handleRef = useRef<CombatScene3DHandle | null>(null);
  useImperativeHandle(ref, () => handleRef.current!, [handleRef]);

  // Compute canvas pixel size: each cell ≈ 64px (at scale 1.0), plus labels & padding
  const gridPixelSize = props.gridSize * 68 + 40;
  const width = gridPixelSize;
  const height = Math.max(gridPixelSize * 0.75, 400);

  return (
    <div
      className="combat-scene-3d"
      style={{
        width,
        height,
        position: "relative",
        background: "radial-gradient(ellipse at center, #1a2040 0%, #0a0f1e 100%)",
      }}
    >
      <Canvas
        gl={{ antialias: true, alpha: false }}
        style={{ width: "100%", height: "100%" }}
      >
        <SceneContent {...props} handleRef={handleRef} />
      </Canvas>
    </div>
  );
});

export default CombatScene3D;
