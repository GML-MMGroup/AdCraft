const MIME_TYPE_MAP: Record<string, string> = {
	mp4: "video/mp4",
	webm: "video/webm",
	mov: "video/quicktime",
	avi: "video/x-msvideo",
	mkv: "video/x-matroska",
	mp3: "audio/mpeg",
	wav: "audio/wav",
	ogg: "audio/ogg",
	flac: "audio/flac",
	aac: "audio/aac",
	png: "image/png",
	jpg: "image/jpeg",
	jpeg: "image/jpeg",
	gif: "image/gif",
	webp: "image/webp",
	svg: "image/svg+xml",
	bmp: "image/bmp",
};

function guessContentType({ url }: { url: string }): string {
	try {
		const pathname = new URL(url).pathname;
		const extension = pathname.split(".").pop()?.toLowerCase() ?? "";
		return MIME_TYPE_MAP[extension] ?? "application/octet-stream";
	} catch {
		return "application/octet-stream";
	}
}

function extractFilename({ url }: { url: string }): string {
	try {
		const pathname = new URL(url).pathname;
		const segments = pathname.split("/").filter(Boolean);
		const lastSegment = segments.at(-1);
		if (lastSegment?.includes(".")) {
			return decodeURIComponent(lastSegment);
		}
	} catch {
		// fall through to default
	}

	const timestamp = Date.now();
	return `imported-media-${timestamp}`;
}

export async function fetchWithProxyFallback({
	url,
}: {
	url: string;
}): Promise<Blob> {
	try {
		const directResponse = await fetch(url);
		if (!directResponse.ok) {
			throw new Error(`Direct fetch failed: ${directResponse.status}`);
		}
		return await directResponse.blob();
	} catch {
		const proxyUrl = `/api/proxy/download?url=${encodeURIComponent(url)}`;
		const proxyResponse = await fetch(proxyUrl);
		if (!proxyResponse.ok) {
			throw new Error(
				`Failed to fetch: ${proxyResponse.status} ${proxyResponse.statusText}`,
			);
		}
		return await proxyResponse.blob();
	}
}

export async function fetchRemoteMediaAsFile({
	url,
}: {
	url: string;
}): Promise<File> {
	const blob = await fetchWithProxyFallback({ url });
	const contentType =
		blob.type && blob.type !== "application/octet-stream"
			? blob.type
			: guessContentType({ url });
	const filename = extractFilename({ url });

	return new File([blob], filename, { type: contentType });
}
