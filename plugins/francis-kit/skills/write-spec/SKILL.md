---
name: write-spec
description: Turn a request into a feature spec in the francis-kit shape - choose the lane, read what exists, ask once, write spec.md, lint it, and stop at Draft. Use when asked to specify, write or draft a spec, to turn a requirement or a ticket into a feature, when a spec is too big and has to be split, or to review a spec before a person approves it.
---

# Write a spec

A spec says what the system will do, in sentences a test can prove. It is written before the plan and it stops at `Draft`: only a person sets `Approved`.

The shape is the standard's (`${CLAUDE_SKILL_DIR}/../../STANDARD.md`). Where the project has Spec Kit commands (it has `.specify/scripts/` or `.specify/templates/`), they create the directory and the file; otherwise create them by hand. This skill decides what goes in the file.

## Before writing

1. **May an agent write specs here?** Read `CLAUDE.md` and the constitution. Where they say specs are written by people, stop and say so; offer to review a spec a person wrote instead.
2. **Which lane?** (`STANDARD.md`, "Three lanes".) Say it in one line with the reason.
   - Behaviour does not change: **Fix**. No spec. Stop here and use the Fix lane of `flow`. Unsure between Fix and Spec: it is Spec.
   - One capability, about 3 to 12 requirements: **Spec**. Continue.
   - More than that: **Split**. Write one page of intent with the user (the problem, what is in, what is out), cut it into at most five features that can each ship alone, and write them one at a time, the first one first.
3. **Read what exists.** `specs/_living/<capability>/spec.md` for what the system does today, `specs/INDEX.md` for features in the same capability, the map for where it lives (when a project has no map yet, say so and go on). A requirement that already exists is modified under its own id (`005/FR-002`), not written again. One that already holds and does not change is named in Why or in a user story and listed nowhere else.

## Ask once

Put every question in one message, each with the answer you would guess, so the user can reply "yes" to most of them. Ask only what changes a requirement:

- Who does it, and what they have in hand when they start.
- What must be true when it is done, in their words.
- What happens on the unhappy paths that matter here: no permission, bad input, the thing is already done, two people at once.
- What is out of scope. Write that down too.
- Numbers: limits, amounts, times, rounding. Never invent one.

What the user cannot answer yet stays in the spec as `[NEEDS CLARIFICATION: the question]`, inside the requirement it blocks or under "Open questions", nowhere else. A spec holding one cannot be approved.

## Write

`specs/NNN-slug/spec.md`, the next free number, in the project's language for prose:

```
# Feature Specification: <title>

**Status**: Draft
**Ticket**: <id, or none while a Draft>
**Capability**: <the one capability this changes; a new one is named here and gets its directory under specs/_living/ when the feature is closed>

## Why
<the problem, for whom, in three or four sentences>

## User stories
<each one independently testable, most valuable first>

## Requirements
- **FR-001**: The system MUST <one behaviour a test can prove>.

## Success criteria
- **SC-001**: <a number or an observation, not an adjective>

## Out of scope
- <what a reader might expect and will not get>

## Open questions
- [NEEDS CLARIFICATION: <a question that belongs to no single requirement>]

## Decisions
<how each open question was answered and by whom, written when it is answered; `- none` while there is nothing to record>

## Added
<ids that are new, one per line: `- FR-001`; write `- none` when a section is empty>

## Modified
<`005/FR-002` and its new text, for each requirement of an earlier feature this one changes>

## Removed
<ids that no longer hold; a requirement listed here is no longer declared>
```

Rules for a requirement:

- One behaviour per id. "and" between two behaviours is two requirements.
- MUST, SHOULD or MAY, and a subject: who or what does it.
- It says what, never how: no table, class, endpoint or library, unless the user's requirement is that interface.
- A test could fail it. "Fast", "friendly", "secure" are not requirements; a time, a message, a refusal are. A success criterion is an observation unless the user gave the number.
- Permission and money are stated, never implied: who may, who may not, which amount, which rounding.

## Check

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/spec_lint.py" --root <project root> NNN
python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/spec_index.py" --root <project root>
```

`NNN` is the feature's number or its directory name. Exit 0 is clean, 1 an error, 2 nothing could be read. Paste the output. An error is fixed. A warning is fixed or answered in one line to the user (more than 12 requirements: propose the split). On a Draft or Approved spec the lint also warns, by id, about a requirement that holds two behaviours: a second MUST, SHOULD, MAY, PHẢI, KHÔNG ĐƯỢC or NÊN in capitals (the PHẢI of KHÔNG PHẢI, "is not", does not count), or `and also`, `as well as`, `và cũng`. Split it into two ids; words quoted in backticks do not count. On an Approved spec, put the split to the owner before making it: splitting the requirement changes what was approved. The gate of a project runs this lint without `--strict`: an error fails the pull request, a warning does not.

Then hand the spec to the `spec-reviewer` agent, which reads it without this conversation. Its findings are resolved or put to the user before anyone is asked to approve.

## Stop

Report: the lane, the questions still open, the lint output, the reviewer's findings. The status stays `Draft`. Do not write `plan.md`, do not start code.

When the lint is clean and no question is open, ask for the approval in one question of its own, for example: "Approve 007-late-fees, 6 requirements, no open question?" Only a yes to that question lets you write `**Status**: Approved`, with a line under Decisions that says who approved and on which date. Anything else leaves it at `Draft`.

## Reviewing a spec someone else wrote

Run the lint, then answer with file and line:

1. Which requirement can no test fail?
2. Which two statements contradict each other: a requirement against another, against the living spec, against "Out of scope" or against what `## Modified` declares?
3. Which unhappy path has no requirement: no permission, bad input, done twice, two at once?
4. Which number is missing or was invented?
5. What is in the spec that the stated problem does not need?
6. Is the lane right: would an open question, once answered, make this two capabilities or more than 12 requirements?

Report findings. Do not rewrite the spec: its author decides.
