import type {
	AudioElement,
	LibraryAudioElement,
	TimelineElement,
	TimelineTrack,
} from "@/types/timeline";
import type { MediaAsset } from "@/types/assets";
import { canElementHaveAudio } from "@/lib/timeline/element-utils";
import { canTracktHaveAudio } from "@/lib/timeline";
import { mediaSupportsAudio } from "@/lib/media/media-utils";

export type CollectedAudioElement = Omit<
	AudioElement,
	"type" | "mediaId" | "id" | "name" | "sourceType" | "sourceUrl"
> & { buffer: AudioBuffer; reversed?: boolean };

export function createAudioContext(): AudioContext {
	const AudioContextConstructor =
		window.AudioContext ||
		(window as typeof window & { webkitAudioContext?: typeof AudioContext })
			.webkitAudioContext;

	return new AudioContextConstructor();
}

export interface DecodedAudio {
	samples: Float32Array;
	sampleRate: number;
}

export async function decodeAudioToFloat32({
	audioBlob,
	targetSampleRate,
}: {
	audioBlob: Blob;
	targetSampleRate?: number;
}): Promise<DecodedAudio> {
	const audioContext = targetSampleRate
		? new AudioContext({ sampleRate: targetSampleRate })
		: createAudioContext();

	try {
		const arrayBuffer = await audioBlob.arrayBuffer();
		const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

		const numChannels = audioBuffer.numberOfChannels;
		const length = audioBuffer.length;
		const samples = new Float32Array(length);

		if (numChannels === 2) {
			// stereo -> mono with power-preserving scaling
			const SCALING_FACTOR = Math.sqrt(2);
			const left = audioBuffer.getChannelData(0);
			const right = audioBuffer.getChannelData(1);
			for (let i = 0; i < length; i++) {
				samples[i] = (SCALING_FACTOR * (left[i] + right[i])) / 2;
			}
		} else {
			const channel = audioBuffer.getChannelData(0);
			for (let i = 0; i < length; i++) {
				samples[i] = channel[i];
			}
		}

		return { samples, sampleRate: audioBuffer.sampleRate };
	} finally {
		await audioContext.close();
	}
}

export async function collectAudioElements({
	tracks,
	mediaAssets,
	audioContext,
}: {
	tracks: TimelineTrack[];
	mediaAssets: MediaAsset[];
	audioContext: AudioContext;
}): Promise<CollectedAudioElement[]> {
	const mediaMap = new Map<string, MediaAsset>(
		mediaAssets.map((media) => [media.id, media]),
	);
	const pendingElements: Array<Promise<CollectedAudioElement | null>> = [];

	for (const track of tracks) {
		if (canTracktHaveAudio(track) && track.muted) continue;

		for (const element of track.elements) {
			if (!canElementHaveAudio(element)) continue;
			if (element.duration <= 0) continue;

			const isTrackMuted = canTracktHaveAudio(track) && track.muted;
			const isElementMuted =
				"muted" in element ? (element.muted ?? false) : false;
			const muted = isTrackMuted || isElementMuted;

		if (element.type === "audio") {
			const volume = element.volume ?? 1;
			pendingElements.push(
				resolveAudioBufferForElement({
					element,
					mediaMap,
					audioContext,
				}).then((audioBuffer) => {
					if (!audioBuffer) return null;
					return {
						buffer: audioBuffer,
						startTime: element.startTime,
						duration: element.duration,
						trimStart: element.trimStart,
						trimEnd: element.trimEnd,
						volume,
						muted,
						playbackRate: element.playbackRate ?? 1,
					};
				}),
			);
		}

		if (element.type === "video") {
			const mediaAsset = mediaMap.get(element.mediaId);
			if (!mediaAsset || !mediaSupportsAudio({ media: mediaAsset }))
				continue;

			pendingElements.push(
				resolveVideoAudioBuffer({
					file: mediaAsset.file,
					audioContext,
				}).then((audioBuffer) => {
					if (!audioBuffer) return null;
					return {
						buffer: audioBuffer,
						startTime: element.startTime,
						duration: element.duration,
						trimStart: element.trimStart,
						trimEnd: element.trimEnd,
						volume: 1,
						muted,
						playbackRate: element.playbackRate ?? 1,
						reversed: element.reversed ?? false,
					};
				}),
			);
		}
		}
	}

	const resolvedElements = await Promise.all(pendingElements);
	const audioElements: CollectedAudioElement[] = [];
	for (const element of resolvedElements) {
		if (element) audioElements.push(element);
	}
	return audioElements;
}

async function resolveVideoAudioBuffer({
	file,
	audioContext,
}: {
	file: File;
	audioContext: AudioContext;
}): Promise<AudioBuffer | null> {
	try {
		const arrayBuffer = await file.arrayBuffer();
		return await audioContext.decodeAudioData(arrayBuffer.slice(0));
	} catch (error) {
		console.warn("Failed to decode video audio:", error);
		return null;
	}
}

async function resolveAudioBufferForElement({
	element,
	mediaMap,
	audioContext,
}: {
	element: AudioElement;
	mediaMap: Map<string, MediaAsset>;
	audioContext: AudioContext;
}): Promise<AudioBuffer | null> {
	try {
		if (element.sourceType === "upload") {
			const asset = mediaMap.get(element.mediaId);
			if (!asset || !mediaSupportsAudio({ media: asset })) return null;

			const arrayBuffer = await asset.file.arrayBuffer();
			return await audioContext.decodeAudioData(arrayBuffer.slice(0));
		}

		if (element.buffer) return element.buffer;

		const response = await fetch(element.sourceUrl);
		if (!response.ok) {
			throw new Error(`Library audio fetch failed: ${response.status}`);
		}

		const arrayBuffer = await response.arrayBuffer();
		return await audioContext.decodeAudioData(arrayBuffer.slice(0));
	} catch (error) {
		console.warn("Failed to decode audio:", error);
		return null;
	}
}

interface AudioMixSource {
	file: File;
	startTime: number;
	duration: number;
	trimStart: number;
	trimEnd: number;
	playbackRate: number;
}

export interface AudioClipSource {
	id: string;
	sourceKey: string;
	file: File;
	startTime: number;
	duration: number;
	trimStart: number;
	trimEnd: number;
	muted: boolean;
	volume: number;
	playbackRate: number;
}

async function fetchLibraryAudioSource({
	element,
}: {
	element: LibraryAudioElement;
}): Promise<AudioMixSource | null> {
	try {
		const response = await fetch(element.sourceUrl);
		if (!response.ok) {
			throw new Error(`Library audio fetch failed: ${response.status}`);
		}

		const blob = await response.blob();
		const file = new File([blob], `${element.name}.mp3`, {
			type: "audio/mpeg",
		});

		return {
			file,
			startTime: element.startTime,
			duration: element.duration,
			trimStart: element.trimStart,
			trimEnd: element.trimEnd,
			playbackRate: element.playbackRate ?? 1,
		};
	} catch (error) {
		console.warn("Failed to fetch library audio:", error);
		return null;
	}
}

async function fetchLibraryAudioClip({
	element,
	muted,
}: {
	element: LibraryAudioElement;
	muted: boolean;
}): Promise<AudioClipSource | null> {
	try {
		const response = await fetch(element.sourceUrl);
		if (!response.ok) {
			throw new Error(`Library audio fetch failed: ${response.status}`);
		}

		const blob = await response.blob();
		const file = new File([blob], `${element.name}.mp3`, {
			type: "audio/mpeg",
		});

		return {
			id: element.id,
			sourceKey: element.id,
			file,
			startTime: element.startTime,
			duration: element.duration,
			trimStart: element.trimStart,
			trimEnd: element.trimEnd,
			muted,
			volume: element.volume ?? 1,
			playbackRate: element.playbackRate ?? 1,
		};
	} catch (error) {
		console.warn("Failed to fetch library audio:", error);
		return null;
	}
}

function getElementPlaybackRate({
	element,
}: {
	element: TimelineElement;
}): number {
	if ("playbackRate" in element && typeof element.playbackRate === "number") {
		return element.playbackRate;
	}
	return 1;
}

function collectMediaAudioSource({
	element,
	mediaAsset,
}: {
	element: TimelineElement;
	mediaAsset: MediaAsset;
}): AudioMixSource {
	return {
		file: mediaAsset.file,
		startTime: element.startTime,
		duration: element.duration,
		trimStart: element.trimStart,
		trimEnd: element.trimEnd,
		playbackRate: getElementPlaybackRate({ element }),
	};
}

function getElementVolume({
	element,
}: {
	element: TimelineElement;
}): number {
	if ("volume" in element && typeof element.volume === "number") {
		return element.volume;
	}
	return 1;
}

function collectMediaAudioClip({
	element,
	mediaAsset,
	muted,
}: {
	element: TimelineElement;
	mediaAsset: MediaAsset;
	muted: boolean;
}): AudioClipSource {
	return {
		id: element.id,
		sourceKey: mediaAsset.id,
		file: mediaAsset.file,
		startTime: element.startTime,
		duration: element.duration,
		trimStart: element.trimStart,
		trimEnd: element.trimEnd,
		muted,
		volume: getElementVolume({ element }),
		playbackRate: getElementPlaybackRate({ element }),
	};
}

export async function collectAudioMixSources({
	tracks,
	mediaAssets,
}: {
	tracks: TimelineTrack[];
	mediaAssets: MediaAsset[];
}): Promise<AudioMixSource[]> {
	const audioMixSources: AudioMixSource[] = [];
	const mediaMap = new Map<string, MediaAsset>(
		mediaAssets.map((asset) => [asset.id, asset]),
	);
	const pendingLibrarySources: Array<Promise<AudioMixSource | null>> = [];

	for (const track of tracks) {
		if (canTracktHaveAudio(track) && track.muted) continue;

		for (const element of track.elements) {
			if (!canElementHaveAudio(element)) continue;

			const isElementMuted =
				"muted" in element ? (element.muted ?? false) : false;
			if (isElementMuted) continue;

			if (element.type === "audio") {
				if (element.sourceType === "upload") {
					const mediaAsset = mediaMap.get(element.mediaId);
					if (!mediaAsset) continue;

					audioMixSources.push(
						collectMediaAudioSource({ element, mediaAsset }),
					);
				} else {
					pendingLibrarySources.push(fetchLibraryAudioSource({ element }));
				}
				continue;
			}

			if (element.type === "video") {
				const mediaAsset = mediaMap.get(element.mediaId);
				if (!mediaAsset) continue;

				if (mediaSupportsAudio({ media: mediaAsset })) {
					audioMixSources.push(
						collectMediaAudioSource({ element, mediaAsset }),
					);
				}
			}
		}
	}

	const resolvedLibrarySources = await Promise.all(pendingLibrarySources);
	for (const source of resolvedLibrarySources) {
		if (source) audioMixSources.push(source);
	}

	return audioMixSources;
}

export async function collectAudioClips({
	tracks,
	mediaAssets,
}: {
	tracks: TimelineTrack[];
	mediaAssets: MediaAsset[];
}): Promise<AudioClipSource[]> {
	const clips: AudioClipSource[] = [];
	const mediaMap = new Map<string, MediaAsset>(
		mediaAssets.map((asset) => [asset.id, asset]),
	);
	const pendingLibraryClips: Array<Promise<AudioClipSource | null>> = [];

	for (const track of tracks) {
		const isTrackMuted = canTracktHaveAudio(track) && track.muted;

		for (const element of track.elements) {
			if (!canElementHaveAudio(element)) continue;

			const isElementMuted =
				"muted" in element ? (element.muted ?? false) : false;
			const muted = isTrackMuted || isElementMuted;

			if (element.type === "audio") {
				if (element.sourceType === "upload") {
					const mediaAsset = mediaMap.get(element.mediaId);
					if (!mediaAsset) continue;

					clips.push(
						collectMediaAudioClip({
							element,
							mediaAsset,
							muted,
						}),
					);
				} else {
					pendingLibraryClips.push(fetchLibraryAudioClip({ element, muted }));
				}
				continue;
			}

			if (element.type === "video") {
				const mediaAsset = mediaMap.get(element.mediaId);
				if (!mediaAsset) continue;

				if (mediaSupportsAudio({ media: mediaAsset })) {
					clips.push(
						collectMediaAudioClip({
							element,
							mediaAsset,
							muted,
						}),
					);
				}
			}
		}
	}

	const resolvedLibraryClips = await Promise.all(pendingLibraryClips);
	for (const clip of resolvedLibraryClips) {
		if (clip) clips.push(clip);
	}

	return clips;
}

export async function createTimelineAudioBuffer({
	tracks,
	mediaAssets,
	duration,
	sampleRate = 44100,
	audioContext,
}: {
	tracks: TimelineTrack[];
	mediaAssets: MediaAsset[];
	duration: number;
	sampleRate?: number;
	audioContext?: AudioContext;
}): Promise<AudioBuffer | null> {
	const context = audioContext ?? createAudioContext();

	try {
	const audioElements = await collectAudioElements({
		tracks,
		mediaAssets,
		audioContext: context,
	});

	if (audioElements.length === 0) return null;

	const outputChannels = 2;
	const outputLength = Math.ceil(duration * sampleRate);
	const outputBuffer = context.createBuffer(
		outputChannels,
		outputLength,
		sampleRate,
	);

	for (const element of audioElements) {
		if (element.muted) continue;

		mixAudioChannels({
			element,
			outputBuffer,
			outputLength,
			sampleRate,
		});
	}

	return outputBuffer;
	} finally {
		if (!audioContext) await context.close();
	}
}

function mixAudioChannels({
	element,
	outputBuffer,
	outputLength,
	sampleRate,
}: {
	element: CollectedAudioElement;
	outputBuffer: AudioBuffer;
	outputLength: number;
	sampleRate: number;
}): void {
	const {
		buffer,
		startTime,
		trimStart,
		duration: elementDuration,
		volume,
		playbackRate = 1,
		reversed = false,
	} = element;

	const sourceStartSample = Math.floor(trimStart * buffer.sampleRate);
	const sourceEndSample = Math.min(
		buffer.length - 1,
		Math.ceil((trimStart + elementDuration * playbackRate) * buffer.sampleRate) -
			1,
	);
	const outputStartSample = Math.floor(startTime * sampleRate);
	const outputSampleCount = Math.floor(elementDuration * sampleRate);
	const sourceStep = (buffer.sampleRate / sampleRate) * playbackRate;

	const outputChannels = 2;
	for (let channel = 0; channel < outputChannels; channel++) {
		const outputData = outputBuffer.getChannelData(channel);
		const sourceChannel = Math.min(channel, buffer.numberOfChannels - 1);
		const sourceData = buffer.getChannelData(sourceChannel);

		for (let i = 0; i < outputSampleCount; i++) {
			const outputIndex = outputStartSample + i;
			if (outputIndex >= outputLength) break;

			const sourcePos = reversed
				? sourceEndSample - i * sourceStep
				: sourceStartSample + i * sourceStep;
			const sourceIndex = Math.floor(sourcePos);
			if (sourceIndex < 0 || sourceIndex >= sourceData.length) continue;

			const fraction = sourcePos - sourceIndex;
			const sample0 = sourceData[sourceIndex];
			const sample1 =
				sourceIndex + 1 < sourceData.length
					? sourceData[sourceIndex + 1]
					: sample0;
			const interpolated = sample0 + fraction * (sample1 - sample0);

			outputData[outputIndex] += interpolated * volume;
		}
	}
}
