# Writing Style

Use plain, direct language for project text and replies about repository work.
Apply this guide to new text and requested edits. Leave unrelated text alone.
The user's requested format and wording take priority.

## General rules

- State the idea, rule, instruction, or result directly.
- Use familiar words and concrete verbs. Keep sentences short enough to read easily.
- Use natural sentence lengths. There is no prescribed dictionary or fixed word limit.
- Keep conditions, exceptions, permissions, and details needed to understand the behavior.
- Include technical details when they help the reader understand or use the information.
- Do not expand a simple idea into extra requirements, advice, or related projects unless requested.
- Remove filler, repeated explanations, and background that the reader does not need.
- Use the same term for the same thing. Explain unfamiliar abbreviations when the reader needs them.
- Say which kind of schema you mean. Never write "schema" alone. This repository has several kinds:
  - LLM reply schemas: the allowed fields and values of a model reply, which Ollama enforces.
  - The settings schema: the settings keys, aliases, and coercion in `data/io/settings_schema.py`.
  - Save and move formats: the shapes of saved data that the migrations convert. See `data/migrations/MIGRATIONS.md`.

  For example, write "the LLM reply schema for letters" or "the settings schema", not "the schema".
- Preserve exact paths, identifiers, commands, formulas, protocol values, and UI labels.
- Use normal punctuation in prose. Keep labels and list fragments consistent with their surrounding text.
- Preserve third-party licenses, quotations, and archived source data.
- Check descriptions of current behavior against the code. Distinguish current behavior from proposed changes.

## Match the format

### TODO lists

Put each idea on one line. Use simple topic headings when they help organize the list.
Keep related conditions on the same line when they are needed to understand the idea.
Do not add introductory explanations, implementation plans, or advice about other projects unless requested.
Keep questions as questions when the feature still needs a decision.

### Documentation and design notes

Explain the rule and the information needed to use or maintain it.
Keep one main subject per paragraph. Use numbered steps for procedures.
Give required conditions before the steps. Keep rules, examples, and proposals distinct.
Keep shared explanations in their primary guide and use short references elsewhere.

### Comments and docstrings

Explain purpose, non-obvious rules, constraints, or compatibility needs.
Avoid repeating what the code already states clearly.
Preserve useful existing comments and update descriptions that no longer match the code.

### UI text and tutorials

Use short labels and direct messages. Name the action or problem clearly.
Explain what the player needs to do when an error requires action.
Keep player instructions focused on controls and gameplay.
Add help text only when requested. Preserve the tutorial's player-facing voice.

### Agent replies

Lead with the answer or result. Match the length to the request.
For changes, state what changed and any relevant verification or remaining limitation.
Include required handoff details without repeating the plan or giving a generic checklist.
Use examples when they clarify something. Leave out unsolicited next steps and offers to continue.

### Existing documents with their own voice

Preserve the tone and format of the root README, informal notes, and `documentation/other/SANDBOX_SECURITY.md`.
Make requested edits clear without imposing a formal technical style on the whole document.

## Examples

| Context | Avoid | Prefer |
| --- | --- | --- |
| TODO | Define a workflow for configurable production costs | Add unit-cost editing |
| TODO | Introduce enhanced allied order visibility capabilities | Let allies see movement arrows |
| Design question | Implement resource storage limits | Decide whether resources need storage limits |
| Change report | The requested documentation restructuring has been successfully completed | Added the writing guide and linked it from AGENTS.md |

Keep extra detail when it changes the meaning. A short phrase must still describe the intended behavior accurately.

## Optional style: casual user english (CUE)

CUE is an informal, non-technical style based on the user's conversational writing.
Use it when the user asks for "CUE" or "casual user english," such as "rewrite this in CUE."
Apply it to the requested text only. It does not replace the default style for other writing.
These rules override the default capitalization and punctuation guidance for that text.

### Voice and wording

- Use everyday words and contractions. Keep the wording relaxed. Short phrases and sentence fragments are fine when the meaning is clear.
- Use natural phrases such as "basically," "stuff like," or "for now" when they fit. Do not add them to every sentence.
- Keep uncertainty honest. Use "maybe" for an uncertain suggestion without making a clear request sound uncertain.
- Use short paragraphs or simple lists. Skip formal introductions, summaries, and headings unless the format needs them.
- Explain the idea without technical terminology unless a specific technical name is needed.
- Keep necessary conditions and exceptions. Preserve the original meaning and level of detail.
- Do not invent slang, jokes, swearing, or exaggerated enthusiasm to make the text sound casual.

### Capitalization, punctuation, and spelling

- Start sentences with lowercase letters unless the first word is a name or another term that needs capitals.
- Use lowercase "i" and "i'm" in ordinary prose.
- Preserve the capitalization of names, acronyms, filenames, identifiers, and exact UI labels, including at the start of a sentence.
- Keep punctuation minimal. Usually omit the final period from a paragraph or list item.
- Separate sentences with periods or line breaks so they do not run together.
- Use commas, question marks, and parentheses when they help convey the meaning or tone.
- Keep apostrophes in contractions: "don't," "can't," "it's," and "there's."
- Correct spelling errors. Casual wording does not require incorrect spelling.
- Keep code, commands, paths, quoted source text, and protocol values intact.

### Examples

| Default wording | CUE |
| --- | --- |
| Allow players to edit unit production costs. | let players change how much units cost |
| Keep the existing file and create a simpler version. | make a simpler version but keep the old file too |
| Display oil cost and defense even when their values are zero. | show oil cost and defense even when they're zero |
| This is a review only. Do not change any files. | this is just a review, don't actually change anything |
| AGENTS.md should link to the writing guide. | AGENTS.md should link to the writing guide |

### Exceptions

- Category titles should be excluded from this style of wriring, for example:

> ### This is a Properly Written Title where Punctuation and Capitalization are kept
> casual english goes here for the description