---
name: flow
description: The francis-kit development loop and how to find the current stage. Use at the start of work in a project, when asked what the next step is, when asked about the workflow or process, or when unsure which kit skill or agent applies.
---

# The loop

One loop and one layout for every project. The layout and conventions are in `${CLAUDE_SKILL_DIR}/../../STANDARD.md`; the facts of this project (commands, tracker, deploy branches) are in `.claude/kit.yml` at the git root.

| # | Stage | Owner | Exit condition |
|---|---|---|---|
| 0 | Init | `kit-init` (new project) or `kit-adopt` (existing) | `kit_doctor.py` exits 0 |
| 1 | Map | `project-mapper` agent | The Verify commands of `map-project` are green; S12 and S13 removed from `deviations` |
| 2 | Specify | A person, or `spec-writer` when asked to draft (`write-spec`); then `spec-reviewer` in a clean context | `spec_lint.py` has no error, `spec.md` has no open question, and a person set `**Status**: Approved` |
| 3 | Plan | Spec Kit plan, tasks, analyze | `plan.md` and `tasks.md` exist, analyze is clean |
| 4 | Build | Spec Kit implement | No `- [ ]` left in `tasks.md`; `test` and `lint` output pasted; the building session sets `Built` |
| 5 | Review | Fresh session or subagent | "3 places most likely wrong" and the review questions of `code-shape` answered, findings resolved; for an interface, the captures of `design-direction` shown to the user |
| 6 | Release | The project's release process | Merged to `release.pr_target`, deployed; whoever merges sets `Released` |
| 7 | Close | `feature-closer` agent | `specs/_living/` updated, ticket closed; status `Closed` |
| 8 | Clean | `repo-janitor` agent, scoped to the feature's files | Tier 1 fixed, tier 2 decided |
| 9 | Re-map | Verify of `map-project`, then `project-mapper` if red | Green. Back to stage 2 |

- At stage 4, a test that fails is not fixed before its cause is found: `find-cause`.
- At stage 5, a finding of the code review is not fixed before its cause is found: `find-cause`.

## Say the step

Every stage has a fixed name, so a person always knows where the work stands: `step-0-init`, `step-1-map`, `step-2-specify`, `step-3-plan`, `step-4-build`, `step-5-review`, `step-6-release`, `step-7-close`, `step-8-clean`, `step-9-remap`.

Open the first message of a piece of work, and every report, with one line in this shape, in the user's language:

`step-4-build (4 of 9) · 012-late-fee · next: step-5-review, by a fresh session`

A fix shows its lane instead of a feature: `step-4-build · fix for 005/FR-003 · next: step-5-review`. When a stage is left, say which exit condition was met and paste the output that shows it. Never name a step the exit condition of the one before does not allow.

Spec Kit commands are named `/speckit.specify`, `/specify` or `speckit-specify` depending on the installed version; use the ones the project has.

## Which lane

Before stage 2, decide the lane from `STANDARD.md` ("Three lanes"). Say which one and why in one line.

- **Fix**: behaviour does not change. Skip stages 2 and 3. Find the cause first (`find-cause`). Add the ticked task under `## Fixes` in the owning feature's `tasks.md`, write the test that cites the requirement, then stages 4 to 6. A fix moves no Status. Stage 5 still happens for anything that touches money, permissions or numbers. Work that is not about the product's behaviour (CI, tooling, a typo, a dependency update) needs no task line.
- **Spec**: the loop as written.
- **Split**: write the page of intent with the user, then one feature per part, and run the loop for each.

When unsure between Fix and Spec, it is Spec: ask what requirement says the current behaviour is wrong. No requirement, no fix.

## Rules that hold at every stage

1. Before an edit that touches logic, permissions, money or numbers: list assumptions and unknowns, numbered, then edit.
2. Done means real output pasted. A description of a passing test is not a result.
3. The session that wrote something does not review, close or clean it. Stages 1, 5, 7 and 8 run in a clean context.
4. A correction from the user becomes one rule line in the skill that owns the domain (`.claude/skills/<domain>/`). A rule that holds for every project is proposed to francis-kit instead.
5. Nothing is built from a `Draft`. The approval is a person's. A session writes `Approved` only as that person's hand: it puts one question to them that names the feature, how many requirements it has and that no open question is left, and writes the line when the answer to that question is yes. A go-ahead given before the question, or to something else ("ok, continue"), is not that answer. It then adds under Decisions who approved and on which date. A subagent never writes `Approved`. Work in the Fix lane has no spec of its own: it is built from the requirement it restores.
6. The branch rule of `STANDARD.md`: never commit on, or push to, a branch in `release.deploy_branches`; pull requests go to `release.pr_target`; where that target deploys, say in the pull request that merging is releasing and leave the merge to the owner.
7. When `tracker.type` is not `none`, the branch and the pull request carry the feature's ticket id.
8. Comments follow `comment-discipline` from the first commit. The constitution may add rules; it does not relax these.
9. Code follows `code-shape`: the simplest thing that meets the spec, in the shape the project already uses.
10. Words a user reads follow `ui-copy` and `docs/VOICE.md`. No screen is built before `docs/DESIGN.md` has a direction (`design-direction`).
11. Input from outside is checked at the boundary, permission is checked on the server for the object asked for, and no secret goes into code, a test or a log. A package is added only after its registry page was opened and its name and history checked. The rest is in `security`, which loads when the work touches those surfaces.
12. An id never stands alone in what a person reads. The first time a rule, a requirement, a task or a ticket is named in a message, a report or a pull request, say what it is in a few words: `S17 (every project names a dependency audit)`, `005/FR-003 (a late fee is charged once)`, `T012 (migrate the rates table)`. After that the id may stand alone in the same message. A table of ids has a column that says what each one is.
13. Long work is pushed as it goes: commit and push after each step that passes, not once at the end, so a session that stops (a limit, a lost login) loses only the step it was on. A subagent that may not commit says so in its report and leaves the files for its parent to commit.

## Finding the current stage

The kit's commands say `python3`. Where the shell does not find it (Windows: exit 127), run the same command with `python`, and say so once.

```bash
top=$(git rev-parse --show-toplevel)
python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_doctor.py" --repo "$top"     # stage 0
git rev-parse --is-shallow-repository       # true: deepen before trusting a pin check
git status --short | head
ls -d <root>/specs/[0-9]*/ | tail -3        # newest features
grep -m1 '^\*\*Status\*\*' <feature>/spec.md
grep -c '^\s*- \[ \]' <feature>/tasks.md || true
```

Find the newest feature that is not `Closed`: its status names the stage (Draft: 2, Approved: 3 or 4, Built: 5 or 6, Released: 7). No such feature: the project waits at stage 2 for the next spec. Say which stage the project is in and what the exit condition still needs, then do that stage or hand it to its owner.
