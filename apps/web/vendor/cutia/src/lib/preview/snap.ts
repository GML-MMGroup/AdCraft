import type { ElementHalfSize } from "./element-bounds";

export interface SnapGuide {
	orientation: "horizontal" | "vertical";
	position: number;
	type: "center" | "edge" | "element";
}

interface SnapCandidate {
	snappedValue: number;
	distance: number;
	guide: SnapGuide;
}

interface OtherElementBounds {
	centerX: number;
	centerY: number;
	halfWidth: number;
	halfHeight: number;
}

const SNAP_THRESHOLD = 8;

/**
 * Computes snap-aligned position and active guide lines for a dragged element.
 * X and Y axes snap independently to the closest target within threshold.
 */
export function computePreviewSnap({
	position,
	elementHalfSize,
	canvasWidth,
	canvasHeight,
	otherElements,
	threshold = SNAP_THRESHOLD,
}: {
	position: { x: number; y: number };
	elementHalfSize: ElementHalfSize;
	canvasWidth: number;
	canvasHeight: number;
	otherElements: OtherElementBounds[];
	threshold?: number;
}): {
	snappedPosition: { x: number; y: number };
	activeGuides: SnapGuide[];
} {
	const halfW = canvasWidth / 2;
	const halfH = canvasHeight / 2;

	const elementCenterX = halfW + position.x;
	const elementCenterY = halfH + position.y;
	const elementLeft = elementCenterX - elementHalfSize.halfWidth;
	const elementRight = elementCenterX + elementHalfSize.halfWidth;
	const elementTop = elementCenterY - elementHalfSize.halfHeight;
	const elementBottom = elementCenterY + elementHalfSize.halfHeight;

	const xCandidates: SnapCandidate[] = [];
	const yCandidates: SnapCandidate[] = [];

	collectCanvasSnapCandidates({
		elementCenterX,
		elementCenterY,
		elementLeft,
		elementRight,
		elementTop,
		elementBottom,
		canvasWidth,
		canvasHeight,
		halfW,
		halfH,
		xCandidates,
		yCandidates,
	});

	collectElementSnapCandidates({
		elementCenterX,
		elementCenterY,
		elementLeft,
		elementRight,
		elementTop,
		elementBottom,
		otherElements,
		xCandidates,
		yCandidates,
	});

	const bestX = pickClosestCandidate({ candidates: xCandidates, threshold });
	const bestY = pickClosestCandidate({ candidates: yCandidates, threshold });

	const snappedPosition = { ...position };
	const activeGuides: SnapGuide[] = [];

	if (bestX) {
		snappedPosition.x = position.x + (bestX.snappedValue - elementCenterX);
		activeGuides.push(bestX.guide);
	}
	if (bestY) {
		snappedPosition.y = position.y + (bestY.snappedValue - elementCenterY);
		activeGuides.push(bestY.guide);
	}

	return { snappedPosition, activeGuides };
}

function collectCanvasSnapCandidates({
	elementCenterX,
	elementCenterY,
	elementLeft,
	elementRight,
	elementTop,
	elementBottom,
	canvasWidth,
	canvasHeight,
	halfW,
	halfH,
	xCandidates,
	yCandidates,
}: {
	elementCenterX: number;
	elementCenterY: number;
	elementLeft: number;
	elementRight: number;
	elementTop: number;
	elementBottom: number;
	canvasWidth: number;
	canvasHeight: number;
	halfW: number;
	halfH: number;
	xCandidates: SnapCandidate[];
	yCandidates: SnapCandidate[];
}) {
	// --- X axis (vertical guide lines) ---

	// canvas horizontal center
	pushCandidate({
		candidates: xCandidates,
		currentValue: elementCenterX,
		targetValue: halfW,
		guide: { orientation: "vertical", position: halfW, type: "center" },
	});

	// canvas left edge (element left ≈ 0)
	pushCandidateFromEdge({
		candidates: xCandidates,
		elementCenter: elementCenterX,
		elementEdge: elementLeft,
		targetEdge: 0,
		guide: { orientation: "vertical", position: 0, type: "edge" },
	});

	// canvas right edge (element right ≈ canvasWidth)
	pushCandidateFromEdge({
		candidates: xCandidates,
		elementCenter: elementCenterX,
		elementEdge: elementRight,
		targetEdge: canvasWidth,
		guide: {
			orientation: "vertical",
			position: canvasWidth,
			type: "edge",
		},
	});

	// --- Y axis (horizontal guide lines) ---

	// canvas vertical center
	pushCandidate({
		candidates: yCandidates,
		currentValue: elementCenterY,
		targetValue: halfH,
		guide: { orientation: "horizontal", position: halfH, type: "center" },
	});

	// canvas top edge
	pushCandidateFromEdge({
		candidates: yCandidates,
		elementCenter: elementCenterY,
		elementEdge: elementTop,
		targetEdge: 0,
		guide: { orientation: "horizontal", position: 0, type: "edge" },
	});

	// canvas bottom edge
	pushCandidateFromEdge({
		candidates: yCandidates,
		elementCenter: elementCenterY,
		elementEdge: elementBottom,
		targetEdge: canvasHeight,
		guide: {
			orientation: "horizontal",
			position: canvasHeight,
			type: "edge",
		},
	});
}

function collectElementSnapCandidates({
	elementCenterX,
	elementCenterY,
	elementLeft,
	elementRight,
	elementTop,
	elementBottom,
	otherElements,
	xCandidates,
	yCandidates,
}: {
	elementCenterX: number;
	elementCenterY: number;
	elementLeft: number;
	elementRight: number;
	elementTop: number;
	elementBottom: number;
	otherElements: OtherElementBounds[];
	xCandidates: SnapCandidate[];
	yCandidates: SnapCandidate[];
}) {
	for (const other of otherElements) {
		const otherLeft = other.centerX - other.halfWidth;
		const otherRight = other.centerX + other.halfWidth;
		const otherTop = other.centerY - other.halfHeight;
		const otherBottom = other.centerY + other.halfHeight;

		// X: center-to-center
		pushCandidate({
			candidates: xCandidates,
			currentValue: elementCenterX,
			targetValue: other.centerX,
			guide: {
				orientation: "vertical",
				position: other.centerX,
				type: "element",
			},
		});

		// X: left-to-left
		pushCandidateFromEdge({
			candidates: xCandidates,
			elementCenter: elementCenterX,
			elementEdge: elementLeft,
			targetEdge: otherLeft,
			guide: {
				orientation: "vertical",
				position: otherLeft,
				type: "element",
			},
		});

		// X: right-to-right
		pushCandidateFromEdge({
			candidates: xCandidates,
			elementCenter: elementCenterX,
			elementEdge: elementRight,
			targetEdge: otherRight,
			guide: {
				orientation: "vertical",
				position: otherRight,
				type: "element",
			},
		});

		// X: left-to-right
		pushCandidateFromEdge({
			candidates: xCandidates,
			elementCenter: elementCenterX,
			elementEdge: elementLeft,
			targetEdge: otherRight,
			guide: {
				orientation: "vertical",
				position: otherRight,
				type: "element",
			},
		});

		// X: right-to-left
		pushCandidateFromEdge({
			candidates: xCandidates,
			elementCenter: elementCenterX,
			elementEdge: elementRight,
			targetEdge: otherLeft,
			guide: {
				orientation: "vertical",
				position: otherLeft,
				type: "element",
			},
		});

		// Y: center-to-center
		pushCandidate({
			candidates: yCandidates,
			currentValue: elementCenterY,
			targetValue: other.centerY,
			guide: {
				orientation: "horizontal",
				position: other.centerY,
				type: "element",
			},
		});

		// Y: top-to-top
		pushCandidateFromEdge({
			candidates: yCandidates,
			elementCenter: elementCenterY,
			elementEdge: elementTop,
			targetEdge: otherTop,
			guide: {
				orientation: "horizontal",
				position: otherTop,
				type: "element",
			},
		});

		// Y: bottom-to-bottom
		pushCandidateFromEdge({
			candidates: yCandidates,
			elementCenter: elementCenterY,
			elementEdge: elementBottom,
			targetEdge: otherBottom,
			guide: {
				orientation: "horizontal",
				position: otherBottom,
				type: "element",
			},
		});

		// Y: top-to-bottom
		pushCandidateFromEdge({
			candidates: yCandidates,
			elementCenter: elementCenterY,
			elementEdge: elementTop,
			targetEdge: otherBottom,
			guide: {
				orientation: "horizontal",
				position: otherBottom,
				type: "element",
			},
		});

		// Y: bottom-to-top
		pushCandidateFromEdge({
			candidates: yCandidates,
			elementCenter: elementCenterY,
			elementEdge: elementBottom,
			targetEdge: otherTop,
			guide: {
				orientation: "horizontal",
				position: otherTop,
				type: "element",
			},
		});
	}
}

function pushCandidate({
	candidates,
	currentValue,
	targetValue,
	guide,
}: {
	candidates: SnapCandidate[];
	currentValue: number;
	targetValue: number;
	guide: SnapGuide;
}) {
	candidates.push({
		snappedValue: targetValue,
		distance: Math.abs(currentValue - targetValue),
		guide,
	});
}

function pushCandidateFromEdge({
	candidates,
	elementCenter,
	elementEdge,
	targetEdge,
	guide,
}: {
	candidates: SnapCandidate[];
	elementCenter: number;
	elementEdge: number;
	targetEdge: number;
	guide: SnapGuide;
}) {
	const offset = targetEdge - elementEdge;
	candidates.push({
		snappedValue: elementCenter + offset,
		distance: Math.abs(offset),
		guide,
	});
}

function pickClosestCandidate({
	candidates,
	threshold,
}: {
	candidates: SnapCandidate[];
	threshold: number;
}): SnapCandidate | null {
	let best: SnapCandidate | null = null;
	for (const candidate of candidates) {
		if (candidate.distance > threshold) continue;
		if (!best || candidate.distance < best.distance) {
			best = candidate;
		}
	}
	return best;
}
