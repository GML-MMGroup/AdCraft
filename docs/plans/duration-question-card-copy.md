# Production duration question card copy

## Goal

Compact the production duration questionnaire shown in the chat panel by removing explanatory copy that is redundant for this single duration choice.

## Scope

- For the `production_duration_seconds` questionnaire only, hide the frame context and question prompt.
- Hide each duration option's summary text (for example, “Produce a 30-second advertisement.”).
- Keep the card title, seconds labels, Recommended marker, custom duration input, answer counter, validation errors, and Submit answers behavior.
- Leave all other questionnaire cards unchanged.

## Implementation plan

1. Add a duration-specific compact mode in `QuestionnaireDecisionDock` and pass empty title context/prompt display only for the production-duration question.
2. Add focused tests proving the redundant copy is absent while labels, recommendation, custom input, and submission remain available.
3. Run the questionnaire tests, typecheck, and diff checks.
