import { Command } from "@/lib/commands/base-command";
import type { TimelineTrack } from "@/types/timeline";
import { EditorCore } from "@/core";
import { isMainTrack, hasMediaId } from "@/lib/timeline";
import { storageService } from "@/services/storage/service";
import type { MediaAsset } from "@/types/assets";

export class DeleteElementsCommand extends Command {
	private savedState: TimelineTrack[] | null = null;
	private removedEphemeralAssets: MediaAsset[] = [];

	constructor(private elements: { trackId: string; elementId: string }[]) {
		super();
	}

	execute(): void {
		const editor = EditorCore.getInstance();
		this.savedState = editor.timeline.getTracks();

		const deletedMediaIds = new Set<string>();
		for (const track of this.savedState) {
			for (const element of track.elements) {
				const isDeleted = this.elements.some(
					(el) => el.trackId === track.id && el.elementId === element.id,
				);
				if (isDeleted && hasMediaId(element)) {
					deletedMediaIds.add(element.mediaId);
				}
			}
		}

		const updatedTracks = this.savedState
			.map((track) => {
				const hasElementsToDelete = this.elements.some(
					(el) => el.trackId === track.id,
				);

				if (!hasElementsToDelete) {
					return track;
				}

				return {
					...track,
					elements: track.elements.filter(
						(element) =>
							!this.elements.some(
								(el) => el.trackId === track.id && el.elementId === element.id,
							),
					),
				} as typeof track;
			})
			.filter((track) => track.elements.length > 0 || isMainTrack(track));

		editor.timeline.updateTracks(updatedTracks);

		this.cleanupEphemeralAssets({ editor, deletedMediaIds });
	}

	private cleanupEphemeralAssets({
		editor,
		deletedMediaIds,
	}: {
		editor: EditorCore;
		deletedMediaIds: Set<string>;
	}): void {
		if (deletedMediaIds.size === 0) return;

		const projectId = editor.project.getActiveOrNull()?.metadata.id;
		if (!projectId) return;

		const assets = editor.media.getAssets();
		const ephemeralToRemove = assets.filter(
			(asset) => asset.ephemeral && deletedMediaIds.has(asset.id),
		);

		if (ephemeralToRemove.length === 0) return;

		this.removedEphemeralAssets = ephemeralToRemove;

		const remainingAssets = assets.filter(
			(asset) => !ephemeralToRemove.some((removed) => removed.id === asset.id),
		);
		editor.media.setAssets({ assets: remainingAssets });

		for (const asset of ephemeralToRemove) {
			storageService
				.deleteMediaAsset({ projectId, id: asset.id })
				.catch((error) => {
					console.error("Failed to cleanup ephemeral media:", error);
				});
		}
	}

	undo(): void {
		if (this.savedState) {
			const editor = EditorCore.getInstance();
			editor.timeline.updateTracks(this.savedState);

			if (this.removedEphemeralAssets.length > 0) {
				const assets = editor.media.getAssets();
				editor.media.setAssets({
					assets: [...assets, ...this.removedEphemeralAssets],
				});

				const projectId = editor.project.getActiveOrNull()?.metadata.id;
				if (projectId) {
					for (const asset of this.removedEphemeralAssets) {
						storageService
							.saveMediaAsset({ projectId, mediaAsset: asset })
							.catch((error) => {
								console.error("Failed to restore ephemeral media on undo:", error);
							});
					}
				}
			}
		}
	}
}
