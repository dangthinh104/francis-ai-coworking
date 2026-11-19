# CLAUDE.md

This file is short on purpose: what must never be broken, the rules, and where to read next. Detail lives in `.claude/skills/<domain>/`.

## What this project is

{{TITLE}}: <one paragraph: what it does, for whom, where it runs>

## Read first

1. `.specify/memory/constitution.md` - the principles that win over everything else
2. `docs/ARCHITECTURE.md` - the map
3. `specs/_living/` - what the system does today
4. `specs/` - the feature in progress is the highest number

## Hazards

<one line each: what breaks production, loses data or moves money. Remove this line when the first hazard is written.>

## How work is done here

This project follows the francis-kit standard. Load the `flow` skill to find the current stage.

- Assumptions out loud, numbered, before an edit that touches logic, permissions, money or numbers.
- Done means real output pasted.
- A correction becomes one rule line in the skill that owns the domain, not in this file.
- The session that wrote a change does not review it.

## The gate

Commands are in `.claude/kit.yml` (`setup`, `test`, `lint`). Run them before opening a pull request.
