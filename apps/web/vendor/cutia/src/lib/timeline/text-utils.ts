import type { TextElement } from "@/types/timeline";

export function isBottomAlignedSubtitleText({
	element,
}: {
	element: TextElement;
}): boolean {
	const normalizedName = element.name.trim().toLowerCase();
	return (
		normalizedName === "subtitle" || normalizedName.startsWith("caption ")
	);
}
