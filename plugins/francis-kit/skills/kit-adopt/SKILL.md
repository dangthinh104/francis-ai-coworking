---
name: kit-adopt
description: Bring an EXISTING project onto the francis-kit standard - measure the gaps with kit_doctor, record them as deviations, and close them in small pull requests. Use when a repo already has specs, docs, a CLAUDE.md or its own process and is asked to adopt, migrate to, align with or conform to the kit.
---

# Adopt the standard in an existing project

The standard is `${CLAUDE_SKILL_DIR}/../../STANDARD.md`. The project moves to it. Where the project does something else today, that is a gap to close, not an option to keep.

Two things do not move: history is not rewritten, and the product's behaviour does not change. Adoption touches Markdown, manifests and file locations. It may also edit what guards the old layout (a test that globs `specs/`, a CI path filter, a script with a hard-coded docs path), listed in the pull request: in a commit of its own where the guard can change first and stay green, otherwise in the same commit as the move, so that no commit leaves the project's tests red.

## Step 1: measure

```bash
python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_doctor.py" --repo "$(git rev-parse --show-toplevel)"
```

For a monorepo without a manifest add `--project-root <dir>` per project. Paste the output.

## Step 2: first pull request - manifest and debt list

On a branch that does not deploy:

1. Read the facts first: `python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_detect.py" --repo "$(git rev-parse --show-toplevel)"`, as `kit-init` reads them under "Read".
2. Run `python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/claude_md_audit.py" --repo "$(git rev-parse --show-toplevel)"` and show its output: what the project's `CLAUDE.md` names that git once held and that is gone. Every session has been reading that file; what it gets wrong is known before anything is built on it.
3. Ask before writing any file. An existing project is asked the same questions as a new one: put the groups of `kit-init`, "Ask once", to the user in one message, each with what `kit_detect.py` read as the suggested answer. The gate question is among them, all in that message: first `Does GitHub start jobs on GitHub-hosted runners (such as ubuntu-latest) for this account?` (yes, no, don't know), then where the gate runs, suggested as `gate_choice` gives it for that answer, with its `why`, then the labels of a `runner` answer, as `kit-init` asks them. The answers offered here:
   - `hosted`: the workflow `.github/workflows/kit-gate.yml` on GitHub's runners; no variable is set.
   - `runner`: the same workflow on the project's own runner, chosen by the repository variable `KIT_GATE_RUNNER`, which a person sets with the line the scaffold prints.
   - `hook`: `gate: hook` in the manifest and `.githooks/pre-push`; not offered where `hook_manager` is not empty. Say it plainly before the user chooses: the hook guards the author's clone, not the release; a merge in GitHub's web interface and a push from a clone that has not switched it on are not judged.
   - None of them: the project keeps no gate for now. Pass `--gate-at none`, and record S14 in the top-level `deviations` here alone, where the user takes none of the three answers.

   What the ticket ids look like, which branches deploy and what must never break are the user's to say; a reading from commits is a suggestion, and a fact nobody confirmed is not written into the manifest.
4. Run `python3 "${CLAUDE_SKILL_DIR}/../kit-init/scripts/kit_scaffold.py" --repo "$(git rev-parse --show-toplevel)" --gate-at <answer> --dry-run`, then without `--dry-run`, with one `--runner-label <label>` per label for `runner`. It creates only what is missing, and writes the line `gate:` into a manifest that has no such key. Where it refuses (the manifest names another gate, the other gate file is there), it writes nothing and its line says what to do first: pass it to the user, and once they have done it (a gate file is removed with `git rm`), run it again; that is not a new round of questions. Under `runner` give the user its last two lines, the `gh` command and the note that the kit sets nothing on GitHub; under `hook` the two commands it prints, and run `git add --chmod=+x .githooks/pre-push` before the doctor: S14 reports a hook git does not hold executable, and that is no reason for a deviation. In a monorepo run it once per project with `--project-root <dir>` and add each project to the manifest by hand.
5. Fill in `.claude/kit.yml` as `kit-init` describes under Run, and confirm with the user every reading that decides where code goes (pull-request target, branches that deploy).
6. For every remaining `GAP`, add an entry under `deviations` with the rule id, a one-line reason, and the fix from the table below. For S04 to S09 and S11 list under `features:` exactly the names the doctor prints with `--all`: no more, no fewer; for S18 and S19 the same under `names:`. A rule that names things (S04 to S09, S11, S18, S19) may have several entries, each with its own reason, fix and names; a name held by two entries is a gap of S01. A project whose gate pins an older kit writes its gate again (README, "Releasing the kit", step 4) before it records a second entry on a rule: the gate runs the doctor of the version it pins, which reports that entry as listed twice. S14 and S15 go in the top-level `deviations` list. A deviation the doctor now calls `listed under deviations but conforms now` (an S14 entry once the gate of the answer is written, for one) is removed, not kept. Run the doctor again: it must exit 0 with `DEBT` lines and no `GAP`.
   Features under `.specify/specs/` are judged too, so their status, ticket and task gaps are known before the S05 move, not after.
7. Before committing, search the project's tests, scripts and CI for anything that guards its layout (`kit_detect.py` lists the workflows that name `specs/` under `reads_specs`; that list is a start, not the whole search): `git grep -nE "specs/|\.specify/|docs/[A-Z]" -- ':!specs' ':!docs' ':!*.lock'` and read the hits. `git grep` reads tracked files only, so `node_modules` and a virtualenv are left out, and every language is included. The scaffold adds `specs/_living/`; a test that lists every directory under `specs/` will need to skip it. Run those guards. Say which ones you could not run.

This pull request changes no existing file except `.claude/settings.json`, `.claude/kit.yml` (the one line `gate:` the scaffold adds where it has no such key, and the fields and `deviations` of steps 5 and 6), a gate file the person removes with `git rm` where the scaffold refused the answer for it, and, where item 7 found one that the new directories break, that guard, in a commit of its own. From here on the gate holds the line: new gaps fail, listed debt does not.

## Step 3: close the debt, one rule per pull request

Read `release` in the manifest first. Where `pr_target` is one of `deploy_branches`, every merge deploys, a Markdown-only one included: put the rules into as few pull requests as the reviewer accepts, say in each description that merging it is a release, and leave the merge to the owner and the project's release window.

Order: cheapest and safest first. Each pull request removes what it fixed from `deviations`: the whole entry, or the names it fixed from `features`. The doctor fails on an entry or a name left behind.

| Rule | Fix | Kind |
|---|---|---|
| S05 | `git mv .specify/specs/NNN-slug specs/NNN-slug`; update links that point at the old path | move |
| S04 | Rename feature directories to `NNN-slug`; renumber the later of two directories sharing a number and record the old name in its `history.md`; move stray files into the feature they belong to or into `docs/`. A file a tool reads or writes (an index, a baseline) moves together with the tool's path, or stays as recorded debt | move |
| S07 | Add the Status line. Map the project's wording to the seven values by what it means, not how it is spelled: an `approved` in a project's front matter that means "built and in force" is not the kit's `Approved`. Where one rule maps a project's wording for every feature, put that rule to the user once, not feature by feature. Where the old wording does not say whether the feature shipped, do not pick: list it for the user and leave it under the deviation until they answer. A feature that shipped without `plan.md` or `tasks.md` is `Released` and is listed under S06. Keep the old wording, word for word, on a `**Status note**:` line. A project whose constitution names another document as the source of status: stop and ask before adding a second one | edit |
| S08 | Only in a project with a tracker (with `tracker.type: none` the rule is skipped and nothing is added). Add the Ticket line from the spec's own text or the tracker. An approved feature with no ticket in a project that has a tracker stays in the deviation until someone creates the ticket. A feature the map gives several tickets stays there too, until a person names the one that owns it: picking one claims a mapping nobody made. Where the spec's own text and the map disagree, say so in the pull request and have the user say which is right | edit |
| S09 | Read the feature's Status first. Add one `- [ ]` / `- [x]` line per task above the existing table and keep the table as it is. A row that is neither done nor open (partly done, waiting) becomes `- [ ]` with the state in words; in a feature that is `Released` or later an open task is a gap of its own, so list that feature for the user (drop the task, move it to a new feature, or reopen) and leave it under the deviation. A task the user drops or moves leaves the list as row S09 of `STANDARD.md` says, with no checkbox: dropped below a line that starts with `Not done`, or moved under a heading `## Moved out`. A table with no column that says whether a task is done gives no checkbox: leave it for the user, task by task | edit |
| S06 | Features with a plan but no spec: ask the user whether to write the spec from the plan or mark the directory as not a feature and move it | ask |
| S02 | Move detail out of `CLAUDE.md` into the skill that owns the domain, verbatim, leaving a pointer; keep hazards | move |
| S12, S13 | If `docs/ARCHITECTURE.md` already exists without the kit pin, first `git grep -n "ARCHITECTURE.md\|docs/diagrams"` in the project's code, scripts and tests: where a tool of the project reads the old map or every file under `docs/diagrams/`, the move goes in the same commit as the change of that tool and a run of its test (a bare rename leaves that test red), or the map stays as recorded debt naming the tool. Otherwise `git mv` it to `docs/ARCHITECTURE.legacy.md`. Then the `project-mapper` agent writes the map. Older maps stay as they are until the user agrees what to do with each; check which tests read them first | write |
| S10, S11 | Judged only once a feature is `Closed`; before that the doctor skips both and there is nothing to record. Where features are already `Closed`, record both as debt (S11 lists every Closed feature). Not backfilled in bulk. The living spec grows each time `feature-closer` closes a feature, oldest released first | write |
| S16 | Set `interface: true` when people use the project through screens. Write `docs/VOICE.md` from what the product already says: read its locale files, list the forms of address and the names it uses for its things, and ask the user which to keep (`ui-copy`). Write `docs/DESIGN.md` from the screens that exist: the tokens in use and the frame of each kind of page; where pages of different kinds share one frame, say so (`design-direction`). Neither file is invented: what cannot be read from the product is asked | write |
| S18 (`CLAUDE.md` names nothing that is gone) | Correct the path, or drop the sentence when what it pointed at is gone for good; add the manifest's test command or name `.claude/kit.yml`. The words around a path are not read, so a sentence that says a file is gone is reported too: write the name without backticks there. What cannot be fixed now is listed under `names:` | edit |
| S19 (tests run on pull requests) | Make a workflow of the project run each `test` entry on pull requests to `release.pr_target`: the entry word for word in a `run:` step, in the project's directory, its result kept (no `continue-on-error`; the entry is the last command of its line), and in a step that holds only plain commands before it (no pipe, `;`, `if`, function or `$(...)`: a step of its own is the simple way). Or change the entry to the line CI already runs (`make test`), together with `CLAUDE.md` (S18). An entry of one command that names its directory with `uv --directory X`, `go -C X` or `make -C X` directly after the program is run by the same command without the option under `working-directory: X`, and the other way round, so neither CI nor the manifest has to change; `uv --project X`, `npm --prefix X` and an entry `cd X && ...` are matched word for word, so rewriting an entry that way does not make a step under `working-directory: X` prove it. Do not copy into CI an entry written for a person's machine: one that mounts the working tree into a container (`-v "$PWD:..."`) or uses a tool installed on the host runs against a checkout that has no `vendor/` or `node_modules/`, and fails for that reason alone; where CI tests what it built instead, keep the debt and say so in `reason`. A project whose tests run in a workflow of another repository, two calls deep, in an action or in another CI system keeps the debt too: list the entries under `names:` | edit |
| S17 | Add `audit` with the command for each package manager in use and run it. Findings go to the user as a list with the fixed version of each; upgrading is a pull request of its own, not part of adoption | add |
| S14 | Ask the gate question and run the scaffold with `--gate-at` and the answer, which writes that gate; for the workflow the user adds the repository secret `KIT_READ_TOKEN`, and under `runner` sets `KIT_GATE_RUNNER` with the line the scaffold prints; for the hook the user runs the two commands the scaffold prints | add |

Rules for every one of these pull requests:

- Where a machine runs the project from a working tree that a pull, a restart or a watchdog puts live (no deploy branch, a scheduler on the box), merging is not the release, pulling there is: say in the pull request whether it changes anything the running process imports or reads, and leave the pull on that machine to the owner, when the process is stopped. A clone that has diverged from its remote is a merge on pull, not a fast-forward: say so.
- Use `git mv` so history follows the file.
- After a move, search the repo for the old path and fix every reference, including CI path filters and tests that read docs.
- A status you set from old wording is a claim about what shipped. List every feature whose status you inferred and have the user confirm before merge.
- Before advising how to pay a debt, make that change in a throwaway worktree and run the doctor on it; advise only a change the doctor then passes, and say what it printed. A fix read off this table without that try can be one the doctor never accepts.
- Run the manifest's `test` and `lint` and the doctor; paste the output.
- Never commit on a branch in `release.deploy_branches`. In a repository you do not own, open a pull request and stop.

## What adoption does not do

- It does not edit a requirement's text, only where it lives and how its status is written.
- In a project where only people may write specs, the Status, Ticket and checkbox lines are still added by a person or with their explicit go-ahead per pull request.
- It does not delete a project rule. Rules the standard does not cover stay in the constitution or the domain skill.
- Where the project already has a rule on the same question as a kit skill with another number (its own limit on comment lines, its own tone rules), say so in the first pull request and ask which the project keeps. The kit's scripts report by the kit's numbers either way; they are places to look, not a gate.
- It does not mark anything `Closed`. Closing is `feature-closer`'s job, one feature at a time.

## Report

1. Doctor output before and after
2. Deviations recorded, in the order you propose to close them
3. Statuses you inferred, for the user to confirm
4. Project checks you ran or could not run
