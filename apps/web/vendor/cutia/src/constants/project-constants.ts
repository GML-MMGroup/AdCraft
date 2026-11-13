import type { TCanvasSize } from "@/types/project";

export interface CanvasSizePreset {
	label: string;
	width: number;
	height: number;
}

export const CANVAS_SIZE_PRESETS: CanvasSizePreset[] = [
	{ label: "480p", width: 854, height: 480 },
	{ label: "720p", width: 1280, height: 720 },
	{ label: "768p", width: 1366, height: 768 },
	{ label: "1080p", width: 1920, height: 1080 },
	{ label: "720p Portrait", width: 720, height: 1280 },
	{ label: "1080p Portrait", width: 1080, height: 1920 },
	{ label: "2K", width: 2560, height: 1440 },
];

export const DEFAULT_CANVAS_PRESETS: TCanvasSize[] = [
	{ width: 1920, height: 1080 },
	{ width: 1080, height: 1920 },
	{ width: 1080, height: 1080 },
	{ width: 1440, height: 1080 },
];

export const FPS_PRESETS = [
	{ value: "24", label: "24 fps" },
	{ value: "25", label: "25 fps" },
	{ value: "30", label: "30 fps" },
	{ value: "60", label: "60 fps" },
	{ value: "120", label: "120 fps" },
] as const;

export const BLUR_INTENSITY_PRESETS: { label: string; value: number }[] = [
	{ label: "Light", value: 4 },
	{ label: "Medium", value: 8 },
	{ label: "Heavy", value: 18 },
] as const;

export const DEFAULT_CANVAS_SIZE: TCanvasSize = { width: 1920, height: 1080 };
export const DEFAULT_FPS = 30;
export const DEFAULT_BLUR_INTENSITY = 8;
export const DEFAULT_COLOR = "#000000";
