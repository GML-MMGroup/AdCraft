import { ChevronDownIcon, ChevronUpIcon, PlusIcon, TrashIcon } from "../../../../icons.tsx";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { V2EditableScriptCharacter, V2EditableScriptDocument, V2EditableScriptLocation, V2ScriptAspectRatio } from "../../../../types-v2.ts";
import { createEditableScene, reorderItem } from "./screenplayModel.ts";
import { createProductBeatRows, reconcileProductBeatRows, type ProductBeatRow, type ScreenplayProductOption } from "./screenplayUiHelpers.ts";
import { V2ScreenplayShotEditor } from "./V2ScreenplayShotEditor.tsx";

type Props = {
  document: V2EditableScriptDocument;
  validationErrors: ReadonlyArray<{ path: string; message: string }>;
  onChange: (update: (document: V2EditableScriptDocument) => V2EditableScriptDocument) => void;
  productOptions?: readonly ScreenplayProductOption[];
};

let clientKeyCounter = 0;
const aspectRatios: V2ScriptAspectRatio[] = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"];

export function V2ScreenplaySceneEditor({ document, validationErrors, onChange, productOptions = [] }: Props) {
  const characters = document.characters ?? [];
  const locations = document.locations ?? [];
  const change = (update: (next: V2EditableScriptDocument) => void) => onChange((next) => { update(next); return next; });
  const setField = (field: "script_title" | "language" | "tone" | "visual_style", value: string) => change((next) => { next[field] = value; });

  return <div className="v2-screenplay-editor">
    <section className="v2-screenplay-section" aria-labelledby="v2-screenplay-details">
      <h3 id="v2-screenplay-details">Script details</h3>
      <div className="v2-screenplay-fields">
        <Field label="Script title" error={errorAt(validationErrors, "script_title")}><input value={document.script_title} onChange={(event) => setField("script_title", event.target.value)} /></Field>
        <Field label="Language" error={errorAt(validationErrors, "language")}><input value={document.language} onChange={(event) => setField("language", event.target.value)} /></Field>
        <Field label="Tone" error={errorAt(validationErrors, "tone")}><input value={document.tone} onChange={(event) => setField("tone", event.target.value)} /></Field>
        <Field label="Visual style" error={errorAt(validationErrors, "visual_style")}><input value={document.visual_style} onChange={(event) => setField("visual_style", event.target.value)} /></Field>
        <Field label="Aspect ratio" error={errorAt(validationErrors, "aspect_ratio")}><select value={document.aspect_ratio} onChange={(event) => change((next) => { next.aspect_ratio = event.target.value as V2ScriptAspectRatio; })}>{aspectRatios.map((ratio) => <option key={ratio} value={ratio}>{ratio}</option>)}</select></Field>
      </div>
      <ProductBeatsEditor beats={document.product_beats ?? []} onChange={(beats) => change((next) => { next.product_beats = beats; })} />
    </section>
    <EntitySection
      title="Characters"
      addLabel="Add character"
      onAdd={() => change((next) => { next.characters = [...(next.characters ?? []), createCharacter()]; })}
    >
      {characters.length === 0 ? <Empty label="No characters yet." /> : characters.map((character, index) => <article className="v2-screenplay-entity" key={entityId(character)}>
        <ItemHeading label={`Character ${index + 1}`} prefix="character" index={index} count={characters.length} onMove={(from, to) => change((next) => { next.characters = reorderItem(next.characters ?? [], from, to); })} onRemove={() => change((next) => removeCharacterReferences(next, entityId(character)))} />
        <div className="v2-screenplay-fields">
          <Field label="Display name" error={errorAt(validationErrors, `characters.${index}.display_name`)}><input value={character.display_name} onChange={(event) => change((next) => updateEntity(next.characters ?? [], index, (item) => { item.display_name = event.target.value; }))} /></Field>
          <Field label="Role" error={errorAt(validationErrors, `characters.${index}.role`)}><input value={character.role} onChange={(event) => change((next) => updateEntity(next.characters ?? [], index, (item) => { item.role = event.target.value; }))} /></Field>
          <Field label="Description" error={errorAt(validationErrors, `characters.${index}.description`)}><textarea value={character.description} onChange={(event) => change((next) => updateEntity(next.characters ?? [], index, (item) => { item.description = event.target.value; }))} /></Field>
          <Field label="Visual notes" error={errorAt(validationErrors, `characters.${index}.visual_notes`)}><textarea value={character.visual_notes} onChange={(event) => change((next) => updateEntity(next.characters ?? [], index, (item) => { item.visual_notes = event.target.value; }))} /></Field>
          <Field label="Gender"><input value={character.gender ?? ""} onChange={(event) => change((next) => updateEntity(next.characters ?? [], index, (item) => { item.gender = event.target.value || null; }))} /></Field>
        </div>
      </article>)}
    </EntitySection>
    <EntitySection title="Locations" addLabel="Add location" onAdd={() => change((next) => { next.locations = [...(next.locations ?? []), createLocation()]; })}>
      {locations.length === 0 ? <Empty label="No locations yet." /> : locations.map((location, index) => <article className="v2-screenplay-entity" key={entityId(location)}>
        <ItemHeading label={`Location ${index + 1}`} prefix="location" index={index} count={locations.length} onMove={(from, to) => change((next) => { next.locations = reorderItem(next.locations ?? [], from, to); })} onRemove={() => change((next) => removeLocationReferences(next, entityId(location)))} />
        <div className="v2-screenplay-fields">
          <Field label="Display name" error={errorAt(validationErrors, `locations.${index}.display_name`)}><input value={location.display_name} onChange={(event) => change((next) => updateEntity(next.locations ?? [], index, (item) => { item.display_name = event.target.value; }))} /></Field>
          <Field label="Description" error={errorAt(validationErrors, `locations.${index}.description`)}><textarea value={location.description} onChange={(event) => change((next) => updateEntity(next.locations ?? [], index, (item) => { item.description = event.target.value; }))} /></Field>
          <Field label="Visual notes" error={errorAt(validationErrors, `locations.${index}.visual_notes`)}><textarea value={location.visual_notes} onChange={(event) => change((next) => updateEntity(next.locations ?? [], index, (item) => { item.visual_notes = event.target.value; }))} /></Field>
          <Field label="Location type"><input value={location.location_type ?? ""} onChange={(event) => change((next) => updateEntity(next.locations ?? [], index, (item) => { item.location_type = event.target.value || null; }))} /></Field>
          <Field label="Time of day"><input value={location.time_of_day ?? ""} onChange={(event) => change((next) => updateEntity(next.locations ?? [], index, (item) => { item.time_of_day = event.target.value || null; }))} /></Field>
          <SettingField value={location.setting_type ?? ""} error={errorAt(validationErrors, `locations.${index}.setting_type`)} onChange={(value) => change((next) => updateEntity(next.locations ?? [], index, (item) => { item.setting_type = value; }))} />
        </div>
      </article>)}
    </EntitySection>
    <EntitySection title="Scenes" addLabel="Add scene" onAdd={() => change((next) => { next.scenes.push(createEditableScene()); })}>
      {document.scenes.length === 0 ? <Empty label="No scenes yet." error={errorAt(validationErrors, "scenes")} /> : document.scenes.map((scene, index) => <article className="v2-screenplay-scene" key={entityId(scene)}>
        <ItemHeading label={`Scene ${index + 1}`} prefix="scene" index={index} count={document.scenes.length} onMove={(from, to) => change((next) => { next.scenes = reorderItem(next.scenes, from, to); })} onRemove={() => change((next) => removeSceneReferences(next, entityId(scene)))} />
        <div className="v2-screenplay-fields">
          <Field label="Scene title" error={errorAt(validationErrors, `scenes.${index}.title`)}><input value={scene.title} onChange={(event) => change((next) => updateEntity(next.scenes, index, (item) => { item.title = event.target.value; }))} /></Field>
          <Field label="Scene description" error={errorAt(validationErrors, `scenes.${index}.description`)}><textarea value={scene.description} onChange={(event) => change((next) => updateEntity(next.scenes, index, (item) => { item.description = event.target.value; }))} /></Field>
          <Field label="Location" error={errorAt(validationErrors, `scenes.${index}.location_id`)}><select value={scene.location_id ?? ""} onChange={(event) => change((next) => updateEntity(next.scenes, index, (item) => { item.location_id = event.target.value || null; }))}><option value="">No location</option>{locations.map((location) => <option key={entityId(location)} value={entityId(location)}>{location.display_name || "Untitled location"}</option>)}</select></Field>
          <Field label="Location type"><input value={scene.location_type ?? ""} onChange={(event) => change((next) => updateEntity(next.scenes, index, (item) => { item.location_type = event.target.value || null; }))} /></Field>
          <Field label="Time of day"><input value={scene.time_of_day ?? ""} onChange={(event) => change((next) => updateEntity(next.scenes, index, (item) => { item.time_of_day = event.target.value || null; }))} /></Field>
          <SettingField value={scene.setting_type ?? ""} error={errorAt(validationErrors, `scenes.${index}.setting_type`)} onChange={(value) => change((next) => updateEntity(next.scenes, index, (item) => { item.setting_type = value; }))} />
        </div>
        <V2ScreenplayShotEditor document={document} sceneIndex={index} validationErrors={validationErrors} onChange={onChange} productOptions={productOptions} />
      </article>)}
    </EntitySection>
  </div>;
}

function EntitySection({ title, addLabel, onAdd, children }: { title: string; addLabel: string; onAdd: () => void; children: ReactNode }) { return <section className="v2-screenplay-section"><div className="v2-screenplay-section-heading"><h3>{title}</h3><button className="v2-screenplay-add" type="button" onClick={onAdd}><PlusIcon /> {addLabel}</button></div>{children}</section>; }
function Empty({ label, error }: { label: string; error?: string }) { return <p className="v2-screenplay-empty">{label}{error ? <em>{error}</em> : null}</p>; }
function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) { return <label className="v2-screenplay-field"><span>{label}</span>{children}{error ? <em>{error}</em> : null}</label>; }
function SettingField({ value, error, onChange }: { value: "" | "interior" | "exterior"; error?: string; onChange: (value: "interior" | "exterior" | null) => void }) { return <Field label="Setting" error={error}><select value={value} onChange={(event) => onChange((event.target.value || null) as "interior" | "exterior" | null)}><option value="">Unspecified</option><option value="interior">Interior</option><option value="exterior">Exterior</option></select></Field>; }
function ProductBeatsEditor({ beats, onChange }: { beats: string[]; onChange: (beats: string[]) => void }) {
  const sequence = useRef(0);
  const createKey = () => `product-beat-ui-${++sequence.current}`;
  const [rows, setRows] = useState<ProductBeatRow[]>(() => createProductBeatRows(beats, createKey));

  useEffect(() => {
    setRows((current) => current.map((row) => row.value).join("\u0000") === beats.join("\u0000")
      ? current
      : reconcileProductBeatRows(current, beats, createKey));
  }, [beats]);

  const publish = (next: ProductBeatRow[]) => {
    setRows(next);
    onChange(next.map((row) => row.value));
  };

  return <section className="v2-screenplay-product-beats"><div className="v2-screenplay-section-heading"><h4>Product beats</h4><button className="v2-screenplay-add" type="button" onClick={() => publish([...rows, { key: createKey(), value: "Describe the product beat." }])}><PlusIcon /> Add product beat</button></div>{rows.length === 0 ? <Empty label="No product beats yet." /> : rows.map((row, index) => <div className="v2-screenplay-beat" key={row.key}><ItemHeading label={`Product beat ${index + 1}`} prefix="product beat" index={index} count={rows.length} onMove={(from, to) => publish(reorderItem(rows, from, to))} onRemove={() => publish(rows.filter((_, itemIndex) => itemIndex !== index))} /><Field label="Product beat"><textarea value={row.value} onChange={(event) => publish(rows.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} /></Field></div>)}</section>;
}
function ItemHeading({ label, prefix, index, count, onMove, onRemove }: { label: string; prefix: string; index: number; count: number; onMove: (from: number, to: number) => void; onRemove: () => void }) { return <div className="v2-screenplay-item-heading"><strong>{label}</strong><div className="v2-screenplay-icon-actions"><button type="button" aria-label={`Move ${prefix} up`} title={`Move ${label} up`} disabled={index === 0} onClick={() => onMove(index, index - 1)}><ChevronUpIcon /></button><button type="button" aria-label={`Move ${prefix} down`} title={`Move ${label} down`} disabled={index === count - 1} onClick={() => onMove(index, index + 1)}><ChevronDownIcon /></button><button type="button" aria-label={`Remove ${prefix}`} title={`Remove ${label}`} onClick={onRemove}><TrashIcon /></button></div></div>; }
function updateEntity<T>(items: T[], index: number, update: (item: T) => void) { if (items[index]) update(items[index]); }
function errorAt(errors: ReadonlyArray<{ path: string; message: string }>, path: string): string | undefined { return errors.find((error) => error.path === path || error.path.startsWith(`${path}.`))?.message; }
function entityId(item: { client_key?: string | null; character_id?: string | null; location_id?: string | null; scene_id?: string | null }): string { return item.client_key ?? item.character_id ?? item.location_id ?? item.scene_id ?? "new-item"; }
function clientKey(namespace: string) { clientKeyCounter += 1; return `${namespace}-client-ui-${clientKeyCounter}`; }
function createCharacter(): V2EditableScriptCharacter { return { client_key: clientKey("character"), display_name: "New character", role: "supporting", description: "Describe the character.", visual_notes: "Describe visual details.", gender: null }; }
function createLocation(): V2EditableScriptLocation { return { client_key: clientKey("location"), display_name: "New location", description: "Describe the location.", visual_notes: "Describe visual details.", location_type: null, time_of_day: null, setting_type: null }; }

function removeCharacterReferences(document: V2EditableScriptDocument, characterId: string) {
  document.characters = (document.characters ?? []).filter((character) => entityId(character) !== characterId);
  document.scenes.forEach((scene) => scene.shots.forEach((shot) => { shot.character_ids = (shot.character_ids ?? []).filter((id) => id !== characterId); shot.dialogue = (shot.dialogue ?? []).filter((line) => line.character_id !== characterId); }));
  return document;
}
function removeLocationReferences(document: V2EditableScriptDocument, locationId: string) { document.locations = (document.locations ?? []).filter((location) => entityId(location) !== locationId); document.scenes.forEach((scene) => { if (scene.location_id === locationId) scene.location_id = null; }); return document; }
function removeSceneReferences(document: V2EditableScriptDocument, sceneId: string) { document.scenes = document.scenes.filter((scene) => entityId(scene) !== sceneId); document.scenes.forEach((scene) => scene.shots.forEach((shot) => { shot.scene_ids = (shot.scene_ids ?? []).filter((id) => id !== sceneId); })); return document; }
