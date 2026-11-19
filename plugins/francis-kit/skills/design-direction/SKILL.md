---
name: design-direction
description: Decide what a product should look like before any interface code is written, and check that its pages do not all look the same. Use before building or restyling a screen, when a project has no docs/DESIGN.md, and when reviewing a set of pages.
---

# Design direction

Pages come out alike when they are built before anyone chose a direction: the same font, the same rounded cards, the same grid. The fix is a decision written down once, and a different frame for each kind of page.

Figma is not required. A project needs it when a designer works on it or a client must approve the look before code; then the Figma file is the source and this skill reads from it. Otherwise the direction lives in the repository.

## Before any interface code

1. Read `docs/DESIGN.md`. If it does not exist or is still the unfilled template (the doctor reports S16), write it with the user from `${CLAUDE_SKILL_DIR}/templates/DESIGN.md`. Offer two or three directions that differ in kind (not three shades of one). Each is one HTML file of the same real screen of this product, at 1440 wide, under `docs/design/directions/<name>.html`, shown to the user as a rendered page or a capture. The user picks; do not pick for them. The files of the directions not chosen are deleted.
2. If a `frontend-design` skill is available, load it for the craft of the direction (type, colour, spacing, motion). This skill decides *that* a direction exists and *that* pages differ; that one helps make it good.
3. Use the project's own component kit and tokens when it has them. Extend the kit; do not write one-off styles beside it.

## One frame per kind of page

Name the kind of each page before building it. Each kind has its own frame in `DESIGN.md`; a page does not borrow another kind's frame.

| Kind | What the user is doing | The frame is built around |
|---|---|---|
| List | Finding one thing among many | A dense table or rows, filters, one primary action |
| Detail | Reading one thing closely | A header that identifies it, then sections in the order they are needed |
| Form | Entering data | One column, fields in the order of the task, the action at the end |
| Overview | Judging a situation at a glance | A few numbers that matter, each leading somewhere |
| Flow | Doing a task in steps | One step on screen, where they are, a way back |
| Empty or first run | Starting from nothing | One sentence and one action |

Rules:

- A card is for an item among peers. A page section is not a card. If every block on a page is a rounded card, the page has no hierarchy.
- One primary action per screen.
- Density follows the task: an operator who enters twenty rows wants a table, not twenty cards.
- Wording follows the `ui-copy` skill.

## Check with pictures, not from the code

After building or changing pages:

1. Capture every page of the feature at the widths the project targets (default 1440 and 390), with the project's Playwright setup, or the session's browser when the project has none. Say which you used. Measure what the spec states in numbers (sizes, gaps, contrast) from the DOM, not by eye.
2. Lay the captures side by side and look at them as a set. Two pages look alike when they share the same column structure and the same main component repeated (for example a grid of cards). Report each such pair: are they the same kind? Same kind is expected to match. Different kinds that match are a finding.
3. Show the set to the user. A page is not done on the strength of its code or its tests.

## When the user corrects a design

Add the decision to `docs/DESIGN.md` (what, and what it rules out), so the next page starts from it.
