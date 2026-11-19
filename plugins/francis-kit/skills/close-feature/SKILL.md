---
name: close-feature
description: Post-release cleanup for a Spec Kit feature. Use after a feature is released, or when asked to close, archive or finalize a feature - merges specs/###-feature into the living spec, trims comments, and moves history out of the code.
---

# Close a feature

Run this once per feature, after release. It changes Markdown and comments only. It never changes executable lines.

Run it in a fresh session or through the `feature-closer` agent, not in the session that wrote the feature.

## Before anything

The layout and conventions are the standard's (`${CLAUDE_SKILL_DIR}/../../STANDARD.md`): features in `specs/NNN-slug/`, the living spec in `specs/_living/<capability>/spec.md`, the constitution in `.specify/memory/constitution.md`. Commands, tracker and deploy branches are in `.claude/kit.yml`; in a monorepo ask which project entry.

Run `python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_doctor.py" --repo "$(git rev-parse --show-toplevel)" --all`. If it names this feature under S04 to S09, as a gap or as debt, stop: the feature is not in standard shape yet and `kit-adopt` comes first.

## Steps

### 1. Preconditions

- Working tree is clean and the current branch is not in `release.deploy_branches`.
- The user named the feature (number or directory) and confirmed it is released. If not, stop and ask.
- The feature's status is `Released`. Anything earlier: stop and say which stage it is in.
- `tasks.md` has no `- [ ]`. Open tasks: list them and stop.

### 2. Reconcile spec with what shipped

Read `spec.md`, `plan.md`, `tasks.md` and the feature's shipped changes. Find them from the ticket id or feature number: the merged pull request, `git log --grep '<ticket id>'`, `git log --grep 'specs/###'`, or the files `tasks.md` names. In a shallow clone deepen first. If you cannot establish what shipped, stop and ask. List every place where shipped behaviour differs from an FR-### or SC-###, numbered. Do not resolve drift yourself: show the list and ask which side is right for each item.

### 3. Merge into the living spec

Read the architecture map first so you know which capability each requirement belongs to.

- Group requirements by capability, not by feature.
- Requirement ids are per feature: cite each as `012/FR-003`.
- A requirement keeps the id it was first given. When this feature changes `005/FR-002`, the living spec still calls it `005/FR-002`; tests that cite it stay valid.
- Added requirement: append. Changed: replace the old text and keep every earlier origin on the line, adding yours: `(specs/005-x, changed by specs/012-y)`. Removed: replace it with one line that keeps every origin the requirement carried, `Removed by specs/012-y (was specs/005-x, changed by specs/008-z)`, so each closed feature is still cited (S11).
- Each requirement ends with its origin: `(specs/012-feature-name)`. The doctor (S11) looks for exactly this string.
- Create `specs/_living/<capability>/spec.md` when the capability is new.
- Do not copy user stories, plans or tasks. The living spec states what the system does today.

### 4. Constitution

Never edit the constitution here. If the feature exposed a rule that belongs there, quote the proposed line to the user and let them run the project's Spec Kit constitution command.

### 5. Comment pass

For every file the feature touched, apply the `comment-discipline` skill:

- Run its audit script first and keep the output: `python3 "${CLAUDE_SKILL_DIR}/../comment-discipline/scripts/comment_audit.py" <files>`.
- Move dated history, logs and measurements to `history.md` in the feature directory, under a heading per topic. Leave a 1-line pointer where the reason still matters.
- Delete comments that describe behaviour the code no longer has.
- If two comments contradict each other, do not guess. Add the pair to the report as an open question.
- Run the audit again.

### 6. Mark the feature closed

Set `**Status**: Closed` in `spec.md`; from here on only its Status lines change. Regenerate the index: `python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/spec_index.py" --root <project root>`. Leave the directory in place: Spec Kit derives the next feature number from it. When `tracker.type` is not `none`, close the ticket through the tracker's connector if one is available, else name the ticket for the user to close.

### 7. Lessons

For each correction the user made during this feature, propose one rule line for the skill that owns the domain (`.claude/skills/<domain>/SKILL.md`). A rule that holds for every project is proposed to francis-kit instead. Apply only what the user approves.

### 8. Verify and commit

- Run the manifest's `setup`, `test` and `lint` commands and the doctor again (same command as in "Before anything"), and paste the real output. No output, not done. Name the `ci_only` gates you could not run.
- Paste `git diff --stat` and both audit outputs.
- Two commits: `docs(spec): merge ###-feature-name into living spec` and `chore(comments): trim after ###-feature-name`.
- Do not push or open a PR unless asked. A PR goes to `release.pr_target`; where that branch deploys, say in the description that merging it is a release.

## Report format

1. Drift items and how each was resolved
2. Living spec: requirements added / changed / removed
3. Comment audit before and after
4. Open questions (contradicting comments, unclear ownership)
5. Proposed rule lines
6. Test and lint output
