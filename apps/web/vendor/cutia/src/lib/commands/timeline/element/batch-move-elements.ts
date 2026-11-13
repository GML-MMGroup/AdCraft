import { Command } from "@/lib/commands/base-command";
import type { TimelineTrack } from "@/types/timeline";
import { EditorCore } from "@/core";

export class BatchMoveElementsCommand extends Command {
	private savedState: TimelineTrack[] | null = null;

	constructor(
		private elements: { trackId: string; elementId: string }[],
		private timeDelta: number,
	) {
		super();
	}

	execute(): void {
		const editor = EditorCore.getInstance();
		this.savedState = editor.timeline.getTracks();

		const elementSet = new Set(
			this.elements.map(({ trackId, elementId }) => `${trackId}:${elementId}`),
		);

		const updatedTracks = this.savedState.map((track) => {
			const hasAffectedElements = this.elements.some(
				(element) => element.trackId === track.id,
			);
			if (!hasAffectedElements) return track;

			const newElements = track.elements.map((element) => {
				const key = `${track.id}:${element.id}`;
				if (!elementSet.has(key)) return element;

				const newStartTime = Math.max(0, element.startTime + this.timeDelta);
				return { ...element, startTime: newStartTime };
			});

			return { ...track, elements: newElements } as typeof track;
		});

		editor.timeline.updateTracks(updatedTracks);
	}

	undo(): void {
		if (this.savedState) {
			const editor = EditorCore.getInstance();
			editor.timeline.updateTracks(this.savedState);
		}
	}
}
