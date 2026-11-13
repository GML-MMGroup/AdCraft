import { create } from "zustand";

interface MediaPreviewState {
	selectedMediaId: string | null;
	selectMedia: ({ mediaId }: { mediaId: string }) => void;
	clearSelection: () => void;
}

export const useMediaPreviewStore = create<MediaPreviewState>((set) => ({
	selectedMediaId: null,
	selectMedia: ({ mediaId }) => set({ selectedMediaId: mediaId }),
	clearSelection: () => set({ selectedMediaId: null }),
}));

export function handleMediaPreviewKeyDown(
	event: Pick<KeyboardEvent, "key" | "defaultPrevented" | "target">,
) {
	const target = event.target as {
		closest?: (selector: string) => unknown;
	} | null;
	if (
		event.key !== "Escape" ||
		event.defaultPrevented ||
		target?.closest?.("input, textarea, [contenteditable='true']")
	) {
		return;
	}

	useMediaPreviewStore.getState().clearSelection();
}
