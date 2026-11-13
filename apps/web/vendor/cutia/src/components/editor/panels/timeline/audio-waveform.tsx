import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";

interface AudioWaveformProps {
	audioUrl?: string;
	audioBlob?: Blob;
	audioBuffer?: AudioBuffer;
	duration?: number;
	height?: number;
	volume?: number;
	className?: string;
}

function extractPeaks({
	buffer,
	length = 512,
}: {
	buffer: AudioBuffer;
	length?: number;
}): number[][] {
	const channels = buffer.numberOfChannels;
	const peaks: number[][] = [];

	for (let c = 0; c < channels; c++) {
		const data = buffer.getChannelData(c);
		const step = Math.floor(data.length / length);
		const channelPeaks: number[] = [];

		for (let i = 0; i < length; i++) {
			const start = i * step;
			const end = Math.min(start + step, data.length);
			let max = 0;
			for (let j = start; j < end; j++) {
				const abs = Math.abs(data[j]);
				if (abs > max) max = abs;
			}
			channelPeaks.push(max);
		}
		peaks.push(channelPeaks);
	}

	return peaks;
}

export function AudioWaveform({
	audioUrl,
	audioBlob,
	audioBuffer,
	duration: durationProp,
	height = 32,
	volume = 1,
	className = "",
}: AudioWaveformProps) {
	const waveformRef = useRef<HTMLDivElement>(null);
	const wavesurfer = useRef<WaveSurfer | null>(null);
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState(false);

	useEffect(() => {
		let mounted = true;

		setError(false);
		setIsLoading(true);

		const destroyWaveSurfer = () => {
			const currentWaveSurfer = wavesurfer.current;
			wavesurfer.current = null;

			if (!currentWaveSurfer) return;

			try {
				currentWaveSurfer.destroy();
			} catch {}
		};

		const initWaveSurfer = async () => {
			if (!waveformRef.current || (!audioUrl && !audioBlob && !audioBuffer)) {
				return;
			}

			try {
				destroyWaveSurfer();

				const newWaveSurfer = WaveSurfer.create({
					container: waveformRef.current,
					waveColor: "rgba(255, 255, 255, 0.6)",
					progressColor: "rgba(255, 255, 255, 0.9)",
					cursorColor: "transparent",
					barWidth: 2,
					barGap: 1,
					height,
					normalize: true,
					interact: false,
				});

				if (mounted) {
					wavesurfer.current = newWaveSurfer;
				} else {
					try {
						newWaveSurfer.destroy();
					} catch {}
					return;
				}

				// Prefer buffer/blob loading to avoid media metadata races.
				if (audioBuffer) {
					const peaks = extractPeaks({ buffer: audioBuffer });
					await newWaveSurfer.load("", peaks, audioBuffer.duration);
				} else if (audioBlob) {
					await newWaveSurfer.loadBlob(audioBlob, undefined, durationProp);
				} else if (audioUrl) {
					await newWaveSurfer.load(audioUrl, undefined, durationProp);
				}

				if (mounted) {
					setIsLoading(false);
					setError(false);
				}
			} catch (err) {
				if (mounted) {
					console.error("Failed to initialize WaveSurfer:", err);
					setError(true);
					setIsLoading(false);
				}
			}
		};

		void initWaveSurfer();

		return () => {
			mounted = false;
			destroyWaveSurfer();
		};
	}, [audioUrl, audioBlob, audioBuffer, durationProp, height]);

	if (error) {
		return (
			<div
				className={`flex items-center justify-center ${className}`}
				style={{ height }}
			>
				<span className="text-foreground/60 text-xs">Audio unavailable</span>
			</div>
		);
	}

	const clampedVolume = Math.min(volume, 2);

	return (
		<div className={`relative overflow-hidden ${className}`} style={{ height }}>
			{isLoading && (
				<div className="absolute inset-0 flex items-center justify-center">
					<span className="text-foreground/60 text-xs">Loading...</span>
				</div>
			)}
			<div
				ref={waveformRef}
				className={`w-full transition-transform duration-150 ${isLoading ? "opacity-0" : "opacity-100"}`}
				style={{
					height,
					transform: `scaleY(${clampedVolume})`,
					transformOrigin: "center",
				}}
			/>
		</div>
	);
}

export default AudioWaveform;
