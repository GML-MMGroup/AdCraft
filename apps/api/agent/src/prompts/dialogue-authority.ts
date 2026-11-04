/** Preserve speech decisions without turning unwritten dialogue into a prohibition. */
const dialogueAuthorityPolicy = [
  "Dialogue authority check: distinguish confirmed exact lines, exchanges required by the narrative whose wording is still open, and an explicit decision for silence or a closed line list. Preserve confirmed words and speakers; an omission is not a silence instruction. Respect an explicit silence decision only for its stated character, interval or sound category.",
  "For any no-dialogue or no-additional-lines restriction, identify the supplied source and its scope. A short line list, restrained performance, pauses, fixed framing, no narration or no background music does not by itself close all dialogue. An earlier model-authored staging suggestion is not a new user restriction; keep optional choices distinguishable from confirmed requirements.",
  "Before returning, compare required exchanges with the proposed speech and action. Do not convert questioning or a verbal response into silent gestures merely because its exact words were not supplied. Where an inherited speech restriction conflicts with the approved narrative, describe the unresolved conflict and the needed script decision in existing narrative notes or production_handoff. Preserve approved content until that decision is resolved; do not silently rewrite it or strengthen the restriction for downstream roles.",
].join(" ");

export const scriptDialogueDevelopmentPolicy = [
  dialogueAuthorityPolicy,
  "During script development, write the missing exchanges when the approved narrative calls for them and leaves their wording open. Make each exchange advance the approved meaning or evidence, preserve the product facts and reveal order, and fit natural delivery to the duration. Existing quoted lines remain verbatim; they are not automatically an exhaustive list. If an explicitly closed script or silence decision prevents completing an implied exchange, retain it and present the needed revision in existing notes rather than adding unauthorized lines.",
].join(" ");

export const downstreamDialogueContinuityPolicy = [
  dialogueAuthorityPolicy,
  "During style locking, storyboard planning and media-prompt realization, preserve the narrative's required speaking actions and retain missing wording as unresolved script detail. Identify the speaker, purpose and affected beat in existing narrative notes or production_handoff so the script can be completed; do not fabricate approved dialogue or label the passage silent. Carry already-approved silence without broadening it. Storyboard image prompts depict speaking through acting and never transcribe dialogue; exact speech belongs to Script and Video.",
].join(" ");
