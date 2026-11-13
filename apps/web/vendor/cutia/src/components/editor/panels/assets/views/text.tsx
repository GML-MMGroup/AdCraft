import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { DraggableItem } from "@/components/editor/panels/assets/draggable-item";
import { PanelBaseView as BaseView } from "@/components/editor/panels/panel-base-view";
import { useEditor } from "@/hooks/use-editor";
import { DEFAULT_TEXT_ELEMENT } from "@/constants/text-constants";
import { buildTextElement } from "@/lib/timeline/element-utils";

export function TextView() {
	const { t } = useTranslation();
	const editor = useEditor();

	const handleAddDefaultText = ({
		currentTime,
	}: {
		currentTime: number;
	}) => {
		const activeScene = editor.scenes.getActiveScene();
		if (!activeScene) return;

		const element = buildTextElement({
			raw: DEFAULT_TEXT_ELEMENT,
			startTime: currentTime,
		});

		editor.timeline.insertElement({
			element,
			placement: { mode: "auto" },
		});
	};

	return (
		<BaseView>
			<div className="space-y-3">
				<DraggableItem
					name={t("Default text")}
					preview={
						<div className="bg-accent flex size-full items-center justify-center rounded">
							<span className="text-xs select-none">{t("Default text")}</span>
						</div>
					}
					dragData={{
						id: "temp-text-id",
						type: DEFAULT_TEXT_ELEMENT.type,
						name: DEFAULT_TEXT_ELEMENT.name,
						content: DEFAULT_TEXT_ELEMENT.content,
					}}
					aspectRatio={1}
					onAddToTimeline={handleAddDefaultText}
					shouldShowLabel={false}
				/>
			</div>
		</BaseView>
	);
}
