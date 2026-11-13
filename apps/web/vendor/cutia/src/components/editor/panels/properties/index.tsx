"use client";

import { useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AudioProperties } from "./audio-properties";
import { VideoProperties } from "./video-properties";
import { TextProperties } from "./text-properties";
import { StickerProperties } from "./sticker-properties";
import { EmptyView } from "./empty-view";
import { useEditor } from "@/hooks/use-editor";
import { useElementSelection } from "@/hooks/timeline/element/use-element-selection";
import type { TimelineElement, TimelineTrack } from "@/types/timeline";

interface ElementWithTrack {
	element: TimelineElement;
	track: TimelineTrack;
}

function groupByType(items: ElementWithTrack[]) {
	const groups: Record<string, ElementWithTrack[]> = {};
	for (const item of items) {
		const key = item.element.type;
		if (!groups[key]) groups[key] = [];
		groups[key].push(item);
	}
	return groups;
}

export function PropertiesPanel() {
	const editor = useEditor();
	const { selectedElements } = useElementSelection();

	const elementsWithTracks = editor.timeline.getElementsWithTracks({
		elements: selectedElements,
	});

	const grouped = useMemo(
		() => groupByType(elementsWithTracks),
		[elementsWithTracks],
	);

	return (
		<div className="panel bg-background h-full rounded-sm border overflow-hidden">
			{selectedElements.length > 0 ? (
				<ScrollArea className="h-full">
					{grouped.text && grouped.text.length > 0 && (
						<TextProperties
							elements={grouped.text.map((item) => ({
								element: item.element as import("@/types/timeline").TextElement,
								trackId: item.track.id,
							}))}
						/>
					)}
					{grouped.video && grouped.video.length > 0 && (
						<VideoProperties
							_element={
								grouped.video[0]
									.element as import("@/types/timeline").VideoElement
							}
							trackId={grouped.video[0].track.id}
						/>
					)}
					{grouped.image && grouped.image.length > 0 && (
						<VideoProperties
							_element={
								grouped.image[0]
									.element as import("@/types/timeline").ImageElement
							}
							trackId={grouped.image[0].track.id}
						/>
					)}
				{grouped.audio && grouped.audio.length > 0 && (
					<AudioProperties
						_element={
							grouped.audio[0]
								.element as import("@/types/timeline").AudioElement
						}
						trackId={grouped.audio[0].track.id}
					/>
				)}
				{grouped.sticker && grouped.sticker.length > 0 && (
					<StickerProperties
						_element={
							grouped.sticker[0]
								.element as import("@/types/timeline").StickerElement
						}
						trackId={grouped.sticker[0].track.id}
					/>
				)}
				</ScrollArea>
			) : (
				<EmptyView />
			)}
		</div>
	);
}
