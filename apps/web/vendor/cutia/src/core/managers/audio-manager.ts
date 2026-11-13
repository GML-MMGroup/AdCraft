import type { EditorCore } from "@/core";
import type { AudioClipSource } from "@/lib/media/audio";
import { createAudioContext, collectAudioClips } from "@/lib/media/audio";

export class AudioManager {
	private audioContext: AudioContext | null = null;
	private masterGain: GainNode | null = null;
	private playbackStartTime = 0;
	private playbackStartContextTime = 0;
	private clips: AudioClipSource[] = [];
	private decodedBuffers = new Map<string, AudioBuffer>();
	private queuedSources = new Set<AudioBufferSourceNode>();
	private playbackSessionId = 0;
	private lastIsPlaying = false;
	private lastVolume = 1;
	private unsubscribers: Array<() => void> = [];
	private timelineChangeTimer: number | null = null;

	constructor(private editor: EditorCore) {
		this.lastVolume = this.editor.playback.getVolume();

		this.unsubscribers.push(
			this.editor.playback.subscribe(this.handlePlaybackChange),
			this.editor.timeline.subscribe(this.handleTimelineChange),
			this.editor.media.subscribe(this.handleTimelineChange),
		);
		if (typeof window !== "undefined") {
			window.addEventListener("playback-seek", this.handleSeek);
		}
	}

	dispose(): void {
		this.stopPlayback();
		if (this.timelineChangeTimer !== null) {
			window.clearTimeout(this.timelineChangeTimer);
			this.timelineChangeTimer = null;
		}
		for (const unsub of this.unsubscribers) {
			unsub();
		}
		this.unsubscribers = [];
		if (typeof window !== "undefined") {
			window.removeEventListener("playback-seek", this.handleSeek);
		}
		this.decodedBuffers.clear();
		if (this.audioContext) {
			void this.audioContext.close();
			this.audioContext = null;
			this.masterGain = null;
		}
	}

	private handlePlaybackChange = (): void => {
		const isPlaying = this.editor.playback.getIsPlaying();
		const volume = this.editor.playback.getVolume();

		if (volume !== this.lastVolume) {
			this.lastVolume = volume;
			this.updateGain();
		}

		if (isPlaying !== this.lastIsPlaying) {
			this.lastIsPlaying = isPlaying;
			if (isPlaying) {
				void this.startPlayback({
					time: this.editor.playback.getCurrentTime(),
				});
			} else {
				this.stopPlayback();
			}
		}
	};

	private handleSeek = (event: Event): void => {
		const detail = (event as CustomEvent<{ time: number }>).detail;
		if (!detail) return;

		if (this.editor.playback.getIsScrubbing()) {
			this.stopPlayback();
			return;
		}

		if (this.editor.playback.getIsPlaying()) {
			void this.startPlayback({ time: detail.time });
			return;
		}

		this.stopPlayback();
	};

	private handleTimelineChange = (): void => {
		if (this.timelineChangeTimer !== null) {
			window.clearTimeout(this.timelineChangeTimer);
		}

		this.timelineChangeTimer = window.setTimeout(() => {
			this.timelineChangeTimer = null;
			this.decodedBuffers.clear();

			if (!this.editor.playback.getIsPlaying()) return;

			void this.startPlayback({
				time: this.editor.playback.getCurrentTime(),
			});
		}, 300);
	};

	private ensureAudioContext(): AudioContext | null {
		if (this.audioContext) return this.audioContext;
		if (typeof window === "undefined") return null;

		this.audioContext = createAudioContext();
		this.masterGain = this.audioContext.createGain();
		this.masterGain.gain.value = this.lastVolume;
		this.masterGain.connect(this.audioContext.destination);
		return this.audioContext;
	}

	private updateGain(): void {
		if (!this.masterGain) return;
		this.masterGain.gain.value = this.lastVolume;
	}

	private async startPlayback({ time }: { time: number }): Promise<void> {
		const audioContext = this.ensureAudioContext();
		if (!audioContext) return;

		this.stopPlayback();
		this.playbackSessionId++;
		const sessionId = this.playbackSessionId;

		const tracks = this.editor.timeline.getTracks();
		const mediaAssets = this.editor.media.getAssets();
		const duration = this.editor.timeline.getTotalDuration();

		if (duration <= 0) return;

		if (audioContext.state === "suspended") {
			await audioContext.resume();
		}

		this.clips = await collectAudioClips({ tracks, mediaAssets });
		if (!this.editor.playback.getIsPlaying()) return;
		if (sessionId !== this.playbackSessionId) return;

		this.playbackStartTime = time;
		this.playbackStartContextTime = audioContext.currentTime;

		await this.scheduleAllClips({ time, sessionId });
	}

	private async scheduleAllClips({
		time,
		sessionId,
	}: {
		time: number;
		sessionId: number;
	}): Promise<void> {
		const audioContext = this.audioContext;
		if (!audioContext) return;

		for (const clip of this.clips) {
			if (clip.muted) continue;

			const clipEnd = clip.startTime + clip.duration;
			if (clipEnd <= time) continue;
			if (sessionId !== this.playbackSessionId) return;

			try {
				const buffer = await this.getDecodedBuffer({ clip });
				if (!buffer) continue;
				if (sessionId !== this.playbackSessionId) return;
				if (!this.editor.playback.getIsPlaying()) return;

				this.scheduleClipNode({ clip, buffer, time });
			} catch (error) {
				console.warn("Failed to schedule audio clip:", clip.id, error);
			}
		}
	}

	private scheduleClipNode({
		clip,
		buffer,
		time,
	}: {
		clip: AudioClipSource;
		buffer: AudioBuffer;
		time: number;
	}): void {
		const audioContext = this.audioContext;
		if (!audioContext || !this.masterGain) return;

		const rate = clip.playbackRate;
		const elapsed = Math.max(0, time - clip.startTime);
		const sourceOffset = clip.trimStart + elapsed * rate;
		const remainingDuration = clip.duration - elapsed;

		if (remainingDuration <= 0) return;

		const timelineStart = Math.max(clip.startTime, time);
		const scheduleTime =
			this.playbackStartContextTime +
			(timelineStart - this.playbackStartTime);

		const node = audioContext.createBufferSource();
		node.buffer = buffer;
		node.playbackRate.value = rate;

		const clipGain = audioContext.createGain();
		clipGain.gain.value = clip.volume;
		node.connect(clipGain);
		clipGain.connect(this.masterGain);

		if (scheduleTime >= audioContext.currentTime) {
			node.start(scheduleTime, sourceOffset, remainingDuration);
		} else {
			const late = audioContext.currentTime - scheduleTime;
			const adjustedOffset = sourceOffset + late * rate;
			const adjustedDuration = remainingDuration - late;
			if (adjustedDuration > 0) {
				node.start(audioContext.currentTime, adjustedOffset, adjustedDuration);
			} else {
				return;
			}
		}

		this.queuedSources.add(node);
		node.addEventListener("ended", () => {
			node.disconnect();
			this.queuedSources.delete(node);
		});
	}

	private async getDecodedBuffer({
		clip,
	}: {
		clip: AudioClipSource;
	}): Promise<AudioBuffer | null> {
		const cached = this.decodedBuffers.get(clip.sourceKey);
		if (cached) return cached;

		const audioContext = this.audioContext;
		if (!audioContext) return null;

		try {
			const arrayBuffer = await clip.file.arrayBuffer();
			// .slice(0) avoids the detached-buffer error on repeated decodes
			const buffer = await audioContext.decodeAudioData(arrayBuffer.slice(0));
			this.decodedBuffers.set(clip.sourceKey, buffer);
			return buffer;
		} catch (error) {
			console.warn("Failed to decode audio:", clip.sourceKey, error);
			return null;
		}
	}

	private stopPlayback(): void {
		for (const source of this.queuedSources) {
			try {
				source.stop();
			} catch {}
			source.disconnect();
		}
		this.queuedSources.clear();
	}
}
