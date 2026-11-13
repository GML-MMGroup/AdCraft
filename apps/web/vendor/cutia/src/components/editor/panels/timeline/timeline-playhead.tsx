"use client";

import { useRef, useEffect } from "react";
import { TIMELINE_CONSTANTS } from "@/constants/timeline-constants";
import { useTimelinePlayhead } from "@/hooks/timeline/use-timeline-playhead";
import { useEditor } from "@/hooks/use-editor";

interface TimelinePlayheadProps {
	zoomLevel: number;
	rulerRef: React.RefObject<HTMLDivElement | null>;
	rulerScrollRef: React.RefObject<HTMLDivElement | null>;
	tracksScrollRef: React.RefObject<HTMLDivElement | null>;
	containerRef: React.RefObject<HTMLDivElement | null>;
	playheadRef?: React.RefObject<HTMLDivElement | null>;
	isSnappingToPlayhead?: boolean;
}

export function TimelinePlayhead({
	zoomLevel,
	rulerRef,
	rulerScrollRef,
	tracksScrollRef,
	containerRef,
	playheadRef: externalPlayheadRef,
	isSnappingToPlayhead = false,
}: TimelinePlayheadProps) {
	const editor = useEditor();
	const duration = editor.timeline.getTotalDuration();
	const internalPlayheadRef = useRef<HTMLDivElement>(null);
	const playheadRef = externalPlayheadRef || internalPlayheadRef;

	const { playheadPosition, handlePlayheadMouseDown } = useTimelinePlayhead({
		zoomLevel,
		rulerRef,
		rulerScrollRef,
		tracksScrollRef,
		playheadRef,
	});

	useEffect(() => {
		const scrollContainer = tracksScrollRef.current;
		const playheadElement = playheadRef.current;
		if (!scrollContainer || !playheadElement) return;

		const syncScrollOffset = () => {
			playheadElement.style.transform = `translateX(${-scrollContainer.scrollLeft}px)`;
		};

		syncScrollOffset();
		scrollContainer.addEventListener("scroll", syncScrollOffset, {
			passive: true,
		});
		return () =>
			scrollContainer.removeEventListener("scroll", syncScrollOffset);
	}, [tracksScrollRef, playheadRef]);

	const totalHeight = containerRef.current?.clientHeight ?? 400;

	const timelinePosition =
		playheadPosition * TIMELINE_CONSTANTS.PIXELS_PER_SECOND * zoomLevel;

	const handlePlayheadKeyDown = (
		event: React.KeyboardEvent<HTMLDivElement>,
	) => {
		if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;

		event.preventDefault();
		const step = 1 / Math.max(1, editor.project.getActive().settings.fps);
		const direction = event.key === "ArrowRight" ? 1 : -1;
		const nextTime = Math.max(
			0,
			Math.min(duration, playheadPosition + direction * step),
		);

		editor.playback.seek({ time: nextTime });
	};

	return (
		<div
			ref={playheadRef}
			role="slider"
			aria-label="Timeline playhead"
			aria-valuemin={0}
			aria-valuemax={duration}
			aria-valuenow={playheadPosition}
			tabIndex={0}
			className="pointer-events-auto absolute z-60 will-change-transform"
			style={{
				left: `${timelinePosition}px`,
				top: 0,
				height: `${totalHeight}px`,
				width: "2px",
			}}
			onMouseDown={handlePlayheadMouseDown}
			onKeyDown={handlePlayheadKeyDown}
		>
			<div className="bg-foreground absolute left-0 h-full w-0.5 cursor-col-resize" />

			<div
				className={`absolute top-1 left-1/2 size-3 -translate-x-1/2 transform rounded-full border-2 shadow-xs ${isSnappingToPlayhead ? "bg-foreground border-foreground" : "bg-foreground border-foreground/50"}`}
			/>
		</div>
	);
}
