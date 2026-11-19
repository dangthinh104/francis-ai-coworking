---
name: cleanup
description: Find and remove clutter in a project - bloated or stale comments, outdated docs, scratch files, orphan files, dead code candidates. Use when asked to clean up, tidy, remove junk or reduce noise in a repo or directory.
---

# Clean up

Clutter is anything a future reader must read and then discard. Removing it is only safe when you know what the project is, so the map comes first.

## Preconditions

1. The standard holds: `python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_doctor.py" --repo "$(git rev-parse --show-toplevel)"` exits 0. If not: `kit-init` or `kit-adopt` first.
2. The architecture map is current: load the `map-project` skill and run its Verify commands. Missing or red: run the `project-mapper` agent first, then come back.
3. Working tree is clean and the current branch is not in `release.deploy_branches`.
4. The scope is named: one project entry and one directory or one feature's files, or the manifest's `scratch` paths. No scope given: ask. Never sweep a whole repo in one run.

## Read before judging

Read the map, the constitution and the specs that cover the scope. A file that looks dead may be an entry point the map lists; a comment that looks long may be a rule the constitution requires.

## What to look for, and what you may do

| Tier | Finding | Action |
|---|---|---|
| 1 | Comments breaking `comment-discipline` | Fix now. History moves to the owning feature's `history.md`; for code no feature owns, to `docs/history.md` |
| 1 | Comment or doc that contradicts the code next to it | Fix when the code is unambiguous, otherwise report |
| 2 | Dated docs whose work has shipped (plans, research notes, incident write-ups) | Propose moving the lasting part into the owning feature's `history.md` and deleting the rest. Wait for approval |
| 2 | Scratch and orphan files: listed in `scratch`, or referenced by no code, doc, CI job or map | Propose deletion with the evidence. Wait for approval |
| 2 | Duplicated doc sections | Propose which copy stays |
| 2 | The same comment block pasted in two places | Trim both to a pointer now; propose extracting the shared code, which is a code change |
| 3 | Dead code candidates: modules, functions, flags nothing reaches | Report only, with how you searched. Never delete |
| 3 | Two docs or comments that contradict each other | Report as an open question. Do not pick a side |

"Referenced by nothing" needs proof: show the search you ran. Dynamic loading, schedulers, CI and config files reference things by string.

## Verify

- Run the project's `test` and `lint` commands from the manifest and paste the real output.
- Run the comment audit before and after on the files you changed: `python3 "${CLAUDE_SKILL_DIR}/../comment-discipline/scripts/comment_audit.py" <files>`.
- Run the Verify commands of `map-project` again: a cleanup that breaks a citation is not finished.
- Paste `git diff --stat`. Tier 1 changes must touch comments and Markdown only.

## Commit

One commit per tier 1 topic. Tier 2 changes get their own commit after approval. Do not push unless asked.

## Report

1. Scope and what was read first
2. Tier 1: fixed (audit before and after)
3. Tier 2: proposals awaiting approval, each with evidence
4. Tier 3: findings and open questions
5. Test, lint and map check output
