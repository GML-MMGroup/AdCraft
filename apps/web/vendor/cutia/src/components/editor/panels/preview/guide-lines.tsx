import type { SnapGuide } from "@/lib/preview/snap";

const GUIDE_COLOR = "var(--primary)";

export function GuideLines({
	guides,
	displaySize,
	canvasWidth,
	canvasHeight,
}: {
	guides: SnapGuide[];
	displaySize: { width: number; height: number };
	canvasWidth: number;
	canvasHeight: number;
}) {
	if (guides.length === 0 || canvasWidth === 0 || canvasHeight === 0) {
		return null;
	}

	const scaleX = displaySize.width / canvasWidth;
	const scaleY = displaySize.height / canvasHeight;

	return (
		<svg
			className="pointer-events-none absolute inset-0"
			width={displaySize.width}
			height={displaySize.height}
			style={{ zIndex: 999 }}
		>
			<title>Alignment guides</title>
			{guides.map((guide) => {
				const key = `${guide.orientation}-${guide.type}-${guide.position}`;

				if (guide.orientation === "vertical") {
					const x = guide.position * scaleX;
					return (
						<line
							key={key}
							x1={x}
							y1={0}
							x2={x}
							y2={displaySize.height}
							stroke={GUIDE_COLOR}
							strokeWidth={1}
							opacity={0.8}
						/>
					);
				}

				const y = guide.position * scaleY;
				return (
					<line
						key={key}
						x1={0}
						y1={y}
						x2={displaySize.width}
						y2={y}
						stroke={GUIDE_COLOR}
						strokeWidth={1}
						opacity={0.8}
					/>
				);
			})}
		</svg>
	);
}
