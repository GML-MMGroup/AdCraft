import type { TextElement, TextStroke, TextShadow } from "@/types/timeline";

export interface TextStylePreset {
	id: string;
	name: string;
	styles: Partial<
		Pick<
			TextElement,
			"color" | "backgroundColor" | "stroke" | "shadow" | "fontWeight"
		>
	>;
	preview: {
		color: string;
		backgroundColor?: string;
		stroke?: TextStroke;
		shadow?: TextShadow;
		fontWeight?: "normal" | "bold";
	};
}

export const TEXT_STYLE_PRESETS: TextStylePreset[] = [
	{
		id: "clear-all",
		name: "Clear All",
		styles: {
			color: "#ffffff",
			backgroundColor: "transparent",
			stroke: undefined,
			shadow: undefined,
		},
		preview: {
			color: "#ffffff",
		},
	},
	{
		id: "white-black-stroke",
		name: "White + Black Stroke",
		styles: {
			color: "#ffffff",
			stroke: { color: "#000000", width: 3 },
			shadow: undefined,
		},
		preview: {
			color: "#ffffff",
			stroke: { color: "#000000", width: 3 },
		},
	},
	{
		id: "black-white-stroke",
		name: "Black + White Stroke",
		styles: {
			color: "#000000",
			stroke: { color: "#ffffff", width: 3 },
			shadow: undefined,
		},
		preview: {
			color: "#000000",
			stroke: { color: "#ffffff", width: 3 },
		},
	},
	{
		id: "yellow-black-stroke",
		name: "Yellow + Black Stroke",
		styles: {
			color: "#ffff00",
			stroke: { color: "#000000", width: 3 },
			shadow: undefined,
		},
		preview: {
			color: "#ffff00",
			stroke: { color: "#000000", width: 3 },
		},
	},
	{
		id: "white-pink-stroke",
		name: "White + Pink Stroke",
		styles: {
			color: "#ffffff",
			stroke: { color: "#ff69b4", width: 3 },
			shadow: undefined,
		},
		preview: {
			color: "#ffffff",
			stroke: { color: "#ff69b4", width: 3 },
		},
	},
	{
		id: "black-bg-white-text",
		name: "Black BG + White Text",
		styles: {
			color: "#ffffff",
			backgroundColor: "#000000",
			stroke: undefined,
			shadow: undefined,
		},
		preview: {
			color: "#ffffff",
			backgroundColor: "#000000",
		},
	},
	{
		id: "white-bg-black-text",
		name: "White BG + Black Text",
		styles: {
			color: "#000000",
			backgroundColor: "#ffffff",
			stroke: undefined,
			shadow: undefined,
		},
		preview: {
			color: "#000000",
			backgroundColor: "#ffffff",
		},
	},
	{
		id: "white-blue-shadow",
		name: "White + Blue Shadow",
		styles: {
			color: "#ffffff",
			stroke: undefined,
			shadow: { color: "#0066ff", offsetX: 2, offsetY: 2, blur: 6 },
		},
		preview: {
			color: "#ffffff",
			shadow: { color: "#0066ff", offsetX: 2, offsetY: 2, blur: 6 },
		},
	},
];
