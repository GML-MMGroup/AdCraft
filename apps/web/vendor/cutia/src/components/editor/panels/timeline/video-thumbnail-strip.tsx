"use client";

import { useLayoutEffect, useRef, useMemo } from "react";
import { TIMELINE_CONSTANTS } from "@/constants/timeline-constants";
import { timelineThumbnailCache } from "@/services/timeline-thumbnail/service";

const ASYNC_LOAD_DEBOUNCE_MS = 150;
const MAX_CANVAS_DIMENSION = 8192;
const RENDER_PADDING_PX = 200;

interface VideoThumbnailStripProps {
	mediaId: string;
	file: File;
	thumbnailUrl?: string;
	trimStart: number;
	duration: number;
	elementWidth: number;
	trackHeight: number;
	zoomLevel: number;
	fps: number;
	mediaWidth: number;
	mediaHeight: number;
}

function drawCoverCrop({
	ctx,
	image,
	destX,
	destY,
	destWidth,
	destHeight,
}: {
	ctx: CanvasRenderingContext2D;
	image: ImageBitmap;
	destX: number;
	destY: number;
	destWidth: number;
	destHeight: number;
}): void {
	const sourceAspect = image.width / image.height;
	const destAspect = destWidth / destHeight;

	let sx: number;
	let sy: number;
	let sw: number;
	let sh: number;

	if (sourceAspect > destAspect) {
		sh = image.height;
		sw = image.height * destAspect;
		sx = (image.width - sw) / 2;
		sy = 0;
	} else {
		sw = image.width;
		sh = image.width / destAspect;
		sx = 0;
		sy = (image.height - sh) / 2;
	}

	ctx.drawImage(image, sx, sy, sw, sh, destX, destY, destWidth, destHeight);
}

function findScrollContainer(element: HTMLElement): HTMLElement | null {
	let current = element.parentElement;
	while (current) {
		if (current.scrollWidth > current.clientWidth + 1) return current;
		current = current.parentElement;
	}
	return null;
}

function getVisibleRange({
	elementRect,
	containerRect,
	elementWidth,
}: {
	elementRect: DOMRect;
	containerRect: DOMRect;
	elementWidth: number;
}): { start: number; end: number } {
	const relativeLeft = containerRect.left - elementRect.left;
	const start = Math.max(0, relativeLeft - RENDER_PADDING_PX);
	const end = Math.min(
		elementWidth,
		relativeLeft + containerRect.width + RENDER_PADDING_PX,
	);
	return { start, end };
}

export function VideoThumbnailStrip({
	mediaId,
	file,
	thumbnailUrl,
	trimStart,
	duration,
	elementWidth,
	trackHeight,
	zoomLevel,
	fps,
	mediaWidth,
	mediaHeight,
}: VideoThumbnailStripProps) {
	const canvasRef = useRef<HTMLCanvasElement>(null);
	const renderIdRef = useRef(0);
	const drawIdRef = useRef(0);
	const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
	const rafRef = useRef<number>(0);

	const tileAspect = mediaWidth / mediaHeight;
	const tileWidth = Math.round(trackHeight * tileAspect);

	const fallbackStyle = useMemo(
		() =>
			thumbnailUrl
				? {
						backgroundImage: `url(${thumbnailUrl})`,
						backgroundRepeat: "repeat-x" as const,
						backgroundSize: `${tileWidth}px ${trackHeight}px`,
						backgroundPosition: "left top",
					}
				: undefined,
		[thumbnailUrl, tileWidth, trackHeight],
	);

	useLayoutEffect(() => {
		const renderId = ++renderIdRef.current;
		const canvas = canvasRef.current;
		if (!canvas) return;

		const parentEl = canvas.parentElement;
		if (!parentEl) return;

		const scrollContainer = findScrollContainer(canvas);
		const dpr = window.devicePixelRatio || 1;
		const maxLogicalWidth = Math.floor(MAX_CANVAS_DIMENSION / dpr);
		const pixelsPerSecond =
			TIMELINE_CONSTANTS.PIXELS_PER_SECOND * zoomLevel;

		const draw = () => {
			if (renderId !== renderIdRef.current) return;

			const drawId = ++drawIdRef.current;
			const elementRect = parentEl.getBoundingClientRect();
			const containerRect = scrollContainer
				? scrollContainer.getBoundingClientRect()
				: new DOMRect(0, 0, window.innerWidth, window.innerHeight);

			const { start: visStart, end: visEnd } = getVisibleRange({
				elementRect,
				containerRect,
				elementWidth,
			});

			const renderWidth = Math.ceil(visEnd - visStart);
			if (renderWidth <= 0) return;

			const cappedWidth = Math.min(renderWidth, maxLogicalWidth);
			const renderStart = visStart;

			const targetW = cappedWidth * dpr;
			const targetH = trackHeight * dpr;
			if (canvas.width !== targetW || canvas.height !== targetH) {
				canvas.width = targetW;
				canvas.height = targetH;
			}
			canvas.style.width = `${cappedWidth}px`;
			canvas.style.height = `${trackHeight}px`;
			canvas.style.left = `${Math.round(renderStart)}px`;

			const ctx = canvas.getContext("2d");
			if (!ctx) return;

			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			ctx.clearRect(0, 0, cappedWidth, trackHeight);

			const startTile = Math.floor(renderStart / tileWidth);
			const endTile = Math.ceil(visEnd / tileWidth);

			const needsAsyncLoad: { index: number; time: number }[] = [];

			for (let i = startTile; i < endTile; i++) {
				const destX = i * tileWidth - renderStart;
				const timeOffset = (i * tileWidth) / pixelsPerSecond;
				const videoTime = trimStart + timeOffset;
				const frameTime = Math.min(videoTime, trimStart + duration);

				const exact = timelineThumbnailCache.getCachedThumbnail({
					mediaId,
					time: frameTime,
					fps,
				});
				const image =
					exact ??
					timelineThumbnailCache.getNearestCachedThumbnail({
						mediaId,
						time: frameTime,
					});

			if (image) {
				drawCoverCrop({
					ctx,
					image,
					destX,
					destY: 0,
					destWidth: tileWidth,
					destHeight: trackHeight,
				});
			}

				if (!exact) {
					needsAsyncLoad.push({ index: i, time: frameTime });
				}
			}

			if (debounceRef.current) clearTimeout(debounceRef.current);

			if (needsAsyncLoad.length > 0) {
				debounceRef.current = setTimeout(() => {
					if (
						renderId !== renderIdRef.current ||
						drawId !== drawIdRef.current
					)
						return;

					timelineThumbnailCache.loadThumbnailsBatch({
						mediaId,
						file,
						times: needsAsyncLoad,
						fps,
						onThumbnail: ({ index, bitmap }) => {
							if (
								renderId !== renderIdRef.current ||
								drawId !== drawIdRef.current
							)
								return;

							const destX = index * tileWidth - renderStart;
						drawCoverCrop({
							ctx,
							image: bitmap,
							destX,
							destY: 0,
							destWidth: tileWidth,
							destHeight: trackHeight,
						});
						},
					});
				}, ASYNC_LOAD_DEBOUNCE_MS);
			}
		};

		draw();

		const onScroll = () => {
			if (rafRef.current) cancelAnimationFrame(rafRef.current);
			rafRef.current = requestAnimationFrame(draw);
		};

		scrollContainer?.addEventListener("scroll", onScroll, {
			passive: true,
		});

		return () => {
			scrollContainer?.removeEventListener("scroll", onScroll);
			if (rafRef.current) cancelAnimationFrame(rafRef.current);
			if (debounceRef.current) clearTimeout(debounceRef.current);
		};
	}, [
		mediaId,
		file,
		trimStart,
		duration,
		elementWidth,
		trackHeight,
		zoomLevel,
		fps,
		tileWidth,
	]);

	return (
		<>
			<div
				className="pointer-events-none absolute inset-0"
				style={fallbackStyle}
			/>
			<canvas
				ref={canvasRef}
				className="pointer-events-none absolute top-0"
			/>
		</>
	);
}
