export const RAIL_MIN_WIDTH = 220;
export const RAIL_MAX_WIDTH = 480;
export const RAIL_DEFAULT_WIDTH = 292;

export const INSPECTOR_MIN_WIDTH = 240;
export const INSPECTOR_MAX_WIDTH = 500;
export const INSPECTOR_DEFAULT_WIDTH = 300;

export const RESIZER_SIZE = 6;

export const KEYBOARD_STEP = 8;

export const LAYOUT_STORAGE_KEY = "world-sim-2d.panelLayout";

export interface StoredPanelLayout {
  railWidth: number;
  inspectorWidth: number;
}

export function clampRailWidth(width: number): number {
  return Math.min(RAIL_MAX_WIDTH, Math.max(RAIL_MIN_WIDTH, width));
}

export function clampInspectorWidth(width: number): number {
  return Math.min(INSPECTOR_MAX_WIDTH, Math.max(INSPECTOR_MIN_WIDTH, width));
}

export function storedPanelLayout(): StoredPanelLayout {
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(LAYOUT_STORAGE_KEY) ?? "null",
    ) as Partial<StoredPanelLayout> | null;
    return {
      railWidth: Number.isFinite(parsed?.railWidth)
        ? clampRailWidth(Number(parsed?.railWidth))
        : RAIL_DEFAULT_WIDTH,
      inspectorWidth: Number.isFinite(parsed?.inspectorWidth)
        ? clampInspectorWidth(Number(parsed?.inspectorWidth))
        : INSPECTOR_DEFAULT_WIDTH,
    };
  } catch {
    return { railWidth: RAIL_DEFAULT_WIDTH, inspectorWidth: INSPECTOR_DEFAULT_WIDTH };
  }
}

export function persistPanelLayout(railWidth: number, inspectorWidth: number): void {
  const layout: StoredPanelLayout = {
    railWidth: Math.round(railWidth),
    inspectorWidth: Math.round(inspectorWidth),
  };
  try {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Layout persistence is optional.
  }
}
