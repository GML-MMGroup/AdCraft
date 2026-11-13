import { useCallback, useRef, useState, useSyncExternalStore } from "react";
import { useEditor } from "@/hooks/use-editor";
import type {
	Transform,
	TimelineTrack,
	TimelineElement,
	TextElement,
} from "@/types/timeline";
import { hitTestElements } from "@/lib/preview/hit-test";
import { FONT_SIZE_SCALE_REFERENCE } from "@/constants/text-constants";
import {
	getElementHalfSize,
	getElementCenterInCanvas,
	measureTextWidth,
	type ElementHalfSize,
} from "@/lib/preview/element-bounds";
import { computePreviewSnap, type SnapGuide } from "@/lib/preview/snap";

type ScaleHandle = "top-left" | "top-right" | "bottom-left" | "bottom-right";
type ResizeHandle = "left" | "right";

interface SnapContext {
	elementHalfSize: ElementHalfSize;
	otherElementBounds: Array<{
		centerX: number;
		centerY: number;
		halfWidth: number;
		halfHeight: number;
	}>;
	canvasWidth: number;
	canvasHeight: number;
}

interface DragState {
	startX: number;
	startY: number;
	tracksSnapshot: TimelineTrack[];
	elements: Array<{
		trackId: string;
		elementId: string;
		initialTransform: Transform;
	}>;
	snapContext: SnapContext | null;
}

interface ScaleState {
	startX: number;
	startY: number;
	handle: ScaleHandle;
	tracksSnapshot: TimelineTrack[];
	trackId: string;
	elementId: string;
	initialTransform: Transform;
	anchorX: number;
	anchorY: number;
}

interface ResizeState {
	startX: number;
	startY: number;
	handle: ResizeHandle;
	tracksSnapshot: TimelineTrack[];
	trackId: string;
	elementId: string;
	initialBoxWidth: number;
	initialTransform: Transform;
	scaleFactor: number;
}

export function usePreviewInteraction({
	canvasRef,
	overlayRef,
}: {
	canvasRef: React.RefObject<HTMLCanvasElement | null>;
	overlayRef: React.RefObject<HTMLDivElement | null>;
}) {
	const editor = useEditor();
	const [isDragging, setIsDragging] = useState(false);
	const [isScaling, setIsScaling] = useState(false);
	const [activeGuides, setActiveGuides] = useState<SnapGuide[]>([]);
	const dragStateRef = useRef<DragState | null>(null);
	const scaleStateRef = useRef<ScaleState | null>(null);
	const resizeStateRef = useRef<ResizeState | null>(null);
	const scalePointerIdRef = useRef<number | null>(null);
	const resizePointerIdRef = useRef<number | null>(null);

	const selectedElements = useSyncExternalStore(
		(listener) => editor.selection.subscribe(listener),
		() => editor.selection.getSelectedElements(),
	);

	const getCanvasCoordinates = useCallback(
		({ clientX, clientY }: { clientX: number; clientY: number }) => {
			if (!canvasRef.current) return { x: 0, y: 0 };

			const rect = canvasRef.current.getBoundingClientRect();
			const logicalWidth = canvasRef.current.width;
			const logicalHeight = canvasRef.current.height;
			const scaleX = logicalWidth / rect.width;
			const scaleY = logicalHeight / rect.height;

			const canvasX = (clientX - rect.left) * scaleX;
			const canvasY = (clientY - rect.top) * scaleY;

			return { x: canvasX, y: canvasY };
		},
		[canvasRef],
	);

	const handlePointerDown = useCallback(
		(event: React.PointerEvent) => {
			const startPos = getCanvasCoordinates({
				clientX: event.clientX,
				clientY: event.clientY,
			});

			const canvasWidth = canvasRef.current?.width ?? 0;
			const canvasHeight = canvasRef.current?.height ?? 0;
			const fitCanvasSize = editor.project.getActive().settings
				.originalCanvasSize ?? { width: canvasWidth, height: canvasHeight };
			const tracks = editor.timeline.getTracks();
			const mediaAssets = editor.media.getAssets();
			const currentTime = editor.playback.getCurrentTime();

			const hitResult = hitTestElements({
				point: startPos,
				tracks,
				mediaAssets,
				canvasWidth,
				canvasHeight,
				fitCanvasSize,
				currentTime,
			});

			if (!hitResult) {
				editor.selection.clearSelection();
				return;
			}

			const isAlreadySelected = selectedElements.some(
				(selected) =>
					selected.trackId === hitResult.trackId &&
					selected.elementId === hitResult.element.id,
			);

			let draggedElementIds: Set<string>;

			if (!isAlreadySelected) {
				editor.selection.setSelectedElements({
					elements: [
						{
							trackId: hitResult.trackId,
							elementId: hitResult.element.id,
						},
					],
				});

				draggedElementIds = new Set([hitResult.element.id]);

				dragStateRef.current = {
					startX: startPos.x,
					startY: startPos.y,
					tracksSnapshot: tracks,
					elements: [
						{
							trackId: hitResult.trackId,
							elementId: hitResult.element.id,
							initialTransform: hitResult.transform,
						},
					],
					snapContext: null,
				};
			} else {
				const elementsWithTracks = editor.timeline.getElementsWithTracks({
					elements: selectedElements,
				});

				const draggableElements = elementsWithTracks.filter(
					({ element }) =>
						element.type === "video" ||
						element.type === "image" ||
						element.type === "text" ||
						element.type === "sticker",
				);

				if (draggableElements.length === 0) return;

				draggedElementIds = new Set(
					draggableElements.map(({ element }) => element.id),
				);

				dragStateRef.current = {
					startX: startPos.x,
					startY: startPos.y,
					tracksSnapshot: tracks,
					elements: draggableElements.map(({ track, element }) => ({
						trackId: track.id,
						elementId: element.id,
						initialTransform: (element as { transform: Transform })
							.transform,
					})),
					snapContext: null,
				};
			}

			dragStateRef.current.snapContext = buildSnapContext({
				tracks,
				mediaAssets,
				currentTime,
				canvasWidth,
				canvasHeight,
				fitCanvasSize,
				draggedElementIds,
				primaryElement: dragStateRef.current.elements[0],
			});

			setIsDragging(true);
			event.currentTarget.setPointerCapture(event.pointerId);
		},
		[selectedElements, editor, getCanvasCoordinates, canvasRef],
	);

	const handleScaleStart = useCallback(
		({
			event,
			handle,
			element,
			trackId,
		}: {
			event: React.PointerEvent;
			handle: ScaleHandle;
			element: TimelineElement;
			trackId: string;
		}) => {
			if (element.type === "audio") return;

			const startPos = getCanvasCoordinates({
				clientX: event.clientX,
				clientY: event.clientY,
			});
			const transform = (element as { transform: Transform }).transform;

			const canvasWidth = canvasRef.current?.width ?? 0;
			const canvasHeight = canvasRef.current?.height ?? 0;
			const anchorX = canvasWidth / 2 + transform.position.x;
			const anchorY = canvasHeight / 2 + transform.position.y;

			scaleStateRef.current = {
				startX: startPos.x,
				startY: startPos.y,
				handle,
				tracksSnapshot: editor.timeline.getTracks(),
				trackId,
				elementId: element.id,
				initialTransform: transform,
				anchorX,
				anchorY,
			};

			scalePointerIdRef.current = event.pointerId;
			overlayRef.current?.setPointerCapture(event.pointerId);

			setIsScaling(true);
		},
		[editor, getCanvasCoordinates, canvasRef, overlayRef],
	);

	const handleResizeStart = useCallback(
		({
			event,
			handle,
			element,
			trackId,
		}: {
			event: React.PointerEvent;
			handle: ResizeHandle;
			element: TimelineElement;
			trackId: string;
		}) => {
			if (element.type !== "text") return;

			const textElement = element as TextElement;
			const startPos = getCanvasCoordinates({
				clientX: event.clientX,
				clientY: event.clientY,
			});

			const canvasHeight = canvasRef.current?.height ?? 0;
			const scaleFactor = canvasHeight / FONT_SIZE_SCALE_REFERENCE;

			const initialBoxWidth =
				textElement.boxWidth && textElement.boxWidth > 0
					? textElement.boxWidth
					: measureTextWidth({
							element: textElement,
							scaledFontSize: textElement.fontSize * scaleFactor,
						}) / scaleFactor;

			resizeStateRef.current = {
				startX: startPos.x,
				startY: startPos.y,
				handle,
				tracksSnapshot: editor.timeline.getTracks(),
				trackId,
				elementId: element.id,
				initialBoxWidth,
				initialTransform: textElement.transform,
				scaleFactor,
			};

			resizePointerIdRef.current = event.pointerId;
			overlayRef.current?.setPointerCapture(event.pointerId);
		},
		[editor, getCanvasCoordinates, canvasRef, overlayRef],
	);

	const handlePointerMove = useCallback(
		(event: React.PointerEvent) => {
			const currentPos = getCanvasCoordinates({
				clientX: event.clientX,
				clientY: event.clientY,
			});

			if (resizeStateRef.current) {
				const state = resizeStateRef.current;
				const { scaleFactor } = state;

				const rawDeltaX = currentPos.x - state.startX;
				const initialWidthPx = state.initialBoxWidth * scaleFactor;

				const directedDelta =
					state.handle === "right" ? rawDeltaX : -rawDeltaX;
				const newWidthPx = Math.max(20, initialWidthPx + directedDelta);
				const newBoxWidth = newWidthPx / scaleFactor;

				const widthChangePx =
					(newBoxWidth - state.initialBoxWidth) * scaleFactor;
				const positionOffsetX =
					state.handle === "right"
						? widthChangePx / 2
						: -widthChangePx / 2;

				editor.timeline.updateElements({
					updates: [
						{
							trackId: state.trackId,
							elementId: state.elementId,
							updates: {
								boxWidth: newBoxWidth,
								transform: {
									...state.initialTransform,
									position: {
										x:
											state.initialTransform.position.x +
											positionOffsetX,
										y: state.initialTransform.position.y,
									},
								},
							},
						},
					],
					pushHistory: false,
				});
				return;
			}

			// scaling takes priority
			if (scaleStateRef.current && isScaling) {
				const state = scaleStateRef.current;
				const initialDist = Math.hypot(
					state.startX - state.anchorX,
					state.startY - state.anchorY,
				);
				const currentDist = Math.hypot(
					currentPos.x - state.anchorX,
					currentPos.y - state.anchorY,
				);

				if (initialDist < 1) return;

				const ratio = currentDist / initialDist;
				const newScale = Math.max(
					0.1,
					Math.min(5, state.initialTransform.scale * ratio),
				);

				editor.timeline.updateElements({
					updates: [
						{
							trackId: state.trackId,
							elementId: state.elementId,
							updates: {
								transform: {
									...state.initialTransform,
									scale: newScale,
								},
							},
						},
					],
					pushHistory: false,
				});
				return;
			}

			if (!dragStateRef.current || !isDragging) return;

			const deltaX = currentPos.x - dragStateRef.current.startX;
			const deltaY = currentPos.y - dragStateRef.current.startY;

			const primaryElement = dragStateRef.current.elements[0];
			const primaryRawPosition = {
				x: primaryElement.initialTransform.position.x + deltaX,
				y: primaryElement.initialTransform.position.y + deltaY,
			};

			let snapDeltaX = 0;
			let snapDeltaY = 0;
			let newGuides: SnapGuide[] = [];

			const { snapContext } = dragStateRef.current;
			if (snapContext) {
				const snapResult = computePreviewSnap({
					position: primaryRawPosition,
					elementHalfSize: snapContext.elementHalfSize,
					canvasWidth: snapContext.canvasWidth,
					canvasHeight: snapContext.canvasHeight,
					otherElements: snapContext.otherElementBounds,
				});
				snapDeltaX = snapResult.snappedPosition.x - primaryRawPosition.x;
				snapDeltaY = snapResult.snappedPosition.y - primaryRawPosition.y;
				newGuides = snapResult.activeGuides;
			}

			setActiveGuides(newGuides);

			const updates = dragStateRef.current.elements.map(
				({ trackId, elementId, initialTransform }) => ({
					trackId,
					elementId,
					updates: {
						transform: {
							...initialTransform,
							position: {
								x: initialTransform.position.x + deltaX + snapDeltaX,
								y: initialTransform.position.y + deltaY + snapDeltaY,
							},
						},
					},
				}),
			);

			editor.timeline.updateElements({ updates, pushHistory: false });
		},
		[isDragging, isScaling, getCanvasCoordinates, editor],
	);

	const handlePointerUp = useCallback(
		(event: React.PointerEvent) => {
			if (resizeStateRef.current) {
				const state = resizeStateRef.current;
				const currentPos = getCanvasCoordinates({
					clientX: event.clientX,
					clientY: event.clientY,
				});

				const rawDeltaX = currentPos.x - state.startX;
				const hasResized = Math.abs(rawDeltaX) > 1;

				if (hasResized) {
					const { scaleFactor } = state;
					const initialWidthPx = state.initialBoxWidth * scaleFactor;
					const directedDelta =
						state.handle === "right" ? rawDeltaX : -rawDeltaX;
					const newWidthPx = Math.max(
						20,
						initialWidthPx + directedDelta,
					);
					const newBoxWidth = newWidthPx / scaleFactor;

					const widthChangePx =
						(newBoxWidth - state.initialBoxWidth) * scaleFactor;
					const positionOffsetX =
						state.handle === "right"
							? widthChangePx / 2
							: -widthChangePx / 2;

					editor.timeline.updateTracks(state.tracksSnapshot);
					editor.timeline.updateElements({
						updates: [
							{
								trackId: state.trackId,
								elementId: state.elementId,
								updates: {
									boxWidth: newBoxWidth,
									transform: {
										...state.initialTransform,
										position: {
											x:
												state.initialTransform.position
													.x + positionOffsetX,
											y: state.initialTransform.position
												.y,
										},
									},
								},
							},
						],
					});
				} else {
					editor.timeline.updateTracks(state.tracksSnapshot);
				}

				if (resizePointerIdRef.current !== null) {
					overlayRef.current?.releasePointerCapture(
						resizePointerIdRef.current,
					);
					resizePointerIdRef.current = null;
				}

				resizeStateRef.current = null;
				return;
			}

			// handle scale commit
			if (scaleStateRef.current && isScaling) {
				const state = scaleStateRef.current;
				const currentPos = getCanvasCoordinates({
					clientX: event.clientX,
					clientY: event.clientY,
				});

				const initialDist = Math.hypot(
					state.startX - state.anchorX,
					state.startY - state.anchorY,
				);
				const currentDist = Math.hypot(
					currentPos.x - state.anchorX,
					currentPos.y - state.anchorY,
				);
				const hasScaled = Math.abs(currentDist - initialDist) > 1;

				if (hasScaled) {
					const ratio = currentDist / Math.max(1, initialDist);
					const newScale = Math.max(
						0.1,
						Math.min(5, state.initialTransform.scale * ratio),
					);

					editor.timeline.updateTracks(state.tracksSnapshot);
					editor.timeline.updateElements({
						updates: [
							{
								trackId: state.trackId,
								elementId: state.elementId,
								updates: {
									transform: {
										...state.initialTransform,
										scale: newScale,
									},
								},
							},
						],
					});
				} else {
					editor.timeline.updateTracks(state.tracksSnapshot);
				}

				if (scalePointerIdRef.current !== null) {
					overlayRef.current?.releasePointerCapture(
						scalePointerIdRef.current,
					);
					scalePointerIdRef.current = null;
				}

				scaleStateRef.current = null;
				setIsScaling(false);
				return;
			}

			// handle drag commit
			if (!dragStateRef.current || !isDragging) return;

			const currentPos = getCanvasCoordinates({
				clientX: event.clientX,
				clientY: event.clientY,
			});

			const deltaX = currentPos.x - dragStateRef.current.startX;
			const deltaY = currentPos.y - dragStateRef.current.startY;

			const hasMovement =
				Math.abs(deltaX) > 0.5 || Math.abs(deltaY) > 0.5;

			if (!hasMovement) {
				dragStateRef.current = null;
				setIsDragging(false);
				setActiveGuides([]);
				event.currentTarget.releasePointerCapture(event.pointerId);
				return;
			}

			const primaryElement = dragStateRef.current.elements[0];
			const primaryRawPosition = {
				x: primaryElement.initialTransform.position.x + deltaX,
				y: primaryElement.initialTransform.position.y + deltaY,
			};

			let snapDeltaX = 0;
			let snapDeltaY = 0;

			const { snapContext } = dragStateRef.current;
			if (snapContext) {
				const snapResult = computePreviewSnap({
					position: primaryRawPosition,
					elementHalfSize: snapContext.elementHalfSize,
					canvasWidth: snapContext.canvasWidth,
					canvasHeight: snapContext.canvasHeight,
					otherElements: snapContext.otherElementBounds,
				});
				snapDeltaX = snapResult.snappedPosition.x - primaryRawPosition.x;
				snapDeltaY = snapResult.snappedPosition.y - primaryRawPosition.y;
			}

			editor.timeline.updateTracks(dragStateRef.current.tracksSnapshot);

			const updates = dragStateRef.current.elements.map(
				({ trackId, elementId, initialTransform }) => ({
					trackId,
					elementId,
					updates: {
						transform: {
							...initialTransform,
							position: {
								x: initialTransform.position.x + deltaX + snapDeltaX,
								y: initialTransform.position.y + deltaY + snapDeltaY,
							},
						},
					},
				}),
			);

			editor.timeline.updateElements({ updates });

			dragStateRef.current = null;
			setIsDragging(false);
			setActiveGuides([]);
			event.currentTarget.releasePointerCapture(event.pointerId);
		},
		[isDragging, isScaling, getCanvasCoordinates, editor, overlayRef],
	);

	const isResizing = resizeStateRef.current !== null;

	return {
		onPointerDown: handlePointerDown,
		onPointerMove: handlePointerMove,
		onPointerUp: handlePointerUp,
		onScaleStart: handleScaleStart,
		onResizeStart: handleResizeStart,
		isTransforming: isDragging || isScaling || isResizing,
		activeGuides,
	};
}

function buildSnapContext({
	tracks,
	mediaAssets,
	currentTime,
	canvasWidth,
	canvasHeight,
	fitCanvasSize,
	draggedElementIds,
	primaryElement,
}: {
	tracks: TimelineTrack[];
	mediaAssets: ReturnType<ReturnType<typeof useEditor>["media"]["getAssets"]>;
	currentTime: number;
	canvasWidth: number;
	canvasHeight: number;
	fitCanvasSize: { width: number; height: number };
	draggedElementIds: Set<string>;
	primaryElement: { elementId: string; initialTransform: Transform };
}): SnapContext | null {
	const mediaMap = new Map(mediaAssets.map((a) => [a.id, a]));

	let primaryEl: TimelineElement | undefined;
	for (const track of tracks) {
		const found = track.elements.find((e) => e.id === primaryElement.elementId);
		if (found) {
			primaryEl = found;
			break;
		}
	}

	if (!primaryEl || primaryEl.type === "audio") return null;

	const elementHalfSize = getElementHalfSize({
		element: primaryEl,
		transform: primaryElement.initialTransform,
		mediaMap,
		canvasWidth,
		canvasHeight,
		fitCanvasSize,
	});

	if (!elementHalfSize) return null;

	const otherElementBounds: SnapContext["otherElementBounds"] = [];

	for (const track of tracks) {
		if ("hidden" in track && track.hidden) continue;
		for (const element of track.elements) {
			if (element.type === "audio") continue;
			if ("hidden" in element && element.hidden) continue;
			if (draggedElementIds.has(element.id)) continue;

			const isVisible =
				currentTime >= element.startTime &&
				currentTime < element.startTime + element.duration;
			if (!isVisible) continue;

			const transform = (element as { transform: Transform }).transform;
			const otherHalf = getElementHalfSize({
				element,
				transform,
				mediaMap,
				canvasWidth,
				canvasHeight,
				fitCanvasSize,
			});
			if (!otherHalf) continue;

			const center = getElementCenterInCanvas({
				element,
				transform,
				canvasWidth,
				canvasHeight,
				halfSize: otherHalf,
			});

			otherElementBounds.push({
				centerX: center.x,
				centerY: center.y,
				halfWidth: otherHalf.halfWidth,
				halfHeight: otherHalf.halfHeight,
			});
		}
	}

	return { elementHalfSize, otherElementBounds, canvasWidth, canvasHeight };
}
