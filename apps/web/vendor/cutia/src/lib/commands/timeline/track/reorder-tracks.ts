import { Command } from "@/lib/commands/base-command";
import type { TimelineTrack } from "@/types/timeline";
import { EditorCore } from "@/core";

export class ReorderTracksCommand extends Command {
	private savedState: TimelineTrack[] | null = null;

	constructor(private newOrder: string[]) {
		super();
	}

	execute(): void {
		const editor = EditorCore.getInstance();
		const currentTracks = editor.timeline.getTracks();
		this.savedState = currentTracks;

		const trackMap = new Map(currentTracks.map((track) => [track.id, track]));
		const reorderedTracks: TimelineTrack[] = [];

		for (const trackId of this.newOrder) {
			const track = trackMap.get(trackId);
			if (track) {
				reorderedTracks.push(track);
			}
		}

		editor.timeline.updateTracks(reorderedTracks);
	}

	undo(): void {
		if (this.savedState) {
			const editor = EditorCore.getInstance();
			editor.timeline.updateTracks(this.savedState);
		}
	}
}
