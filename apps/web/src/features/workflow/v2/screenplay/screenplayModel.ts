import type {
  V2EditableScriptCharacter,
  V2EditableScriptDialogue,
  V2EditableScriptDocument,
  V2EditableScriptLocation,
  V2EditableScriptScene,
  V2EditableScriptShot,
  V2ScriptAspectRatio,
  V2ScriptPlan,
} from "../../../../types-v2.ts";

const supportedAspectRatios = new Set<V2ScriptAspectRatio>(["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"]);

let nextClientKey = 0;

export interface EditableScriptValidationIssue {
  path: string;
  message: string;
}

export function scriptToEditableDocument(script: V2ScriptPlan): V2EditableScriptDocument {
  const shotsByScene = new Map<string, V2EditableScriptShot[]>();

  for (const shot of [...script.shots].sort((left, right) => left.shot_index - right.shot_index)) {
    const editableShot: V2EditableScriptShot = {
      shot_id: shot.shot_id,
      product_ids: [...shot.product_ids],
      character_ids: [...shot.character_ids],
      scene_ids: [...shot.scene_ids],
      description: shot.description,
      dialogue: shot.dialogue.map((line) => ({
        dialogue_id: line.dialogue_id,
        character_id: line.character_id,
        performance_cue: line.performance_cue,
        text: line.text,
      })),
      narration: shot.narration,
      visual_prompt: shot.visual_prompt,
      duration_seconds: shot.duration_seconds,
    };
    const sceneShots = shotsByScene.get(shot.scene_id) ?? [];
    sceneShots.push(editableShot);
    shotsByScene.set(shot.scene_id, sceneShots);
  }

  return {
    script_title: script.script_title,
    language: script.language,
    characters: script.characters.map(toEditableCharacter),
    locations: script.locations.map(toEditableLocation),
    scenes: script.scenes.map((scene) => ({
      scene_id: scene.scene_id,
      title: scene.title,
      description: scene.description,
      location_id: scene.location_id,
      location_type: scene.location_type,
      time_of_day: scene.time_of_day,
      setting_type: scene.setting_type,
      shots: shotsByScene.get(scene.scene_id) ?? [],
    })),
    product_beats: [...script.product_beats],
    tone: script.tone,
    visual_style: script.visual_style,
    aspect_ratio: script.aspect_ratio,
  };
}

export function createEditableScene(): V2EditableScriptScene {
  return {
    client_key: createClientKey("scene"),
    title: "New scene",
    description: "Describe the scene.",
    shots: [],
  };
}

export function createEditableShot(sceneId: string): V2EditableScriptShot {
  return {
    client_key: createClientKey("shot"),
    product_ids: [],
    character_ids: [],
    scene_ids: [sceneId],
    description: "Describe the shot.",
    dialogue: [],
    narration: null,
    visual_prompt: "Describe the visual.",
    duration_seconds: 1,
  };
}

export function createEditableDialogue(characterId: string): V2EditableScriptDialogue {
  return {
    client_key: createClientKey("dialogue"),
    character_id: characterId,
    performance_cue: null,
    text: "Add dialogue.",
  };
}

export function reorderItem<T>(items: T[], from: number, to: number): T[] {
  if (!isArrayIndex(from, items.length) || !isArrayIndex(to, items.length) || from === to) {
    return items;
  }

  const reordered = [...items];
  const [item] = reordered.splice(from, 1);
  reordered.splice(to, 0, item);
  return reordered;
}

export function validateEditableScript(document: V2EditableScriptDocument): EditableScriptValidationIssue[] {
  const issues: EditableScriptValidationIssue[] = [];
  const characters = document.characters ?? [];
  const locations = document.locations ?? [];
  const scenes = document.scenes ?? [];

  validateRequiredText(issues, "script_title", document.script_title);
  validateRequiredText(issues, "language", document.language);
  validateRequiredText(issues, "tone", document.tone);
  validateRequiredText(issues, "visual_style", document.visual_style);
  if (!supportedAspectRatios.has(document.aspect_ratio)) {
    addIssue(issues, "aspect_ratio", "Choose a supported aspect ratio.");
  }

  const characterIds = collectEntityIds(issues, characters, "character", "character_id", "characters");
  const locationIds = collectEntityIds(issues, locations, "location", "location_id", "locations");
  const sceneIds = collectEntityIds(issues, scenes, "scene", "scene_id", "scenes");

  characters.forEach((character, index) => {
    validateRequiredText(issues, `characters.${index}.display_name`, character.display_name);
    validateRequiredText(issues, `characters.${index}.description`, character.description);
    validateRequiredText(issues, `characters.${index}.role`, character.role);
    validateRequiredText(issues, `characters.${index}.visual_notes`, character.visual_notes);
  });
  locations.forEach((location, index) => {
    validateRequiredText(issues, `locations.${index}.display_name`, location.display_name);
    validateRequiredText(issues, `locations.${index}.description`, location.description);
    validateRequiredText(issues, `locations.${index}.visual_notes`, location.visual_notes);
    validateSettingType(issues, `locations.${index}.setting_type`, location.setting_type);
  });

  if (scenes.length === 0) {
    addIssue(issues, "scenes", "Add at least one scene.");
  }

  const shotIdentities: Array<{ item: V2EditableScriptShot; path: string }> = [];
  const dialogueIdentities: Array<{ item: V2EditableScriptDialogue; path: string }> = [];
  scenes.forEach((scene, sceneIndex) => {
    const scenePath = `scenes.${sceneIndex}`;
    validateRequiredText(issues, `${scenePath}.title`, scene.title);
    validateRequiredText(issues, `${scenePath}.description`, scene.description);
    validateSettingType(issues, `${scenePath}.setting_type`, scene.setting_type);
    validateOptionalReference(issues, `${scenePath}.location_id`, scene.location_id, locationIds, "location");

    if (scene.shots.length === 0) {
      addIssue(issues, `${scenePath}.shots`, "Add at least one shot to this scene.");
    }
    scene.shots.forEach((shot, shotIndex) => {
      const shotPath = `${scenePath}.shots.${shotIndex}`;
      shotIdentities.push({ item: shot, path: shotPath });
      validateRequiredText(issues, `${shotPath}.description`, shot.description);
      validateRequiredText(issues, `${shotPath}.visual_prompt`, shot.visual_prompt);
      if (!isPositiveInteger(shot.duration_seconds)) {
        addIssue(issues, `${shotPath}.duration_seconds`, "Enter a positive whole-number duration.");
      }
      validateReferenceList(issues, `${shotPath}.product_ids`, shot.product_ids ?? [], undefined, "product");
      validateReferenceList(issues, `${shotPath}.character_ids`, shot.character_ids ?? [], characterIds, "character");
      validateReferenceList(issues, `${shotPath}.scene_ids`, shot.scene_ids ?? [], sceneIds, "scene");

      (shot.dialogue ?? []).forEach((dialogue, dialogueIndex) => {
        const dialoguePath = `${shotPath}.dialogue.${dialogueIndex}`;
        dialogueIdentities.push({ item: dialogue, path: dialoguePath });
        validateRequiredReference(issues, `${dialoguePath}.character_id`, dialogue.character_id, characterIds, "character");
        validateRequiredText(issues, `${dialoguePath}.text`, dialogue.text);
      });
    });
  });

  collectNestedEntityIds(issues, shotIdentities, "shot", "shot_id");
  collectNestedEntityIds(issues, dialogueIdentities, "dialogue", "dialogue_id");
  return issues;
}

function toEditableCharacter(character: V2ScriptPlan["characters"][number]): V2EditableScriptCharacter {
  return {
    character_id: character.character_id,
    display_name: character.display_name,
    description: character.description,
    role: character.role,
    visual_notes: character.visual_notes,
    gender: character.gender,
  };
}

function toEditableLocation(location: V2ScriptPlan["locations"][number]): V2EditableScriptLocation {
  return {
    location_id: location.location_id,
    display_name: location.display_name,
    description: location.description,
    visual_notes: location.visual_notes,
    location_type: location.location_type,
    time_of_day: location.time_of_day,
    setting_type: location.setting_type,
  };
}

function createClientKey(namespace: string): string {
  nextClientKey += 1;
  return `${namespace}-client-${nextClientKey}`;
}

function isArrayIndex(value: number, length: number): boolean {
  return Number.isInteger(value) && value >= 0 && value < length;
}

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

function validateRequiredText(issues: EditableScriptValidationIssue[], path: string, value: string | null | undefined): void {
  if (!value?.trim()) {
    addIssue(issues, path, "This field is required.");
  }
}

function validateSettingType(
  issues: EditableScriptValidationIssue[],
  path: string,
  value: "interior" | "exterior" | null | undefined,
): void {
  if (value != null && value !== "interior" && value !== "exterior") {
    addIssue(issues, path, "Choose interior or exterior.");
  }
}

function collectEntityIds<
  T extends { client_key?: string | null },
  IdField extends keyof T,
>(
  issues: EditableScriptValidationIssue[],
  items: T[],
  namespace: string,
  idField: IdField,
  collectionPath: string,
): Set<string> {
  const identities = new Set<string>();
  items.forEach((item, index) => {
    const identity = validateEntityIdentity(issues, `${collectionPath}.${index}`, namespace, item[idField], item.client_key);
    if (identity) {
      if (identities.has(identity)) {
        addIssue(issues, `${collectionPath}.${index}.${String(idField)}`, `Duplicate ${namespace} identity.`);
      }
      identities.add(identity);
    }
  });
  return identities;
}

function collectNestedEntityIds<
  T extends { client_key?: string | null },
  IdField extends keyof T,
>(
  issues: EditableScriptValidationIssue[],
  items: Array<{ item: T; path: string }>,
  namespace: string,
  idField: IdField,
): void {
  const identities = new Set<string>();
  items.forEach(({ item, path }) => {
    const identity = validateEntityIdentity(issues, path, namespace, item[idField], item.client_key);
    if (identity) {
      if (identities.has(identity)) {
        addIssue(issues, `${path}.${String(idField)}`, `Duplicate ${namespace} identity.`);
      }
      identities.add(identity);
    }
  });
}

function validateEntityIdentity(
  issues: EditableScriptValidationIssue[],
  path: string,
  namespace: string,
  canonicalId: unknown,
  clientKey: unknown,
): string | null {
  const canonical = normalizeId(canonicalId);
  const client = normalizeId(clientKey);
  if (canonical && client) {
    addIssue(issues, `${path}.client_key`, `A retained ${namespace} cannot also have a client key.`);
    return canonical;
  }
  if (!canonical && !client) {
    addIssue(issues, `${path}.${namespace}_id`, `Provide a canonical ${namespace} ID or client key.`);
    return null;
  }
  return canonical ?? client;
}

function validateReferenceList(
  issues: EditableScriptValidationIssue[],
  path: string,
  values: string[],
  availableIds: Set<string> | undefined,
  label: string,
): void {
  const seen = new Set<string>();
  values.forEach((value, index) => {
    const referencePath = `${path}.${index}`;
    const normalized = normalizeId(value);
    if (!normalized) {
      addIssue(issues, referencePath, `Choose a ${label} reference.`);
      return;
    }
    if (seen.has(normalized)) {
      addIssue(issues, referencePath, `Duplicate ${label} reference.`);
      return;
    }
    seen.add(normalized);
    if (availableIds && !availableIds.has(normalized)) {
      addIssue(issues, referencePath, `Select an active ${label}.`);
    }
  });
}

function validateOptionalReference(
  issues: EditableScriptValidationIssue[],
  path: string,
  value: string | null | undefined,
  availableIds: Set<string>,
  label: string,
): void {
  if (value == null) {
    return;
  }
  validateRequiredReference(issues, path, value, availableIds, label);
}

function validateRequiredReference(
  issues: EditableScriptValidationIssue[],
  path: string,
  value: string,
  availableIds: Set<string>,
  label: string,
): void {
  const normalized = normalizeId(value);
  if (!normalized || !availableIds.has(normalized)) {
    addIssue(issues, path, `Select an active ${label}.`);
  }
}

function normalizeId(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function addIssue(issues: EditableScriptValidationIssue[], path: string, message: string): void {
  issues.push({ path, message });
}
