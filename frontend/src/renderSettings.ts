export type MapClarity = "economy" | "standard" | "high" | "ultra";

export const MAP_CLARITY_OPTIONS: Array<{
  value: MapClarity;
  label: string;
  pixels: number;
  cost: string;
  detail: string;
}> = [
  { value: "economy", label: "省资源", pixels: 0.75, cost: "低", detail: "像素量约 0.6×" },
  { value: "standard", label: "标准", pixels: 1, cost: "基准", detail: "像素量约 1×" },
  { value: "high", label: "高清", pixels: 1.5, cost: "中", detail: "像素量约 2.25×" },
  { value: "ultra", label: "极清", pixels: 2, cost: "高", detail: "像素量约 4×" },
];

export const MAP_CLARITY_BY_VALUE = Object.fromEntries(
  MAP_CLARITY_OPTIONS.map((option) => [option.value, option]),
) as Record<MapClarity, (typeof MAP_CLARITY_OPTIONS)[number]>;
