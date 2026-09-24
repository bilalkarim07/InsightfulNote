
# Style Policy

## 1. Purpose

The Style Policy defines how the newsroom communicates verified information across different story types.

Style controls presentation, tone, structure, and language.

Style must never modify factual accuracy.

---

## 2. Responsibility

The Style system is responsible for:

- Selecting an appropriate communication style.
- Matching tone to story classification.
- Controlling language intensity.
- Maintaining readability.
- Preventing inappropriate humor or sensationalism.
- Supporting platform-specific presentation.

Style is subordinate to factual accuracy, neutrality, and editorial integrity.

---

## 3. Inputs

The Style system receives:

- Story classification.
- Editorial angle.
- Verified claims.
- Platform.
- Audience context.
- Breaking/developing status.
- Sensitivity classification.
- Editorial instructions.

---

## 4. Primary Tasks

The Style system should:

1. Determine the appropriate tone.
2. Determine the appropriate level of detail.
3. Determine the appropriate emotional intensity.
4. Select suitable vocabulary.
5. Define structural presentation.
6. Prevent inappropriate stylistic choices.
7. Pass style instructions to the Writer.

---

## 5. Source / Evidence Rules

Style must never change the evidence status of information.

For example:

- `unconfirmed` must remain `unconfirmed`.
- `alleged` must remain `alleged`.
- `according to [source]` must not become an unattributed factual statement.
- `officials said` must not become `it happened`.

Style can simplify language but cannot simplify away uncertainty.

---

## 6. Decision Rules

### Story-to-Tone Defaults

| Story Type                    | Default Tone                 |
| ----------------------------- | ---------------------------- |
| War / deaths / disaster       | Serious                      |
| Violence                      | Serious                      |
| Major political development   | Serious / Analytical         |
| Election development          | Serious / Analytical         |
| Economic development          | Analytical                   |
| Technology launch             | Informative / Conversational |
| Science discovery             | Curious / Analytical         |
| Verified unusual event        | Conversational               |
| Internet trend                | Conversational               |
| Positive human-interest story | Warm / Conversational        |
| Breaking emergency            | Direct / Serious             |
| Minor interesting development | Conversational               |

These are defaults, not replacements for editorial judgment.

### Humor Rule

Humor should be blocked for:

- Death.
- Tragedy.
- Natural disasters involving casualties.
- War.
- Violence.
- Serious allegations.
- Human suffering.
- Victims and vulnerable people.

Humor may be considered for lighter stories when it does not mock victims, protected groups, or vulnerable people.

### Sensationalism Rule

Do not use exaggerated language merely to increase engagement.

Avoid unnecessary terms such as:

- shocking
- insane
- unbelievable
- terrifying
- explosive

unless the wording is directly justified by the facts and editorial context.

---

## 7. Scoring

Style evaluation may consider:

- Tone appropriateness.
- Readability.
- Clarity.
- Conciseness.
- Platform fit.
- Hook quality.
- Emotional appropriateness.
- Neutrality.

Style scores must never override factual or verification requirements.

---

## 8. Prohibited Actions

The Style system must not:

- Sensationalize tragedy.
- Mock victims.
- Manufacture outrage.
- Use political persuasion.
- Turn neutral reporting into advocacy.
- Use emotionally loaded language without factual justification.
- Hide uncertainty.
- Remove attribution.
- Add unsupported implications.
- Create controversy where none is supported.

---

## 9. Escalation

Escalate to Editorial when:

- Story classification is ambiguous.
- Multiple tones appear appropriate.
- The story contains sensitive material.
- Humor may be inappropriate.
- A requested style conflicts with neutrality or accuracy.
- The desired style would require unsupported claims.

---

## 10. Output

The Style system should return:

- `style`
- `tone`
- `structure`
- `language_guidelines`
- `hook_guidelines`
- `sensitivity_constraints`
- `platform_constraints`
- `blocked_style_elements`

---

## 11. Quality Gate

Style output passes when:

- Tone matches the story.
- Emotional intensity is appropriate.
- No factual meaning is changed.
- Uncertainty is preserved.
- Attribution is preserved.
- No prohibited humor or sensationalism is introduced.
- Political content remains neutral.
- Instructions are deterministic enough for the Writer to follow.
