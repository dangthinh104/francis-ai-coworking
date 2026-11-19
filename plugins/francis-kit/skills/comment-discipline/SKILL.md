---
name: comment-discipline
description: Rules for writing and trimming comments in code, config and CI files. Use whenever you write or edit a comment, review a diff for comment quality, or are asked to clean up comments.
---

# Comment discipline

A comment states a constraint that is true right now and that the code cannot say itself. Everything else belongs somewhere else.

These rules are the same in every project. A constitution may add stricter ones.

## Rules

1. **Present tense, 3 lines at most.** Say what must stay true and why. No story of how we got here.
2. **No history.** Dates, log excerpts, measurements, run IDs and names of people go in the commit message or in the feature's `history.md`. The comment may point there.
3. **No numbers that drift.** Test counts, durations, suite counts and sizes go stale silently. Leave them out.
4. **One reason, one place.** If two blocks need the same explanation, extract the shared code (composite action, function, include) and comment it once. Never paste a comment block twice.
5. **Edit comments with the code.** When you change a line, fix or delete the comments next to it in the same commit. Deleting a stale comment is always allowed.

## Citing a requirement

Write `NNN/FR-001` and nothing else: the id leads to the text, so the comment does not repeat it.

- A test carries the id of the requirement it proves.
- Production code carries an id only on the class or function that enforces a business rule. Not on every line that takes part, and not on helpers.
- "Before FR-209 this did X" is history. It goes in the commit message or `history.md`.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/spec_refs.py" --root <project root> --report            # what leads nowhere
python3 "${CLAUDE_SKILL_DIR}/scripts/spec_refs.py" --root <project root> --fix --dry-run     # what can be rewritten safely
python3 "${CLAUDE_SKILL_DIR}/scripts/spec_refs.py" --root <project root> --check             # the gate: no worse than the baseline
```

`--fix` changes a citation only inside a comment or a Python docstring, only when the owner touches the id (`spec 139 FR-008`, `FR-008 (spec 139)`, or a list that continues one), and only when that one feature declares every id on the line. `FR-063-003` is rewritten only with `--dashed`, after you have checked the project does not write ranges that way. Everything else is listed, never guessed: a wrong owner is worse than a missing one. Read the `--dry-run` list before running it for real, and run the project's tests after.

Record the starting point once with `--write-baseline`, then let the counts only go down. A project that already has its own citation checker teaches it the standard form first, or its gate will read every rewrite as a new problem.

## Where each kind of information lives

| Information | Home |
|---|---|
| What the system must do (FR-###, SC-###) | `specs/NNN-slug/spec.md`, then `specs/_living/` when the feature is closed |
| Why this line is written this way | Comment next to the code |
| What happened (incident, measurement, decision date) | Commit message, ticket, `specs/NNN-slug/history.md` |
| A lesson that applies to future work | The skill or doc that owns that domain |
| Project-wide non-negotiable rule | `.specify/memory/constitution.md` (propose, never edit silently) |

## Example

Before:

```yaml
# DO NOT use docker/setup-buildx-action. It creates a builder with the
# container driver ... (18 lines, a dated log excerpt, two measurements)
```

After:

```yaml
# No setup-buildx: the container driver needs double the disk for `load: true`.
# History: specs/007-ci-gates/history.md#buildx
```

## Audit

Run the audit before and after a cleanup and paste both outputs:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/comment_audit.py" <file> [<file> ...]
python3 "${CLAUDE_SKILL_DIR}/scripts/comment_audit.py" --strict <file>   # exit 1 when a limit is exceeded
```

The script is a heuristic. The ratio is judged only on files of 40 lines or more: in a small enum or value object one needed explanation is already a large share. It reports comment ratio, dated comments, comment lines duplicated within a file, and the longest comment block. It does not see docstrings, skips Markdown and missing files, and its limits are strict on purpose: use the numbers to rank files and to compare before with after, not as a verdict.
