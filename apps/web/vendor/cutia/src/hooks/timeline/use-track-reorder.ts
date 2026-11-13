import { useCallback, useRef, useState } from "react";
import { useEditor } from "@/hooks/use-editor";
import type { TimelineTrack } from "@/types/timeline";
import { getTrackHeight } from "@/lib/timeline/track-utils";

export interface TrackReorderState {
	isDragging: boolean;
	dragTrackId: string | null;
	dragOverIndex: number | null;
}

const INITIAL_STATE: TrackReorderState = {
	isDragging: false,
	dragTrackId: null,
	dragOverIndex: null,
};

export function useTrackReorder() {
	const editor = useEditor();
	const [reorderState, setReorderState] =
		useState<TrackReorderState>(INITIAL_STATE);
	const startYRef = useRef(0);
	const containerRef = useRef<HTMLElement | null>(null);

	const getTargetIndex = useCallback(
		({
			mouseY,
			tracks,
		}: {
			mouseY: number;
			tracks: TimelineTrack[];
		}): number => {
			const container = containerRef.current;
			if (!container) return -1;

			const containerRect = container.getBoundingClientRect();
			const relativeY = mouseY - containerRect.top + container.scrollTop;

			let accumulatedHeight = 0;
			for (let i = 0; i < tracks.length; i++) {
				const trackHeight = getTrackHeight({ type: tracks[i].type }) + 4;
				const trackMid = accumulatedHeight + trackHeight / 2;
				if (relativeY < trackMid) {
					return i;
				}
				accumulatedHeight += trackHeight;
			}

			return tracks.length - 1;
		},
		[],
	);

	const handleTrackDragStart = useCallback(
		({
			trackId,
			mouseY,
			container,
		}: {
			trackId: string;
			mouseY: number;
			container: HTMLElement;
		}) => {
			startYRef.current = mouseY;
			containerRef.current = container;
			setReorderState({
				isDragging: true,
				dragTrackId: trackId,
				dragOverIndex: null,
			});

			const handleMouseMove = (event: MouseEvent) => {
				const tracks = editor.timeline.getTracks();
				const targetIndex = getTargetIndex({
					mouseY: event.clientY,
					tracks,
				});
				setReorderState((prev) => ({
					...prev,
					dragOverIndex: targetIndex,
				}));
			};

			const handleMouseUp = () => {
				document.removeEventListener("mousemove", handleMouseMove);
				document.removeEventListener("mouseup", handleMouseUp);

				setReorderState((current) => {
					const { dragTrackId: currentDragId, dragOverIndex } = current;
					if (
						currentDragId === null ||
						dragOverIndex === null
					) {
						return INITIAL_STATE;
					}

					const tracks = editor.timeline.getTracks();
					const fromIndex = tracks.findIndex(
						(track) => track.id === currentDragId,
					);

					if (fromIndex === -1 || fromIndex === dragOverIndex) {
						return INITIAL_STATE;
					}

					const newOrder = [...tracks.map((track) => track.id)];
					const [moved] = newOrder.splice(fromIndex, 1);
					newOrder.splice(dragOverIndex, 0, moved);

					editor.timeline.reorderTracks({ trackIds: newOrder });

					return INITIAL_STATE;
				});
			};

			document.addEventListener("mousemove", handleMouseMove);
			document.addEventListener("mouseup", handleMouseUp);
		},
		[editor, getTargetIndex],
	);

	return {
		reorderState,
		handleTrackDragStart,
	};
}
