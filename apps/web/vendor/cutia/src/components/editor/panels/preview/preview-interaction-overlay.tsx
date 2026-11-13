import { useRef } from "react";
import { usePreviewInteraction } from "@/hooks/use-preview-interaction";
import { SelectionOverlay } from "./selection-overlay";
import { GuideLines } from "./guide-lines";

export function PreviewInteractionOverlay({
	canvasRef,
	displaySize,
}: {
	canvasRef: React.RefObject<HTMLCanvasElement | null>;
	displaySize: { width: number; height: number };
}) {
	const overlayRef = useRef<HTMLDivElement>(null);
	const {
		onPointerDown,
		onPointerMove,
		onPointerUp,
		onScaleStart,
		onResizeStart,
		isTransforming,
		activeGuides,
	} = usePreviewInteraction({ canvasRef, overlayRef });

	const canvasWidth = canvasRef.current?.width ?? 0;
	const canvasHeight = canvasRef.current?.height ?? 0;

	return (
		<div
			ref={overlayRef}
			className="pointer-events-auto absolute inset-0"
			onPointerDown={onPointerDown}
			onPointerMove={onPointerMove}
			onPointerUp={onPointerUp}
		>
			<GuideLines
				guides={activeGuides}
				displaySize={displaySize}
				canvasWidth={canvasWidth}
				canvasHeight={canvasHeight}
			/>
			<SelectionOverlay
				displaySize={displaySize}
				onScaleStart={onScaleStart}
				onResizeStart={onResizeStart}
				isTransforming={isTransforming}
			/>
		</div>
	);
}
