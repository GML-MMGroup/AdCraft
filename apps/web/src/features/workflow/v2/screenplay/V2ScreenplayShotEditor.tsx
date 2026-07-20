import { ChevronDownIcon, ChevronUpIcon, PlusIcon, TrashIcon } from "../../../../icons.tsx";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  V2EditableScriptDialogue,
  V2EditableScriptDocument,
  V2EditableScriptShot,
} from "../../../../types-v2.ts";
import { createEditableDialogue, createEditableShot, reorderItem } from "./screenplayModel.ts";
import { draftDurationValue, mergeProductOptions, parsePositiveDuration, type ScreenplayProductOption } from "./screenplayUiHelpers.ts";

type Props = {
  document: V2EditableScriptDocument;
  sceneIndex: number;
  validationErrors: ReadonlyArray<{ path: string; message: string }>;
  onChange: (update: (document: V2EditableScriptDocument) => V2EditableScriptDocument) => void;
  productOptions?: readonly ScreenplayProductOption[];
};

export function V2ScreenplayShotEditor({ document, sceneIndex, validationErrors, onChange, productOptions = [] }: Props) {
  const scene = document.scenes[sceneIndex];
  if (!scene) return null;
  const sceneIdentity = entityId(scene);
  const characterOptions = (document.characters ?? []).map((character) => ({ value: entityId(character), label: character.display_name || "Untitled character" }));
  const sceneOptions = document.scenes.map((entry) => ({ value: entityId(entry), label: entry.title || "Untitled scene" }));
  const availableProductOptions = mergeProductOptions(productOptions, document.scenes.flatMap((entry) => entry.shots.flatMap((shot) => shot.product_ids ?? [])));

  const changeShot = (shotIndex: number, update: (shot: V2EditableScriptShot) => void) => onChange((next) => {
    const shot = next.scenes[sceneIndex]?.shots[shotIndex];
    if (shot) update(shot);
    return next;
  });

  const moveShot = (from: number, to: number) => onChange((next) => {
    const target = next.scenes[sceneIndex];
    if (target) target.shots = reorderItem(target.shots, from, to);
    return next;
  });

  const removeShot = (shotIndex: number) => onChange((next) => {
    const target = next.scenes[sceneIndex];
    if (target) target.shots.splice(shotIndex, 1);
    return next;
  });

  const addShot = () => onChange((next) => {
    const target = next.scenes[sceneIndex];
    if (target) target.shots.push(createEditableShot(entityId(target)));
    return next;
  });

  return (
    <section className="v2-screenplay-shots" aria-label={`Shots for ${scene.title || "scene"}`}>
      <div className="v2-screenplay-section-heading">
        <h4>Shots</h4>
        <button className="v2-screenplay-add" type="button" onClick={addShot}>
          <PlusIcon /> Add shot
        </button>
      </div>
      {scene.shots.length === 0 ? <p className="v2-screenplay-empty">No shots yet.{errorAt(validationErrors, `scenes.${sceneIndex}.shots`) ? <em>{errorAt(validationErrors, `scenes.${sceneIndex}.shots`)}</em> : null}</p> : null}
      {scene.shots.map((shot, shotIndex) => {
        const path = `scenes.${sceneIndex}.shots.${shotIndex}`;
        return (
          <article className="v2-screenplay-shot" key={entityId(shot)}>
            <div className="v2-screenplay-item-heading">
              <strong>Shot {shotIndex + 1}</strong>
              <IconActions
                prefix="shot"
                index={shotIndex}
                count={scene.shots.length}
                onMove={moveShot}
                onRemove={() => removeShot(shotIndex)}
              />
            </div>
            <div className="v2-screenplay-fields">
              <Field label="Shot description / action" error={errorAt(validationErrors, `${path}.description`)}>
                <textarea value={shot.description} onChange={(event) => changeShot(shotIndex, (next) => { next.description = event.target.value; })} />
              </Field>
              <Field label="Visual prompt" error={errorAt(validationErrors, `${path}.visual_prompt`)}>
                <textarea value={shot.visual_prompt} onChange={(event) => changeShot(shotIndex, (next) => { next.visual_prompt = event.target.value; })} />
              </Field>
              <DurationField value={shot.duration_seconds} error={errorAt(validationErrors, `${path}.duration_seconds`)} onCommit={(duration) => changeShot(shotIndex, (next) => { next.duration_seconds = duration; })} />
              <Field label="Narration">
                <textarea value={shot.narration ?? ""} onChange={(event) => changeShot(shotIndex, (next) => { next.narration = event.target.value || null; })} />
              </Field>
              <ReferenceSelect label="Product references" options={availableProductOptions.map((option) => ({ value: option.id, label: option.label ?? option.id }))} value={shot.product_ids ?? []} onChange={(values) => changeShot(shotIndex, (next) => { next.product_ids = values; })} />
              <ReferenceSelect label="Character references" options={characterOptions} value={shot.character_ids ?? []} error={errorAt(validationErrors, `${path}.character_ids`)} onChange={(values) => changeShot(shotIndex, (next) => { next.character_ids = values; })} />
              <ReferenceSelect label="Scene references" options={sceneOptions} value={shot.scene_ids ?? [sceneIdentity]} error={errorAt(validationErrors, `${path}.scene_ids`)} onChange={(values) => changeShot(shotIndex, (next) => { next.scene_ids = values; })} />
            </div>
            <DialogueEditor
              dialogue={shot.dialogue ?? []}
              characterOptions={characterOptions}
              validationErrors={validationErrors}
              path={path}
              onChange={(update) => changeShot(shotIndex, (next) => { next.dialogue = update(next.dialogue ?? []); })}
            />
          </article>
        );
      })}
    </section>
  );
}

function DialogueEditor({ dialogue, characterOptions, validationErrors, path, onChange }: {
  dialogue: V2EditableScriptDialogue[];
  characterOptions: Array<{ value: string; label: string }>;
  validationErrors: ReadonlyArray<{ path: string; message: string }>;
  path: string;
  onChange: (update: (dialogue: V2EditableScriptDialogue[]) => V2EditableScriptDialogue[]) => void;
}) {
  return <section className="v2-screenplay-dialogue">
    <div className="v2-screenplay-section-heading">
      <h5>Dialogue</h5>
      <button className="v2-screenplay-add" type="button" disabled={!characterOptions.length} onClick={() => onChange((items) => [...items, createEditableDialogue(characterOptions[0].value)])}>
        <PlusIcon /> Add dialogue
      </button>
    </div>
    {!characterOptions.length ? <p className="v2-screenplay-hint">Add a character before adding dialogue.</p> : null}
    {dialogue.map((line, dialogueIndex) => <div className="v2-screenplay-dialogue-line" key={entityId(line)}>
      <div className="v2-screenplay-item-heading">
        <strong>Line {dialogueIndex + 1}</strong>
        <IconActions prefix="dialogue" index={dialogueIndex} count={dialogue.length} onMove={(from, to) => onChange((items) => reorderItem(items, from, to))} onRemove={() => onChange((items) => items.filter((_, index) => index !== dialogueIndex))} />
      </div>
      <div className="v2-screenplay-fields v2-screenplay-fields--compact">
        <Field label="Character" error={errorAt(validationErrors, `${path}.dialogue.${dialogueIndex}.character_id`)}>
          <select value={line.character_id} onChange={(event) => onChange((items) => updateDialogue(items, dialogueIndex, (next) => { next.character_id = event.target.value; }))}>
            <option value="">Choose character</option>
            {characterOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </Field>
        <Field label="Performance cue">
          <input value={line.performance_cue ?? ""} onChange={(event) => onChange((items) => updateDialogue(items, dialogueIndex, (next) => { next.performance_cue = event.target.value || null; }))} />
        </Field>
        <Field label="Text" error={errorAt(validationErrors, `${path}.dialogue.${dialogueIndex}.text`)}>
          <textarea value={line.text} onChange={(event) => onChange((items) => updateDialogue(items, dialogueIndex, (next) => { next.text = event.target.value; }))} />
        </Field>
      </div>
    </div>)}
  </section>;
}

function updateDialogue(items: V2EditableScriptDialogue[], index: number, update: (item: V2EditableScriptDialogue) => void) {
  const next = [...items];
  if (next[index]) update(next[index]);
  return next;
}

function ReferenceSelect({ label, options, value, error, onChange }: { label: string; options: Array<{ value: string; label: string }>; value: string[]; error?: string; onChange: (value: string[]) => void }) {
  return <Field label={label} error={error}>
    <select multiple value={value} onChange={(event) => onChange([...event.currentTarget.selectedOptions].map((option) => option.value))}>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  </Field>;
}

function DurationField({ value, error, onCommit }: { value: number; error?: string; onCommit: (value: number) => void }) {
  const [text, setText] = useState(String(value));
  const [touched, setTouched] = useState(false);
  const editingRef = useRef(false);
  useEffect(() => { if (!editingRef.current) setText(String(value)); }, [value]);
  const localError = touched && parsePositiveDuration(text) === null ? "Enter a positive whole-number duration." : undefined;
  const commitOnBlur = () => {
    editingRef.current = false;
    setTouched(true);
  };
  return <Field label="Duration (seconds)" error={error ?? localError}>
    <input title="Enter a positive duration in seconds" min="1" step="1" inputMode="numeric" type="number" value={text} onChange={(event) => { const nextText = event.target.value; editingRef.current = true; setText(nextText); const duration = draftDurationValue(nextText, value); if (parsePositiveDuration(nextText) === null) setTouched(true); if (duration !== value) onCommit(duration); }} onBlur={commitOnBlur} />
  </Field>;
}

function IconActions({ prefix, index, count, onMove, onRemove }: { prefix: string; index: number; count: number; onMove: (from: number, to: number) => void; onRemove: () => void }) {
  const item = prefix[0].toUpperCase() + prefix.slice(1);
  return <div className="v2-screenplay-icon-actions">
    <button type="button" aria-label={`Move ${prefix} up`} title={`Move ${item} up`} disabled={index === 0} onClick={() => onMove(index, index - 1)}><ChevronUpIcon /></button>
    <button type="button" aria-label={`Move ${prefix} down`} title={`Move ${item} down`} disabled={index === count - 1} onClick={() => onMove(index, index + 1)}><ChevronDownIcon /></button>
    <button type="button" aria-label={`Remove ${prefix}`} title={`Remove ${item}`} onClick={onRemove}><TrashIcon /></button>
  </div>;
}

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return <label className="v2-screenplay-field"><span>{label}</span>{children}{error ? <em>{error}</em> : null}</label>;
}

function errorAt(errors: ReadonlyArray<{ path: string; message: string }>, path: string): string | undefined {
  return errors.find((error) => error.path === path || error.path.startsWith(`${path}.`))?.message;
}

function entityId(item: { client_key?: string | null; scene_id?: string | null; shot_id?: string | null; dialogue_id?: string | null }): string {
  return item.client_key ?? item.scene_id ?? item.shot_id ?? item.dialogue_id ?? "new-item";
}
