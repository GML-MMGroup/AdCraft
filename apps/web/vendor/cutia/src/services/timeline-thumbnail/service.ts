import { Input, ALL_FORMATS, BlobSource, VideoSampleSink } from "mediabunny";

interface SinkData {
	sink: VideoSampleSink;
}

const MAX_CACHED_THUMBNAILS = 500;
const THUMBNAIL_HEIGHT = 120;

function snapTime({ time, fps }: { time: number; fps: number }): number {
	return Math.floor(time * fps) / fps;
}

function makeKey({
	mediaId,
	snappedTime,
}: {
	mediaId: string;
	snappedTime: number;
}): string {
	return `${mediaId}:${snappedTime.toFixed(4)}`;
}

function binarySearchNearest({
	sortedTimes,
	target,
}: {
	sortedTimes: number[];
	target: number;
}): number {
	if (sortedTimes.length === 0) return -1;

	let lo = 0;
	let hi = sortedTimes.length - 1;

	while (lo < hi) {
		const mid = (lo + hi) >>> 1;
		if (sortedTimes[mid] < target) lo = mid + 1;
		else hi = mid;
	}

	if (lo > 0) {
		const distLo = Math.abs(sortedTimes[lo] - target);
		const distPrev = Math.abs(sortedTimes[lo - 1] - target);
		if (distPrev < distLo) return lo - 1;
	}

	return lo;
}

class TimelineThumbnailCache {
	private thumbnails = new Map<string, ImageBitmap>();
	private timeIndex = new Map<string, number[]>();
	private sinks = new Map<string, SinkData>();
	private initPromises = new Map<string, Promise<SinkData | null>>();
	private pending = new Map<string, Promise<ImageBitmap | null>>();

	getCachedThumbnail({
		mediaId,
		time,
		fps,
	}: {
		mediaId: string;
		time: number;
		fps: number;
	}): ImageBitmap | null {
		const key = makeKey({
			mediaId,
			snappedTime: snapTime({ time, fps }),
		});
		return this.thumbnails.get(key) ?? null;
	}

	getNearestCachedThumbnail({
		mediaId,
		time,
	}: {
		mediaId: string;
		time: number;
	}): ImageBitmap | null {
		const times = this.timeIndex.get(mediaId);
		if (!times || times.length === 0) return null;

		const idx = binarySearchNearest({ sortedTimes: times, target: time });
		if (idx === -1) return null;

		const key = makeKey({ mediaId, snappedTime: times[idx] });
		return this.thumbnails.get(key) ?? null;
	}

	async getThumbnail({
		mediaId,
		file,
		time,
		fps,
	}: {
		mediaId: string;
		file: File;
		time: number;
		fps: number;
	}): Promise<ImageBitmap | null> {
		const snappedTime = snapTime({ time, fps });
		const key = makeKey({ mediaId, snappedTime });

		const cached = this.thumbnails.get(key);
		if (cached) return cached;

		const pendingPromise = this.pending.get(key);
		if (pendingPromise) return pendingPromise;

		const promise = this.generateThumbnail({
			mediaId,
			file,
			time: snappedTime,
			key,
		});
		this.pending.set(key, promise);

		try {
			return await promise;
		} finally {
			this.pending.delete(key);
		}
	}

	async loadThumbnailsBatch({
		mediaId,
		file,
		times,
		fps,
		onThumbnail,
	}: {
		mediaId: string;
		file: File;
		times: { index: number; time: number }[];
		fps: number;
		onThumbnail: (params: { index: number; bitmap: ImageBitmap }) => void;
	}): Promise<void> {
		const sinkData = await this.ensureSink({ mediaId, file });
		if (!sinkData) return;

		const uniqueTimes: number[] = [];
		const timeToIndices = new Map<number, number[]>();

		for (const { index, time } of times) {
			const snappedTime = snapTime({ time, fps });
			const key = makeKey({ mediaId, snappedTime });
			if (this.thumbnails.has(key)) continue;

			const existing = timeToIndices.get(snappedTime);
			if (existing) {
				existing.push(index);
			} else {
				uniqueTimes.push(snappedTime);
				timeToIndices.set(snappedTime, [index]);
			}
		}

		if (uniqueTimes.length === 0) return;

		try {
			const iterator =
				sinkData.sink.samplesAtTimestamps(uniqueTimes);
			let j = 0;

			for await (const sample of iterator) {
				if (j >= uniqueTimes.length) break;
				const snappedTime = uniqueTimes[j];
				j++;

				if (!sample) continue;

				try {
					const bitmap = await this.scaleSampleToBitmap({ sample });
					if (!bitmap) continue;

					const key = makeKey({ mediaId, snappedTime });
					this.evictIfNeeded();
					this.thumbnails.set(key, bitmap);
					this.addToTimeIndex({ mediaId, time: snappedTime });

					const indices = timeToIndices.get(snappedTime);
					if (indices) {
						for (const index of indices) {
							onThumbnail({ index, bitmap });
						}
					}
				} finally {
					sample.close();
				}
			}
		} catch (error) {
			console.warn(
				`Batch thumbnail load failed for ${mediaId}:`,
				error,
			);
		}
	}

	clearMedia({ mediaId }: { mediaId: string }): void {
		this.sinks.delete(mediaId);
		this.initPromises.delete(mediaId);
		this.timeIndex.delete(mediaId);

		for (const [key, bitmap] of this.thumbnails) {
			if (key.startsWith(`${mediaId}:`)) {
				bitmap.close();
				this.thumbnails.delete(key);
			}
		}
	}

	clearAll(): void {
		for (const [, bitmap] of this.thumbnails) {
			bitmap.close();
		}
		this.thumbnails.clear();
		this.timeIndex.clear();
		this.sinks.clear();
		this.initPromises.clear();
		this.pending.clear();
	}

	private async generateThumbnail({
		mediaId,
		file,
		time,
		key,
	}: {
		mediaId: string;
		file: File;
		time: number;
		key: string;
	}): Promise<ImageBitmap | null> {
		const sinkData = await this.ensureSink({ mediaId, file });
		if (!sinkData) return null;

		try {
			const sample = await sinkData.sink.getSample(time);
			if (!sample) return null;

			try {
				const bitmap = await this.scaleSampleToBitmap({ sample });
				if (!bitmap) return null;

				this.evictIfNeeded();
				this.thumbnails.set(key, bitmap);
				this.addToTimeIndex({ mediaId, time });
				return bitmap;
			} finally {
				sample.close();
			}
		} catch (error) {
			console.warn(
				`Failed to get thumbnail for ${mediaId} at ${time}:`,
				error,
			);
			return null;
		}
	}

	private async scaleSampleToBitmap({
		sample,
	}: {
		sample: {
			codedWidth: number;
			codedHeight: number;
			draw: (
				ctx: OffscreenCanvasRenderingContext2D,
				dx: number,
				dy: number,
				dw: number,
				dh: number,
			) => void;
		};
	}): Promise<ImageBitmap | null> {
		const scale = Math.min(1, THUMBNAIL_HEIGHT / sample.codedHeight);
		const thumbWidth = Math.round(sample.codedWidth * scale);
		const thumbHeight = Math.round(sample.codedHeight * scale);

		const canvas = new OffscreenCanvas(thumbWidth, thumbHeight);
		const ctx = canvas.getContext("2d");
		if (!ctx) return null;

		sample.draw(ctx, 0, 0, thumbWidth, thumbHeight);
		return createImageBitmap(canvas);
	}

	private addToTimeIndex({
		mediaId,
		time,
	}: {
		mediaId: string;
		time: number;
	}): void {
		let times = this.timeIndex.get(mediaId);
		if (!times) {
			times = [];
			this.timeIndex.set(mediaId, times);
		}

		let lo = 0;
		let hi = times.length;
		while (lo < hi) {
			const mid = (lo + hi) >>> 1;
			if (times[mid] < time) lo = mid + 1;
			else hi = mid;
		}
		if (lo >= times.length || times[lo] !== time) {
			times.splice(lo, 0, time);
		}
	}

	private evictIfNeeded(): void {
		if (this.thumbnails.size < MAX_CACHED_THUMBNAILS) return;

		const keysToRemove = Array.from(this.thumbnails.keys()).slice(
			0,
			Math.floor(MAX_CACHED_THUMBNAILS * 0.2),
		);

		for (const key of keysToRemove) {
			const bitmap = this.thumbnails.get(key);
			if (bitmap) bitmap.close();
			this.thumbnails.delete(key);

			const colonIdx = key.lastIndexOf(":");
			if (colonIdx !== -1) {
				const mediaId = key.substring(0, colonIdx);
				const time = Number.parseFloat(key.substring(colonIdx + 1));
				const times = this.timeIndex.get(mediaId);
				if (times) {
					const idx = times.indexOf(time);
					if (idx !== -1) times.splice(idx, 1);
					if (times.length === 0) this.timeIndex.delete(mediaId);
				}
			}
		}
	}

	private async ensureSink({
		mediaId,
		file,
	}: {
		mediaId: string;
		file: File;
	}): Promise<SinkData | null> {
		const existing = this.sinks.get(mediaId);
		if (existing) return existing;

		const existingPromise = this.initPromises.get(mediaId);
		if (existingPromise) return existingPromise;

		const promise = this.initializeSink({ mediaId, file });
		this.initPromises.set(mediaId, promise);

		try {
			return await promise;
		} finally {
			this.initPromises.delete(mediaId);
		}
	}

	private async initializeSink({
		mediaId,
		file,
	}: {
		mediaId: string;
		file: File;
	}): Promise<SinkData | null> {
		try {
			const input = new Input({
				source: new BlobSource(file),
				formats: ALL_FORMATS,
			});

			const videoTrack = await input.getPrimaryVideoTrack();
			if (!videoTrack) return null;

			const canDecode = await videoTrack.canDecode();
			if (!canDecode) return null;

			const sink = new VideoSampleSink(videoTrack);
			const data: SinkData = { sink };
			this.sinks.set(mediaId, data);
			return data;
		} catch (error) {
			console.error(
				`Failed to init thumbnail sink for ${mediaId}:`,
				error,
			);
			return null;
		}
	}
}

export const timelineThumbnailCache = new TimelineThumbnailCache();
