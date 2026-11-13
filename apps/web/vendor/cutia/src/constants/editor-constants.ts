import type { TPlatformLayout } from "@/types/editor";

export const IS_DEV = process.env.NODE_ENV === "development";

export const PLATFORM_LAYOUTS: Record<TPlatformLayout, string> = {
	tiktok: "TikTok",
};

export const PANEL_CONFIG = {
	panels: {
		tools: 25,
		preview: 50,
		properties: 25,
		mainContent: 50,
		timeline: 50,
		agent: 20,
	},
};
