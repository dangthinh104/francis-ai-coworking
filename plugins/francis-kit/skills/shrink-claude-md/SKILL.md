---
name: shrink-claude-md
description: Cut a long CLAUDE.md down to its hazards, rules and pointers - propose block by block what stays, what moves word for word to a skill or a document, and what is history, then apply only what the owner approved and prove nothing was lost. Use when a CLAUDE.md is over 150 lines, when kit_doctor reports S02 for its length, or when asked to shrink, shorten, split or slim a CLAUDE.md.
---

# Shrink a CLAUDE.md

Every session reads the whole of `CLAUDE.md`. What only one domain needs belongs in that domain's skill, where it is read when the work touches it. This skill moves text; it does not rewrite it. The judgement is yours and the owner's. The script does the mechanics and refuses what must not happen.

Three things you never do:

- Rewrite, shorten, reorder or "tidy" the text of a block. A block stays as it is, moves word for word, or is history.
- Decide that a rule is no longer wanted. A rule you think is stale moves with the rest, and you say so to the owner.
- Write the owner's approval yourself.

One `CLAUDE.md` per run; in a monorepo, one run per file.

## Step 1: measure

```bash
python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/claude_md_audit.py" --repo "$(git rev-parse --show-toplevel)" --project-root <directory of the file>
```

`--repo` is always the git root, so a path written from the root (`francis/docs/...`) is read from there and from the file's own directory; `--repo` pointed at a subdirectory reports such a path as gone. `--project-root` names the directory of the `CLAUDE.md` the person asked for (`.` for the one at the root), so that file is measured whether the manifest lists its project or not. Other files may be measured too; read the line of this one.

Paste the output: lines, estimated size, and what the file names that is gone. Fix what it reports first, in a commit of its own (`kit-adopt`, S18), so the proposal is written on a file that is true. The working tree is clean and the branch is not one that deploys.

## Step 2: start

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_shrink.py" start CLAUDE.md --out <proposal.json>
```

It writes a first proposal: the file's sha256 and one block per heading section, cut again at blank lines, with no verdict. It prints the hazards: the lines of the Hazards section when the file has one, otherwise candidates. It refuses to overwrite a proposal. Keep the proposal out of the commit, or under a path the project ignores.

## Step 3: fill every verdict

Read the whole file, then give each block one verdict in the proposal. Lines are 1-based, inclusive, whole lines. Merge blocks or cut one in two where the first cut is wrong: a section may be split so that one sentence stays and the rest moves, and the cut falls on a line boundary.

| The block | Verdict |
|---|---|
| A hazard: what breaks production, loses data that cannot be recomputed, moves money, or cannot be undone | `stays` |
| A rule every session needs, whatever it works on; where to read next | `stays` |
| A rule that holds for one domain | `moves` to `.claude/skills/<domain>/SKILL.md` |
| Reference detail: tables of fields, long procedures, examples, lists of endpoints | `moves` to a document under `docs/` |
| What was done or decided on a date, and states no rule that still applies | `delete`, with `why` |

- A move names its target in `to`, a path inside the repository. Give it a `pointer`: one line left in its place that says where the text went, such as ``Billing rules: `.claude/skills/billing/SKILL.md`.``
- A block with a date that also states a rule is not history. Cut it: the rule stays or moves, the dated sentence is history. When you cannot cut on a line boundary, the whole block stays or moves.
- A heading whose section is emptied moves with its section. A heading left over a pointer stays.
- When the target does not exist it will be created, holding the moved text and nothing else. Do not invent an owner, a description or front matter for it; say in your report that a new skill file needs its front matter from the person who owns the domain.

## Step 4: the owner confirms the hazards

Ask once, in one message: show the hazard lines `start` printed, with their line numbers, and ask the owner which are hazards, which are not, and which are missing.

- A file with a Hazards section (a heading that holds the word Hazard or Hazards): those lines stay whatever the proposal says. Ask only whether a hazard sits outside the section.
- A file without one: the candidates are a word match, nothing more. Put the ranges the owner confirmed in `hazards` and their answer, word for word and with the date, in `hazards_confirmed`. An answer of "none" is still an answer and is written down.

Do not go on before the owner has answered.

## Step 5: show

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_shrink.py" show <proposal.json>
```

Paste the whole output: each block with its lines, verdict and target, every target marked "will be created" or "appended to" with the sha256 of its text, the lines and estimated size before and after. The count after is the file `apply` writes, split into the lines that stay, the pointers and the blank lines; give the owner that number, never one counted by hand. It exits 1 and names the block when a non-blank line is in no block or in two, a verdict is missing, a move has no target or leaves the repository, a `delete` block holds no date (a full date, a month and a year, or a capitalised month name with a year), a hazard line is not in a block that stays, or the file has changed since `start`. Fix the proposal, not the file, and show again.

For every block marked `delete`, quote its text under the table so the owner reads what will be gone.

`show` also names each line that stays and points at text that leaves ("see the doc-sync note at the top of this file" when that note moves; "(see Special payload fields)" when that section moves): the line, the block it points at, and where that block goes. It is a report, not an error, and it changes nothing. List every one for the owner, who rewords the line or keeps it; you do not reword it.

## STOP: nothing is changed before the owner approves

Up to here only the proposal file was written. Wait for the owner. When they change a verdict, change the proposal and run `show` again.

`show` ends with a fingerprint: twelve characters that stand for the file, the blocks, the hazards and each target (absent, or its text) as they were shown. A target created or changed after `show` is refused at `apply`, named, like a changed proposal; so is an approval given before targets were in the fingerprint. When the owner approves, put their words, the date and that fingerprint in `approved`, for example `"yes, apply it (owner, 2026-11-12), fingerprint 3f9a1c0b7d2e"`. `apply` refuses an approval that does not hold the fingerprint of the proposal as it is now, so any change to the proposal after that needs a new `show` and a new approval from the owner; never copy a new fingerprint into old words.

Only an approval goes in `approved`, and only the owner's words, never yours. The script cannot read whether the words say yes: an answer of "no", "wait" or "change block 4" is not written there. A session that fills `approved` on its own has broken the one rule this skill exists for.

When `CLAUDE.md` changes after `start`, the proposal is refused. Start again from the file as it is; do not edit the sha256.

## Step 6: apply

Keep a copy of the original outside the repository first, then:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_shrink.py" apply <proposal.json>
```

It appends each moved block to its target word for word, writes the new `CLAUDE.md` from the blocks that stay and the pointers, and puts every file back when anything fails. Then it reads the result from disk: each moved block must be found in its target as whole lines, and every line that stays, the hazards among them, in the new file in the same order, each pointer in it, and nothing else in it: no line twice that was once, no text of a block that moved or was deleted, no line that is neither one that stays, nor a pointer, nor blank. A line starting `LOST` (something is not there) or `WRONG` (something is there that `apply` did not write) and exit 1: stop, show the owner, and restore from git. Paste the output.

The same check later, from the copy: `python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_shrink.py" verify <proposal.json> --original <copy>`.

A proposal made on a copy records the copy, and `apply` would change the copy. Name the file in the repository with `--file <repo>/<dir>/CLAUDE.md` on `show`, `apply` and `verify`; targets are then read from that file's repository. The fingerprint holds no path, but it holds each target as it is in the repository the file is in: run `show` with the same `--file` before the owner approves, or `apply` refuses a target that is not the same in the copy's directory and in the repository. A checkout that writes CRLF (`core.autocrlf=true`) is the same text and is accepted; a changed word is not.

## Step 7: the doctor

```bash
python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_doctor.py" --repo "$(git rev-parse --show-toplevel)"
python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/claude_md_audit.py" --repo "$(git rev-parse --show-toplevel)" --project-root <directory of the file>
```

The audit runs as in Step 1, so a `CLAUDE.md` in a subdirectory the manifest does not list is measured too. Paste both. S02 and S18 must pass for this file: 150 lines at most, and every path it names exists, the pointers included. When S02 is still a gap the file is still too long: that is a second proposal, not an edit by hand. Remove an S02 deviation the manifest holds for this file's length.

## After a merge

When a branch that applied a shrink meets a change to a block that moved, carry the change, including a deletion, into the block's target: keeping the pointer in CLAUDE.md drops it.

Run `merged` after every merge where either side applied a shrink, before or after the merge is committed, and after every finished rebase of such a branch with `--side ORIG_HEAD --side <upstream>`; paste its output.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_shrink.py" merged
python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_shrink.py" merged --side ORIG_HEAD --side <upstream>
```

It prints `LOST  <side>  CLAUDE.md:<n>  <text>` for each line one side added to `CLAUDE.md` that the result holds nowhere. During an unfinished merge the result is what is `git add`ed, so add the target before you run it. It exits 2 while a file is unmerged or a rebase is in progress, and does not see a line the other side only deleted or an old copy left in another file: carry those by hand.

A `LOST` line you accept, such as an approved `delete: history` block the other side edited, still exits 1: name it in the pull request with the reason; before a squash-and-merge, merge the target branch into the pull request's branch and run `merged` there.

## Report

1. Lines and estimated size before and after
2. Files written, and which were created
3. The blocks deleted as history, quoted
4. The doctor's and the audit's output
5. Created skill files that still need front matter from their owner
