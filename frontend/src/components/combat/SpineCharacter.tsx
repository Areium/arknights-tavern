/**
 * R3F + spine-threejs bridge component.
 *
 * Loads .skel / .atlas / .png assets via the Spine AssetManager, creates a
 * SkeletonMesh imperatively in the R3F scene, and drives animation via useFrame.
 *
 * Usage (inside an R3F <Canvas>):
 *   <SpineCharacter
 *     assetPath="/api/assets/characters/临光/spine/char_148_nearl/Front"
 *     atlasFile="char_148_nearl.atlas"
 *     skelFile="char_148_nearl.skel"
 *     animation="idle"
 *     scale={0.02}
 *   />
 */
import { useEffect, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AssetManager,
  SkeletonMesh,
} from "@esotericsoftware/spine-threejs";
import {
  AtlasAttachmentLoader,
  SkeletonBinary,
  SkeletonData,
  TextureAtlas,
} from "@esotericsoftware/spine-core";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SpineCharacterHandle {
  setAnimation: (name: string, loop?: boolean) => void;
  getAnimations: () => string[];
}

export interface SpineCharacterProps {
  assetPath: string;
  atlasFile: string;
  skelFile: string;
  animation?: string;
  scale?: number;
  position?: [number, number, number];
  rotationY?: number;
  onLoad?: (animations: string[]) => void;
  onError?: (err: Error) => void;
}

// ---------------------------------------------------------------------------
// Cache — avoid reloading the same skeleton data
// ---------------------------------------------------------------------------

const skeletonCache = new Map<string, SkeletonData>();

async function loadSkeletonData(
  assetPath: string,
  atlasFile: string,
  skelFile: string,
): Promise<SkeletonData> {
  const key = `${assetPath}|${atlasFile}|${skelFile}`;
  const cached = skeletonCache.get(key);
  if (cached) return cached;

  const prefix = assetPath.endsWith("/") ? assetPath : assetPath + "/";
  const mgr = new AssetManager(prefix);

  mgr.loadTextureAtlas(atlasFile);
  mgr.loadBinary(skelFile);
  await mgr.loadAll();

  if (mgr.hasErrors()) {
    const errs = mgr.getErrors();
    const first = Object.entries(errs)[0];
    throw new Error(`Spine load error: ${first?.[0]}: ${first?.[1]}`);
  }

  const atlas = mgr.get(atlasFile) as TextureAtlas;
  const binary = mgr.get(skelFile) as Uint8Array;

  const attachmentLoader = new AtlasAttachmentLoader(atlas);
  const reader = new SkeletonBinary(attachmentLoader);
  const sd = reader.readSkeletonData(binary);

  skeletonCache.set(key, sd);
  return sd;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SpineCharacter({
  assetPath,
  atlasFile,
  skelFile,
  animation = "idle",
  scale = 1,
  position = [0, 0, 0],
  rotationY = 0,
  onLoad,
  onError,
}: SpineCharacterProps) {
  const meshRef = useRef<SkeletonMesh | null>(null);
  const { scene } = useThree();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track latest animation prop without causing re-binds
  const animRef = useRef(animation);
  animRef.current = animation;

  // --- Load assets & create mesh (once per assetPath/atlasFile/skelFile) ---

  useEffect(() => {
    let cancelled = false;

    loadSkeletonData(assetPath, atlasFile, skelFile)
      .then((sd) => {
        if (cancelled) return;

        const mesh = new SkeletonMesh({ skeletonData: sd });
        mesh.scale.setScalar(scale);
        mesh.position.set(position[0], position[1], position[2]);
        mesh.rotation.y = rotationY;

        // Play initial animation
        const names = sd.animations.map((a) => a.name);
        const target = animRef.current;
        if (target && sd.animations.some((a) => a.name === target)) {
          mesh.state.setAnimation(0, target, true);
        }

        meshRef.current = mesh;
        scene.add(mesh);
        setReady(true);
        onLoad?.(names);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        console.error("[SpineCharacter]", err);
        setError(err.message);
        onError?.(err);
      });

    return () => {
      cancelled = true;
      if (meshRef.current) {
        scene.remove(meshRef.current);
        meshRef.current.dispose();
        meshRef.current = null;
        setReady(false);
      }
    };
  }, [assetPath, atlasFile, skelFile]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Sync transform when props change ---

  useEffect(() => {
    const m = meshRef.current;
    if (!m) return;
    m.scale.setScalar(scale);
    m.position.set(position[0], position[1], position[2]);
    m.rotation.y = rotationY;
  }, [scale, position[0], position[1], position[2], rotationY]);

  // --- Per-frame: switch animation + update skeleton ---

  useFrame((_, delta) => {
    const m = meshRef.current;
    if (!m) return;

    // Safe delta clamp (avoid huge jumps on tab-away)
    const dt = Math.min(delta, 0.1);

    const target = animRef.current;
    const current = m.state.getCurrent(0);
    if (target && current?.animation?.name !== target) {
      const sd = m.state.data.skeletonData;
      if (sd.animations.some((a) => a.name === target)) {
        m.state.setAnimation(0, target, true);
      }
    }

    m.update(dt);
  });

  // R3F renders nothing declaratively — mesh is managed imperatively.
  return null;
}
