import type {
	TextElement,
	TimelineElement,
	Transform,
} from "@/types/timeline";
import type { MediaAsset } from "@/types/assets";
import type { TCanvasSize } from "@/types/project";
import { FONT_SIZE_SCALE_REFERENCE } from "@/constants/text-constants";
import { isBottomAlignedSubtitleText } from "@/lib/timeline/text-utils";
import { getTextFont, wrapText } from "@/services/renderer/nodes/text-node";

export interface ElementHalfSize {
	halfWidth: number;
	halfHeight: number;
}

let measureContext: CanvasRenderingContext2D | null = null;

// glyph widths vary too much across scripts (CJK ~1em, latin ~0.5em) to guess,
// so measure with the exact font the renderer draws with
function getTextMeasureContext({
	element,
	scaledFontSize,
}: {
	element: TextElement;
	scaledFontSize: number;
}): CanvasRenderingContext2D | null {
	measureContext ??= document.createElement("canvas").getContext("2d");
	if (measureContext) {
		measureContext.font = getTextFont({ element, scaledFontSize });
	}
	return measureContext;
}

/** Unwrapped width of the text in canvas pixels, before transform.scale. */
export function measureTextWidth({
	element,
	scaledFontSize,
}: {
	element: TextElement;
	scaledFontSize: number;
}): number {
	const context = getTextMeasureContext({ element, scaledFontSize });
	return context?.measureText(element.content).width ?? 0;
}

export function getElementHalfSize({
	element,
	transform,
	mediaMap,
	canvasWidth,
	canvasHeight,
	fitCanvasSize = { width: canvasWidth, height: canvasHeight },
}: {
	element: TimelineElement;
	transform: Transform;
	mediaMap: Map<string, MediaAsset>;
	canvasWidth: number;
	canvasHeight: number;
	fitCanvasSize?: TCanvasSize;
}): ElementHalfSize | null {
	if (element.type === "video" || element.type === "image") {
		const media = mediaMap.get(element.mediaId);
		const mediaW = media?.width || canvasWidth;
		const mediaH = media?.height || canvasHeight;
		const containScale = Math.min(
			fitCanvasSize.width / mediaW,
			fitCanvasSize.height / mediaH,
		);
		return {
			halfWidth: (mediaW * containScale * transform.scale) / 2,
			halfHeight: (mediaH * containScale * transform.scale) / 2,
		};
	}

	if (element.type === "text") {
		const scaleFactor = canvasHeight / FONT_SIZE_SCALE_REFERENCE;
		const scaledFontSize = element.fontSize * scaleFactor;
		const elementScale = element.transform.scale;

		const elementBoxWidth = element.boxWidth;
		const hasBoxWidth =
			elementBoxWidth !== undefined && elementBoxWidth > 0;

		if (hasBoxWidth) {
			const context = getTextMeasureContext({ element, scaledFontSize });
			if (!context) return null;

			const scaledBoxWidth = elementBoxWidth * scaleFactor;
			const lineHeight = scaledFontSize * 1.3;
			const lineCount = wrapText({
				context,
				text: element.content,
				maxWidth: scaledBoxWidth,
			}).length;
			return {
				halfWidth: (scaledBoxWidth * elementScale) / 2,
				halfHeight: ((lineCount * lineHeight) * elementScale) / 2,
			};
		}

		return {
			halfWidth:
				(measureTextWidth({ element, scaledFontSize }) * elementScale) / 2,
			halfHeight: ((scaledFontSize * 1.4) * elementScale) / 2,
		};
	}

	if (element.type === "sticker") {
		const stickerSource = 200;
		const containScale = Math.min(
			canvasWidth / stickerSource,
			canvasHeight / stickerSource,
		);
		const half = (stickerSource * containScale * transform.scale) / 2;
		return { halfWidth: half, halfHeight: half };
	}

	return null;
}

/**
 * Returns the element center in absolute canvas coordinates.
 * position is relative to canvas center; this converts to absolute (0,0 = top-left).
 */
export function getElementCenterInCanvas({
	element,
	transform,
	canvasWidth,
	canvasHeight,
	halfSize,
}: {
	element: TimelineElement;
	transform: Transform;
	canvasWidth: number;
	canvasHeight: number;
	halfSize: ElementHalfSize;
}): { x: number; y: number } {
	const isBottomAlignedText =
		element.type === "text" && isBottomAlignedSubtitleText({ element });

	const centerY = isBottomAlignedText
		? canvasHeight / 2 + transform.position.y - halfSize.halfHeight
		: canvasHeight / 2 + transform.position.y;

	return {
		x: canvasWidth / 2 + transform.position.x,
		y: centerY,
	};
}
