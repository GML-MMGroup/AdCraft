"use client";

import { Textarea } from "@/components/ui/textarea";
import { FontPicker } from "@/components/ui/font-picker";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import type { FontFamily } from "@/constants/font-constants";
import type {
	TextElement,
	TextStroke,
	TextShadow,
	Transform,
} from "@/types/timeline";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useReducer, useRef } from "react";
import { PanelBaseView } from "@/components/editor/panels/panel-base-view";
import {
	PropertyGroup,
	PropertyItem,
	PropertyItemLabel,
	PropertyItemValue,
} from "./property-item";
import { ColorPicker } from "@/components/ui/color-picker";
import { uppercase } from "@/utils/string";
import { clamp } from "@/utils/math";
import { useEditor } from "@/hooks/use-editor";
import { DEFAULT_COLOR } from "@/constants/project-constants";
import { MIN_FONT_SIZE, MAX_FONT_SIZE } from "@/constants/text-constants";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
	TEXT_STYLE_PRESETS,
	type TextStylePreset,
} from "@/constants/text-style-presets";
import { cn } from "@/utils/ui";

interface TextElementRef {
	element: TextElement;
	trackId: string;
}

export function TextProperties({
	elements: elementRefs,
}: {
	elements: TextElementRef[];
}) {
	const element = elementRefs[0].element;

	const { t } = useTranslation();
	const editor = useEditor();
	const containerRef = useRef<HTMLDivElement>(null);
	const [, forceRender] = useReducer((x: number) => x + 1, 0);
	const isEditingFontSize = useRef(false);
	const isEditingOpacity = useRef(false);
	const isEditingContent = useRef(false);
	const isEditingPosX = useRef(false);
	const isEditingPosY = useRef(false);
	const isEditingScale = useRef(false);
	const isEditingRotation = useRef(false);
	const fontSizeDraft = useRef("");
	const opacityDraft = useRef("");
	const contentDraft = useRef("");
	const posXDraft = useRef("");
	const posYDraft = useRef("");
	const scaleDraft = useRef("");
	const rotationDraft = useRef("");

	const buildBatchUpdates = (updates: Partial<Record<string, unknown>>) =>
		elementRefs.map((ref) => ({
			trackId: ref.trackId,
			elementId: ref.element.id,
			updates,
		}));

	const fontSizeDisplay = isEditingFontSize.current
		? fontSizeDraft.current
		: element.fontSize.toString();
	const opacityDisplay = isEditingOpacity.current
		? opacityDraft.current
		: Math.round(element.opacity * 100).toString();
	const contentDisplay = isEditingContent.current
		? contentDraft.current
		: element.content;

	const lastSelectedColor = useRef(DEFAULT_COLOR);
	const initialFontSizeRef = useRef<number | null>(null);
	const initialOpacityRef = useRef<number | null>(null);
	const initialContentRef = useRef<string | null>(null);
	const initialColorRef = useRef<string | null>(null);
	const initialBgColorRef = useRef<string | null>(null);
	const initialPosXRef = useRef<number | null>(null);
	const initialPosYRef = useRef<number | null>(null);
	const initialScaleRef = useRef<number | null>(null);
	const initialRotationRef = useRef<number | null>(null);
	const initialStrokeRef = useRef<TextStroke | null>(null);
	const initialShadowRef = useRef<TextShadow | null>(null);
	const initialStrokeColorRef = useRef<string | null>(null);
	const initialShadowColorRef = useRef<string | null>(null);
	const initialBgOpacityRef = useRef<number | null>(null);
	const initialBgBorderRadiusRef = useRef<number | null>(null);
	const initialBgPaddingXRef = useRef<number | null>(null);
	const initialBgPaddingYRef = useRef<number | null>(null);

	const scalePercent = Math.round(element.transform.scale * 100);
	const posXDisplay = isEditingPosX.current
		? posXDraft.current
		: Math.round(element.transform.position.x).toString();
	const posYDisplay = isEditingPosY.current
		? posYDraft.current
		: Math.round(element.transform.position.y).toString();
	const scaleDisplay = isEditingScale.current
		? scaleDraft.current
		: scalePercent.toString();
	const rotationDisplay = isEditingRotation.current
		? rotationDraft.current
		: Math.round(element.transform.rotate).toString();

	const updateTransform = ({
		updates: transformUpdates,
		pushHistory = true,
	}: {
		updates: Partial<Transform>;
		pushHistory?: boolean;
	}) => {
		editor.timeline.updateElements({
			updates: elementRefs.map((ref) => ({
				trackId: ref.trackId,
				elementId: ref.element.id,
				updates: {
					transform: { ...ref.element.transform, ...transformUpdates },
				},
			})),
			pushHistory,
		});
	};

	const strokeEnabled = !!element.stroke;
	const currentStroke: TextStroke = element.stroke ?? {
		color: "#000000",
		width: 2,
	};
	const shadowEnabled = !!element.shadow;
	const currentShadow: TextShadow = element.shadow ?? {
		color: "#000000",
		offsetX: 2,
		offsetY: 2,
		blur: 4,
	};
	const backgroundEnabled =
		element.backgroundColor !== "transparent" && element.backgroundColor !== "";

	const updateStroke = ({
		stroke,
		pushHistory = true,
	}: {
		stroke: TextStroke | undefined;
		pushHistory?: boolean;
	}) => {
		editor.timeline.updateElements({
			updates: buildBatchUpdates({ stroke }),
			pushHistory,
		});
	};

	const updateShadow = ({
		shadow,
		pushHistory = true,
	}: {
		shadow: TextShadow | undefined;
		pushHistory?: boolean;
	}) => {
		editor.timeline.updateElements({
			updates: buildBatchUpdates({ shadow }),
			pushHistory,
		});
	};

	const handleFontSizeChange = ({ value }: { value: string }) => {
		fontSizeDraft.current = value;
		forceRender();

		if (value.trim() !== "") {
			if (initialFontSizeRef.current === null) {
				initialFontSizeRef.current = element.fontSize;
			}
			const parsed = parseInt(value, 10);
			const fontSize = Number.isNaN(parsed)
				? element.fontSize
				: clamp({ value: parsed, min: MIN_FONT_SIZE, max: MAX_FONT_SIZE });
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ fontSize }),
				pushHistory: false,
			});
		}
	};

	const handleFontSizeBlur = () => {
		if (initialFontSizeRef.current !== null) {
			const parsed = parseInt(fontSizeDraft.current, 10);
			const fontSize = Number.isNaN(parsed)
				? element.fontSize
				: clamp({ value: parsed, min: MIN_FONT_SIZE, max: MAX_FONT_SIZE });
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ fontSize: initialFontSizeRef.current }),
				pushHistory: false,
			});
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ fontSize }),
				pushHistory: true,
			});
			initialFontSizeRef.current = null;
		}
		isEditingFontSize.current = false;
		fontSizeDraft.current = "";
		forceRender();
	};

	const handleOpacityChange = ({ value }: { value: string }) => {
		opacityDraft.current = value;
		forceRender();

		if (value.trim() !== "") {
			if (initialOpacityRef.current === null) {
				initialOpacityRef.current = element.opacity;
			}
			const parsed = parseInt(value, 10);
			const opacityPercent = Number.isNaN(parsed)
				? Math.round(element.opacity * 100)
				: clamp({ value: parsed, min: 0, max: 100 });
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ opacity: opacityPercent / 100 }),
				pushHistory: false,
			});
		}
	};

	const handleOpacityBlur = () => {
		if (initialOpacityRef.current !== null) {
			const parsed = parseInt(opacityDraft.current, 10);
			const opacityPercent = Number.isNaN(parsed)
				? Math.round(element.opacity * 100)
				: clamp({ value: parsed, min: 0, max: 100 });
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ opacity: initialOpacityRef.current }),
				pushHistory: false,
			});
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ opacity: opacityPercent / 100 }),
				pushHistory: true,
			});
			initialOpacityRef.current = null;
		}
		isEditingOpacity.current = false;
		opacityDraft.current = "";
		forceRender();
	};

	const handleColorChange = ({ color }: { color: string }) => {
		if (color !== "transparent") {
			lastSelectedColor.current = color;
		}
		if (initialBgColorRef.current === null) {
			initialBgColorRef.current = element.backgroundColor;
		}
		if (initialBgColorRef.current !== null) {
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ backgroundColor: color }),
				pushHistory: false,
			});
		} else {
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ backgroundColor: color }),
			});
		}
	};

	const handleColorChangeEnd = ({ color }: { color: string }) => {
		if (initialBgColorRef.current !== null) {
			editor.timeline.updateElements({
				updates: buildBatchUpdates({
					backgroundColor: initialBgColorRef.current,
				}),
				pushHistory: false,
			});
			editor.timeline.updateElements({
				updates: buildBatchUpdates({ backgroundColor: `#${color}` }),
				pushHistory: true,
			});
			initialBgColorRef.current = null;
		}
	};

	return (
		<div className="flex h-full flex-col" ref={containerRef}>
			<Tabs defaultValue="style" className="flex h-full flex-col">
				<TabsList className="border-b px-3 py-2">
					<TabsTrigger value="style">{t("Style")}</TabsTrigger>
				</TabsList>
				<TabsContent value="style" className="mt-0 flex-1 overflow-auto">
					<PanelBaseView className="p-0">
						<PropertyGroup
							title={t("Content")}
							hasBorderTop={false}
							collapsible={false}
						>
							<Textarea
								placeholder="Name"
								value={contentDisplay}
								className="bg-accent min-h-20"
								onFocus={() => {
									isEditingContent.current = true;
									contentDraft.current = element.content;
									initialContentRef.current = element.content;
									forceRender();
								}}
								onChange={(event) => {
									contentDraft.current = event.target.value;
									forceRender();
									if (initialContentRef.current === null) {
										initialContentRef.current = element.content;
									}
									editor.timeline.updateElements({
										updates: buildBatchUpdates({
											content: event.target.value,
										}),
										pushHistory: false,
									});
								}}
								onBlur={() => {
									if (initialContentRef.current !== null) {
										const finalContent = contentDraft.current;
										editor.timeline.updateElements({
											updates: buildBatchUpdates({
												content: initialContentRef.current,
											}),
											pushHistory: false,
										});
										editor.timeline.updateElements({
											updates: buildBatchUpdates({
												content: finalContent,
											}),
											pushHistory: true,
										});
										initialContentRef.current = null;
									}
									isEditingContent.current = false;
									contentDraft.current = "";
									forceRender();
								}}
							/>
						</PropertyGroup>
						<PropertyGroup title={t("Typography")} collapsible={false}>
							<div className="space-y-6">
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Font")}</PropertyItemLabel>
									<PropertyItemValue>
										<FontPicker
											defaultValue={element.fontFamily}
											onValueChange={(value: FontFamily) =>
												editor.timeline.updateElements({
													updates: buildBatchUpdates({
														fontFamily: value,
													}),
												})
											}
										/>
									</PropertyItemValue>
								</PropertyItem>
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Style")}</PropertyItemLabel>
									<PropertyItemValue>
										<div className="flex items-center gap-2">
											<Button
												variant={
													element.fontWeight === "bold" ? "default" : "outline"
												}
												size="sm"
												onClick={() =>
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															fontWeight:
																element.fontWeight === "bold"
																	? "normal"
																	: "bold",
														}),
													})
												}
												className="h-8 px-3 font-bold"
											>
												B
											</Button>
											<Button
												variant={
													element.fontStyle === "italic" ? "default" : "outline"
												}
												size="sm"
												onClick={() =>
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															fontStyle:
																element.fontStyle === "italic"
																	? "normal"
																	: "italic",
														}),
													})
												}
												className="h-8 px-3 italic"
											>
												I
											</Button>
											<Button
												variant={
													element.textDecoration === "underline"
														? "default"
														: "outline"
												}
												size="sm"
												onClick={() =>
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															textDecoration:
																element.textDecoration === "underline"
																	? "none"
																	: "underline",
														}),
													})
												}
												className="h-8 px-3 underline"
											>
												U
											</Button>
											<Button
												variant={
													element.textDecoration === "line-through"
														? "default"
														: "outline"
												}
												size="sm"
												onClick={() =>
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															textDecoration:
																element.textDecoration === "line-through"
																	? "none"
																	: "line-through",
														}),
													})
												}
												className="h-8 px-3 line-through"
											>
												S
											</Button>
										</div>
									</PropertyItemValue>
								</PropertyItem>
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Font size")}</PropertyItemLabel>
									<PropertyItemValue>
										<div className="flex items-center gap-2">
											<Slider
												value={[element.fontSize]}
												min={MIN_FONT_SIZE}
												max={MAX_FONT_SIZE}
												step={1}
												onValueChange={([value]) => {
													if (initialFontSizeRef.current === null) {
														initialFontSizeRef.current = element.fontSize;
													}
													editor.timeline.updateElements({
														updates: buildBatchUpdates({ fontSize: value }),
														pushHistory: false,
													});
												}}
												onValueCommit={([value]) => {
													if (initialFontSizeRef.current !== null) {
														editor.timeline.updateElements({
															updates: buildBatchUpdates({
																fontSize: initialFontSizeRef.current,
															}),
															pushHistory: false,
														});
														editor.timeline.updateElements({
															updates: buildBatchUpdates({ fontSize: value }),
															pushHistory: true,
														});
														initialFontSizeRef.current = null;
													}
												}}
												className="w-full"
											/>
											<Input
												type="number"
												value={fontSizeDisplay}
												min={MIN_FONT_SIZE}
												max={MAX_FONT_SIZE}
												onFocus={() => {
													isEditingFontSize.current = true;
													fontSizeDraft.current = element.fontSize.toString();
													forceRender();
												}}
												onChange={(e) =>
													handleFontSizeChange({ value: e.target.value })
												}
												onBlur={handleFontSizeBlur}
												className="bg-accent h-7 w-12 [appearance:textfield] rounded-sm px-2 text-center !text-xs [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
											/>
										</div>
									</PropertyItemValue>
								</PropertyItem>
							</div>
						</PropertyGroup>
						<PropertyGroup title={t("Presets")} collapsible={false}>
							<div className="flex flex-wrap gap-1.5">
								{TEXT_STYLE_PRESETS.map((preset) => (
									<PresetButton
										key={preset.id}
										preset={preset}
										onClick={() => {
											editor.timeline.updateElements({
												updates: buildBatchUpdates(preset.styles),
											});
										}}
									/>
								))}
							</div>
						</PropertyGroup>
						<PropertyGroup title={t("Appearance")} collapsible={false}>
							<div className="space-y-6">
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Color")}</PropertyItemLabel>
									<PropertyItemValue>
										<ColorPicker
											value={uppercase({
												string: (element.color || "FFFFFF").replace("#", ""),
											})}
											onChange={(color) => {
												if (initialColorRef.current === null) {
													initialColorRef.current = element.color || "#FFFFFF";
												}
												if (initialColorRef.current !== null) {
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															color: `#${color}`,
														}),
														pushHistory: false,
													});
												} else {
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															color: `#${color}`,
														}),
													});
												}
											}}
											onChangeEnd={(color) => {
												if (initialColorRef.current !== null) {
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															color: initialColorRef.current,
														}),
														pushHistory: false,
													});
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															color: `#${color}`,
														}),
														pushHistory: true,
													});
													initialColorRef.current = null;
												}
											}}
											containerRef={containerRef}
										/>
									</PropertyItemValue>
								</PropertyItem>
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Opacity")}</PropertyItemLabel>
									<PropertyItemValue>
										<div className="flex items-center gap-2">
											<Slider
												value={[element.opacity * 100]}
												min={0}
												max={100}
												step={1}
												onValueChange={([value]) => {
													if (initialOpacityRef.current === null) {
														initialOpacityRef.current = element.opacity;
													}
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															opacity: value / 100,
														}),
														pushHistory: false,
													});
												}}
												onValueCommit={([value]) => {
													if (initialOpacityRef.current !== null) {
														editor.timeline.updateElements({
															updates: buildBatchUpdates({
																opacity: initialOpacityRef.current,
															}),
															pushHistory: false,
														});
														editor.timeline.updateElements({
															updates: buildBatchUpdates({
																opacity: value / 100,
															}),
															pushHistory: true,
														});
														initialOpacityRef.current = null;
													}
												}}
												className="w-full"
											/>
											<Input
												type="number"
												value={opacityDisplay}
												min={0}
												max={100}
												onFocus={() => {
													isEditingOpacity.current = true;
													opacityDraft.current = Math.round(
														element.opacity * 100,
													).toString();
													forceRender();
												}}
												onChange={(e) =>
													handleOpacityChange({ value: e.target.value })
												}
												onBlur={handleOpacityBlur}
												className="bg-accent h-7 w-12 [appearance:textfield] rounded-sm text-center !text-xs [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
											/>
										</div>
									</PropertyItemValue>
								</PropertyItem>
							</div>
						</PropertyGroup>
						<PropertyGroup
							title={t("Background")}
							defaultExpanded={backgroundEnabled}
						>
							<div className="space-y-6">
								<PropertyItem>
									<PropertyItemLabel>{t("Enable")}</PropertyItemLabel>
									<PropertyItemValue>
										<Switch
											checked={backgroundEnabled}
											onCheckedChange={(checked) => {
												if (checked) {
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															backgroundColor: lastSelectedColor.current,
														}),
													});
												} else {
													editor.timeline.updateElements({
														updates: buildBatchUpdates({
															backgroundColor: "transparent",
														}),
													});
												}
											}}
										/>
									</PropertyItemValue>
								</PropertyItem>
								{backgroundEnabled && (
									<>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Color")}</PropertyItemLabel>
											<PropertyItemValue>
												<ColorPicker
													value={element.backgroundColor.replace("#", "")}
													onChange={(color) =>
														handleColorChange({ color: `#${color}` })
													}
													onChangeEnd={(color) =>
														handleColorChangeEnd({ color })
													}
													containerRef={containerRef}
												/>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Opacity")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[
															Math.round(
																(element.backgroundOpacity ?? 1) * 100,
															),
														]}
														min={0}
														max={100}
														step={1}
														onValueChange={([value]) => {
															if (initialBgOpacityRef.current === null) {
																initialBgOpacityRef.current =
																	element.backgroundOpacity ?? 1;
															}
															editor.timeline.updateElements({
																updates: buildBatchUpdates({
																	backgroundOpacity: value / 100,
																}),
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialBgOpacityRef.current !== null) {
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundOpacity:
																			initialBgOpacityRef.current,
																	}),
																	pushHistory: false,
																});
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundOpacity: value / 100,
																	}),
																	pushHistory: true,
																});
																initialBgOpacityRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{Math.round((element.backgroundOpacity ?? 1) * 100)}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>
												{t("Border Radius")}
											</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[element.backgroundBorderRadius ?? 0]}
														min={0}
														max={50}
														step={1}
														onValueChange={([value]) => {
															if (initialBgBorderRadiusRef.current === null) {
																initialBgBorderRadiusRef.current =
																	element.backgroundBorderRadius ?? 0;
															}
															editor.timeline.updateElements({
																updates: buildBatchUpdates({
																	backgroundBorderRadius: value,
																}),
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialBgBorderRadiusRef.current !== null) {
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundBorderRadius:
																			initialBgBorderRadiusRef.current,
																	}),
																	pushHistory: false,
																});
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundBorderRadius: value,
																	}),
																	pushHistory: true,
																});
																initialBgBorderRadiusRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{element.backgroundBorderRadius ?? 0}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Height")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[element.backgroundPaddingY ?? 4]}
														min={0}
														max={50}
														step={1}
														onValueChange={([value]) => {
															if (initialBgPaddingYRef.current === null) {
																initialBgPaddingYRef.current =
																	element.backgroundPaddingY ?? 4;
															}
															editor.timeline.updateElements({
																updates: buildBatchUpdates({
																	backgroundPaddingY: value,
																}),
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialBgPaddingYRef.current !== null) {
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundPaddingY:
																			initialBgPaddingYRef.current,
																	}),
																	pushHistory: false,
																});
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundPaddingY: value,
																	}),
																	pushHistory: true,
																});
																initialBgPaddingYRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{element.backgroundPaddingY ?? 4}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Width")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[element.backgroundPaddingX ?? 8]}
														min={0}
														max={50}
														step={1}
														onValueChange={([value]) => {
															if (initialBgPaddingXRef.current === null) {
																initialBgPaddingXRef.current =
																	element.backgroundPaddingX ?? 8;
															}
															editor.timeline.updateElements({
																updates: buildBatchUpdates({
																	backgroundPaddingX: value,
																}),
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialBgPaddingXRef.current !== null) {
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundPaddingX:
																			initialBgPaddingXRef.current,
																	}),
																	pushHistory: false,
																});
																editor.timeline.updateElements({
																	updates: buildBatchUpdates({
																		backgroundPaddingX: value,
																	}),
																	pushHistory: true,
																});
																initialBgPaddingXRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{element.backgroundPaddingX ?? 8}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
									</>
								)}
							</div>
						</PropertyGroup>
						<PropertyGroup title={t("Stroke")} defaultExpanded={strokeEnabled}>
							<div className="space-y-6">
								<PropertyItem>
									<PropertyItemLabel>{t("Enable")}</PropertyItemLabel>
									<PropertyItemValue>
										<Switch
											checked={strokeEnabled}
											onCheckedChange={(checked) => {
												updateStroke({
													stroke: checked
														? { color: "#000000", width: 2 }
														: undefined,
												});
											}}
										/>
									</PropertyItemValue>
								</PropertyItem>
								{strokeEnabled && (
									<>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Color")}</PropertyItemLabel>
											<PropertyItemValue>
												<ColorPicker
													value={uppercase({
														string: currentStroke.color.replace("#", ""),
													})}
													onChange={(color) => {
														if (initialStrokeColorRef.current === null) {
															initialStrokeColorRef.current =
																currentStroke.color;
														}
														updateStroke({
															stroke: { ...currentStroke, color: `#${color}` },
															pushHistory: false,
														});
													}}
													onChangeEnd={(color) => {
														if (initialStrokeColorRef.current !== null) {
															updateStroke({
																stroke: {
																	...currentStroke,
																	color: initialStrokeColorRef.current,
																},
																pushHistory: false,
															});
															updateStroke({
																stroke: {
																	...currentStroke,
																	color: `#${color}`,
																},
															});
															initialStrokeColorRef.current = null;
														}
													}}
													containerRef={containerRef}
												/>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Width")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[currentStroke.width]}
														min={1}
														max={20}
														step={1}
														onValueChange={([value]) => {
															if (initialStrokeRef.current === null) {
																initialStrokeRef.current = { ...currentStroke };
															}
															updateStroke({
																stroke: { ...currentStroke, width: value },
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialStrokeRef.current !== null) {
																updateStroke({
																	stroke: initialStrokeRef.current,
																	pushHistory: false,
																});
																updateStroke({
																	stroke: { ...currentStroke, width: value },
																});
																initialStrokeRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{currentStroke.width}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
									</>
								)}
							</div>
						</PropertyGroup>
						<PropertyGroup title={t("Shadow")} defaultExpanded={shadowEnabled}>
							<div className="space-y-6">
								<PropertyItem>
									<PropertyItemLabel>{t("Enable")}</PropertyItemLabel>
									<PropertyItemValue>
										<Switch
											checked={shadowEnabled}
											onCheckedChange={(checked) => {
												updateShadow({
													shadow: checked
														? {
																color: "#000000",
																offsetX: 2,
																offsetY: 2,
																blur: 4,
															}
														: undefined,
												});
											}}
										/>
									</PropertyItemValue>
								</PropertyItem>
								{shadowEnabled && (
									<>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Color")}</PropertyItemLabel>
											<PropertyItemValue>
												<ColorPicker
													value={uppercase({
														string: currentShadow.color.replace("#", ""),
													})}
													onChange={(color) => {
														if (initialShadowColorRef.current === null) {
															initialShadowColorRef.current =
																currentShadow.color;
														}
														updateShadow({
															shadow: { ...currentShadow, color: `#${color}` },
															pushHistory: false,
														});
													}}
													onChangeEnd={(color) => {
														if (initialShadowColorRef.current !== null) {
															updateShadow({
																shadow: {
																	...currentShadow,
																	color: initialShadowColorRef.current,
																},
																pushHistory: false,
															});
															updateShadow({
																shadow: {
																	...currentShadow,
																	color: `#${color}`,
																},
															});
															initialShadowColorRef.current = null;
														}
													}}
													containerRef={containerRef}
												/>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Offset X")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[currentShadow.offsetX]}
														min={-20}
														max={20}
														step={1}
														onValueChange={([value]) => {
															if (initialShadowRef.current === null) {
																initialShadowRef.current = { ...currentShadow };
															}
															updateShadow({
																shadow: { ...currentShadow, offsetX: value },
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialShadowRef.current !== null) {
																updateShadow({
																	shadow: initialShadowRef.current,
																	pushHistory: false,
																});
																updateShadow({
																	shadow: { ...currentShadow, offsetX: value },
																});
																initialShadowRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{currentShadow.offsetX}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Offset Y")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[currentShadow.offsetY]}
														min={-20}
														max={20}
														step={1}
														onValueChange={([value]) => {
															if (initialShadowRef.current === null) {
																initialShadowRef.current = { ...currentShadow };
															}
															updateShadow({
																shadow: { ...currentShadow, offsetY: value },
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialShadowRef.current !== null) {
																updateShadow({
																	shadow: initialShadowRef.current,
																	pushHistory: false,
																});
																updateShadow({
																	shadow: { ...currentShadow, offsetY: value },
																});
																initialShadowRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{currentShadow.offsetY}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
										<PropertyItem direction="column">
											<PropertyItemLabel>{t("Blur")}</PropertyItemLabel>
											<PropertyItemValue>
												<div className="flex items-center gap-2">
													<Slider
														value={[currentShadow.blur]}
														min={0}
														max={30}
														step={1}
														onValueChange={([value]) => {
															if (initialShadowRef.current === null) {
																initialShadowRef.current = { ...currentShadow };
															}
															updateShadow({
																shadow: { ...currentShadow, blur: value },
																pushHistory: false,
															});
														}}
														onValueCommit={([value]) => {
															if (initialShadowRef.current !== null) {
																updateShadow({
																	shadow: initialShadowRef.current,
																	pushHistory: false,
																});
																updateShadow({
																	shadow: { ...currentShadow, blur: value },
																});
																initialShadowRef.current = null;
															}
														}}
														className="w-full"
													/>
													<span className="text-muted-foreground w-8 text-center text-xs">
														{currentShadow.blur}
													</span>
												</div>
											</PropertyItemValue>
										</PropertyItem>
									</>
								)}
							</div>
						</PropertyGroup>
						<PropertyGroup title={t("Transform")}>
							<div className="space-y-6">
								<PropertyItem>
									<PropertyItemLabel>{t("Position X")}</PropertyItemLabel>
									<PropertyItemValue>
										<Input
											type="number"
											value={posXDisplay}
											onFocus={() => {
												isEditingPosX.current = true;
												posXDraft.current = Math.round(
													element.transform.position.x,
												).toString();
												forceRender();
											}}
											onChange={(e) => {
												posXDraft.current = e.target.value;
												forceRender();
												if (initialPosXRef.current === null) {
													initialPosXRef.current = element.transform.position.x;
												}
												const parsed = Number.parseFloat(e.target.value);
												if (!Number.isNaN(parsed)) {
													updateTransform({
														updates: {
															position: {
																...element.transform.position,
																x: parsed,
															},
														},
														pushHistory: false,
													});
												}
											}}
											onBlur={() => {
												if (initialPosXRef.current !== null) {
													const parsed = Number.parseFloat(posXDraft.current);
													const value = Number.isNaN(parsed)
														? element.transform.position.x
														: parsed;
													updateTransform({
														updates: {
															position: {
																...element.transform.position,
																x: initialPosXRef.current,
															},
														},
														pushHistory: false,
													});
													updateTransform({
														updates: {
															position: {
																...element.transform.position,
																x: value,
															},
														},
														pushHistory: true,
													});
													initialPosXRef.current = null;
												}
												isEditingPosX.current = false;
												posXDraft.current = "";
												forceRender();
											}}
											className="bg-accent h-7 w-full [appearance:textfield] rounded-sm px-2 text-center !text-xs [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
										/>
									</PropertyItemValue>
								</PropertyItem>
								<PropertyItem>
									<PropertyItemLabel>{t("Position Y")}</PropertyItemLabel>
									<PropertyItemValue>
										<Input
											type="number"
											value={posYDisplay}
											onFocus={() => {
												isEditingPosY.current = true;
												posYDraft.current = Math.round(
													element.transform.position.y,
												).toString();
												forceRender();
											}}
											onChange={(e) => {
												posYDraft.current = e.target.value;
												forceRender();
												if (initialPosYRef.current === null) {
													initialPosYRef.current = element.transform.position.y;
												}
												const parsed = Number.parseFloat(e.target.value);
												if (!Number.isNaN(parsed)) {
													updateTransform({
														updates: {
															position: {
																...element.transform.position,
																y: parsed,
															},
														},
														pushHistory: false,
													});
												}
											}}
											onBlur={() => {
												if (initialPosYRef.current !== null) {
													const parsed = Number.parseFloat(posYDraft.current);
													const value = Number.isNaN(parsed)
														? element.transform.position.y
														: parsed;
													updateTransform({
														updates: {
															position: {
																...element.transform.position,
																y: initialPosYRef.current,
															},
														},
														pushHistory: false,
													});
													updateTransform({
														updates: {
															position: {
																...element.transform.position,
																y: value,
															},
														},
														pushHistory: true,
													});
													initialPosYRef.current = null;
												}
												isEditingPosY.current = false;
												posYDraft.current = "";
												forceRender();
											}}
											className="bg-accent h-7 w-full [appearance:textfield] rounded-sm px-2 text-center !text-xs [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
										/>
									</PropertyItemValue>
								</PropertyItem>
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Scale")}</PropertyItemLabel>
									<PropertyItemValue>
										<div className="flex items-center gap-2">
											<Slider
												value={[scalePercent]}
												min={10}
												max={500}
												step={1}
												onValueChange={([value]) => {
													if (initialScaleRef.current === null) {
														initialScaleRef.current = element.transform.scale;
													}
													updateTransform({
														updates: { scale: value / 100 },
														pushHistory: false,
													});
												}}
												onValueCommit={([value]) => {
													if (initialScaleRef.current !== null) {
														updateTransform({
															updates: { scale: initialScaleRef.current },
															pushHistory: false,
														});
														updateTransform({
															updates: { scale: value / 100 },
															pushHistory: true,
														});
														initialScaleRef.current = null;
													}
												}}
												className="w-full"
											/>
											<Input
												type="number"
												value={scaleDisplay}
												min={10}
												max={500}
												onFocus={() => {
													isEditingScale.current = true;
													scaleDraft.current = scalePercent.toString();
													forceRender();
												}}
												onChange={(e) => {
													scaleDraft.current = e.target.value;
													forceRender();
													if (initialScaleRef.current === null) {
														initialScaleRef.current = element.transform.scale;
													}
													const parsed = parseInt(e.target.value, 10);
													if (!Number.isNaN(parsed)) {
														const clamped = clamp({
															value: parsed,
															min: 10,
															max: 500,
														});
														updateTransform({
															updates: { scale: clamped / 100 },
															pushHistory: false,
														});
													}
												}}
												onBlur={() => {
													if (initialScaleRef.current !== null) {
														const parsed = parseInt(scaleDraft.current, 10);
														const clamped = Number.isNaN(parsed)
															? scalePercent
															: clamp({ value: parsed, min: 10, max: 500 });
														updateTransform({
															updates: { scale: initialScaleRef.current },
															pushHistory: false,
														});
														updateTransform({
															updates: { scale: clamped / 100 },
															pushHistory: true,
														});
														initialScaleRef.current = null;
													}
													isEditingScale.current = false;
													scaleDraft.current = "";
													forceRender();
												}}
												className="bg-accent h-7 w-14 [appearance:textfield] rounded-sm px-2 text-center !text-xs [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
											/>
										</div>
									</PropertyItemValue>
								</PropertyItem>
								<PropertyItem direction="column">
									<PropertyItemLabel>{t("Rotation")}</PropertyItemLabel>
									<PropertyItemValue>
										<div className="flex items-center gap-2">
											<Slider
												value={[element.transform.rotate]}
												min={-180}
												max={180}
												step={1}
												onValueChange={([value]) => {
													if (initialRotationRef.current === null) {
														initialRotationRef.current =
															element.transform.rotate;
													}
													updateTransform({
														updates: { rotate: value },
														pushHistory: false,
													});
												}}
												onValueCommit={([value]) => {
													if (initialRotationRef.current !== null) {
														updateTransform({
															updates: {
																rotate: initialRotationRef.current,
															},
															pushHistory: false,
														});
														updateTransform({
															updates: { rotate: value },
															pushHistory: true,
														});
														initialRotationRef.current = null;
													}
												}}
												className="w-full"
											/>
											<Input
												type="number"
												value={rotationDisplay}
												min={-360}
												max={360}
												onFocus={() => {
													isEditingRotation.current = true;
													rotationDraft.current = Math.round(
														element.transform.rotate,
													).toString();
													forceRender();
												}}
												onChange={(e) => {
													rotationDraft.current = e.target.value;
													forceRender();
													if (initialRotationRef.current === null) {
														initialRotationRef.current =
															element.transform.rotate;
													}
													const parsed = Number.parseFloat(e.target.value);
													if (!Number.isNaN(parsed)) {
														updateTransform({
															updates: { rotate: parsed },
															pushHistory: false,
														});
													}
												}}
												onBlur={() => {
													if (initialRotationRef.current !== null) {
														const parsed = Number.parseFloat(
															rotationDraft.current,
														);
														const value = Number.isNaN(parsed)
															? element.transform.rotate
															: parsed;
														updateTransform({
															updates: {
																rotate: initialRotationRef.current,
															},
															pushHistory: false,
														});
														updateTransform({
															updates: { rotate: value },
															pushHistory: true,
														});
														initialRotationRef.current = null;
													}
													isEditingRotation.current = false;
													rotationDraft.current = "";
													forceRender();
												}}
												className="bg-accent h-7 w-14 [appearance:textfield] rounded-sm px-2 text-center !text-xs [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
											/>
										</div>
									</PropertyItemValue>
								</PropertyItem>
							</div>
						</PropertyGroup>
					</PanelBaseView>
				</TabsContent>
			</Tabs>
		</div>
	);
}

function PresetButton({
	preset,
	onClick,
}: {
	preset: TextStylePreset;
	onClick: () => void;
}) {
	const { preview } = preset;
	const isClearAll = preset.id === "clear-all";

	const previewStyle: React.CSSProperties = isClearAll
		? {}
		: {
				color: preview.color,
				backgroundColor: preview.backgroundColor,
				fontWeight: preview.fontWeight ?? "bold",
				WebkitTextStroke: preview.stroke
					? `${Math.max(preview.stroke.width * 0.5, 0.5)}px ${preview.stroke.color}`
					: undefined,
				textShadow: preview.shadow
					? `${preview.shadow.offsetX}px ${preview.shadow.offsetY}px ${preview.shadow.blur}px ${preview.shadow.color}`
					: undefined,
			};

	const hasBg = !isClearAll && !!preview.backgroundColor;

	return (
		<button
			type="button"
			title={preset.name}
			className={cn(
				"flex size-10 cursor-pointer items-center justify-center rounded-md border text-lg font-bold transition-colors select-none",
				"hover:border-primary/50 hover:bg-accent/80",
				isClearAll && "relative overflow-hidden",
			)}
			style={{
				backgroundColor: hasBg ? undefined : "rgba(0,0,0,0.6)",
			}}
			onClick={onClick}
			onKeyDown={(event) => {
				if (event.key === "Enter" || event.key === " ") {
					onClick();
				}
			}}
		>
			{isClearAll ? (
				<svg
					width="22"
					height="22"
					viewBox="0 0 22 22"
					fill="none"
					className="text-muted-foreground"
				>
					<title>Clear All</title>
					<circle
						cx="11"
						cy="11"
						r="9"
						stroke="currentColor"
						strokeWidth="1.5"
					/>
					<line
						x1="4.5"
						y1="17.5"
						x2="17.5"
						y2="4.5"
						stroke="currentColor"
						strokeWidth="1.5"
					/>
				</svg>
			) : (
				<span
					style={previewStyle}
					className={cn("leading-none", hasBg && "rounded px-1 py-0.5")}
				>
					T
				</span>
			)}
		</button>
	);
}
