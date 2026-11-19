# The francis-kit standard

One layout and three conventions for every project. A project conforms to this; the kit does not adapt to a project. `kit_doctor.py` checks every rule below by its id.

Where a project cannot conform yet, the gap is listed under `deviations` in `.claude/kit.yml` with the step that removes it. A listed deviation is debt, not a variant. A deviation on a rule that names things (S04 to S09, S11) lists exactly the names it covers under `features:`; one on S18 lists the paths and commands the doctor reports under `names:`; one on S19 lists there the `test` entries no step runs. A name the doctor reports that is not listed is a gap, and so is a listed name that conforms now, so the list only shrinks. A rule that names things (S04 to S09, S11, S18, S19) may have several entries, each with its own reason, fix and names; a name held by two entries is a gap of S01. S01 cannot be a deviation.

## Layout

Paths are from the project root (the git root, or the entry's `root` in a monorepo). `.claude/` is always at the git root.

```
CLAUDE.md                            short: hazards, rules, where to read next
.claude/kit.yml                      facts about this project, nothing else
.claude/settings.json                registers the kit
.claude/skills/<domain>/SKILL.md     home of the rules for one domain
.specify/memory/constitution.md      non-negotiable principles
specs/NNN-slug/spec.md               one directory per feature
specs/NNN-slug/plan.md  tasks.md     written after approval, required from Built on
specs/NNN-slug/history.md            what happened: incidents, measurements, dates
docs/history.md                      the same, for code no feature owns
specs/_living/<capability>/spec.md   what the system does today
docs/ARCHITECTURE.md                 the map, 200 lines at most
docs/VOICE.md                        how the product talks to its user (when it has an interface)
docs/DESIGN.md                       the design direction and one frame per kind of page (same)
docs/diagrams/map.refs.json          anchored citations for the map
.github/workflows/kit-gate.yml       runs the checks below on pull requests
.githooks/pre-push                   or runs them at each push, under gate: hook
```

## Conventions

1. **Status.** `spec.md` carries the line `**Status**: <value>`, alone on its line, with one of `Draft`, `Approved`, `Built`, `Released`, `Closed`, in English. Two more values end a feature outside that sequence: `Superseded` and `Dropped`. Anything else worth keeping (a commit, "superseded by 035") goes on a `**Status note**:` line below it.
   Who moves it: the author writes `Draft`; only a person sets `Approved`; the session that finishes the tasks sets `Built`; whoever merges the release sets `Released`; `feature-closer` sets `Closed`; a person sets `Superseded` or `Dropped`. Nothing is built from a `Draft`. A fix moves no Status.
   A person sets `Approved` by writing the line, or by answering yes to the one question in which a session names the feature, its number of requirements and that no open question is left; the session then writes the line and adds under Decisions who approved and on which date. A go-ahead given before that question is not an approval, and a subagent never writes the line.
2. **Ticket.** `spec.md` carries the line `**Ticket**: <id>`. `none` is allowed while the feature is a `Draft`. A project whose `tracker.type` is `none` needs no Ticket line at all. From `Approved` on, in a project with a tracker, the id matches `tracker.id_pattern`.
3. **Tasks.** `tasks.md` uses `- [ ]` and `- [x]`. A `Released` or `Closed` feature has no open task.

**Ids are for machines, words are for people.** A rule (`S07`), a requirement (`005/FR-003`) or a task (`T012`) named to a person carries what it says the first time it appears: `S07 (the Status line)`. The doctor prints its rules that way.

**Branches.** Nothing is committed on, or pushed to, a branch listed in `release.deploy_branches`; work reaches it through a pull request to `release.pr_target`. Where that target is itself a deploy branch, merging is releasing, and the merge is the owner's. Skills and agents repeat the first half as a reminder; this paragraph is the rule.

Requirement ids (`FR-001`, `SC-001`) are numbered per feature. Outside its own spec a requirement is cited as `NNN/FR-001`.

### Citing a requirement

- In code and tests the citation is `NNN/FR-001`, on one line, with no prose around it that retells the requirement.
- A test names the requirement it proves. Production code names one only on the class or function that enforces a business rule, never line by line.
- A requirement keeps its id for life. When a later feature changes it, the living spec keeps the original `NNN/FR-001`, carries the new text, and lists the later feature as a further origin.
- `spec_refs.py --check` counts citations that lead to no single requirement and fails when the count rises above the recorded baseline; a citation in the standard form that points at nothing always fails. A requirement no test cites is listed as a warning.

### After a feature is closed

A `Closed` feature is a record. In its `spec.md` only the Status lines change; its `tasks.md` gains lines under `## Fixes` and nothing else; `history.md` may grow. What the system does now is edited in `specs/_living/`. A feature written after this rule records what it changes under `## Added`, `## Modified` and `## Removed`, so that closing it is a merge and not a rewrite. Earlier features are not rewritten to fit.

`specs/INDEX.md` is generated by `spec_index.py`; nobody edits it.

An agent drafts a spec only when asked to and where the project allows it, follows `write-spec`, and stops at `Draft`. `spec_lint.py` checks what the lines of a spec say: its size, its one capability, its open questions and its fix lines.

What a status switches on: `plan.md` and `tasks.md` are required from `Built` (S06), the ticket pattern applies from `Approved` (S08), and open tasks are forbidden from `Released` (S09). A feature that is `Superseded` or `Dropped`, or whose status is not valid yet, is exempt from those three checks; S07 is what catches the invalid status. The living spec is read one level deep: `specs/_living/<capability>/spec.md`.

The doctor checks the rules in the table. The numbering of requirement ids, the use of `history.md` and the shape of `specs/_living/` are conventions for people and reviewers; no script checks them yet.

## Three lanes, by the size of the work

Not every change needs a spec, and one spec is not allowed to carry everything. The test is whether the behaviour of the system changes.

| Lane | When | What it needs |
|---|---|---|
| **Fix** | Behaviour does not change: a bug fixed back to what the spec already says, a typo, formatting, a comment, a non-breaking dependency update, configuration, a test for behaviour that already exists | No spec. One task under `## Fixes` in the `tasks.md` of the feature that owns the behaviour, and the ticket id when the project has a tracker |
| **Spec** | Behaviour changes: something the system does is added, modified or removed | One feature: one `spec.md`, about 3 to 12 requirements, one capability named on a `**Capability**:` line |
| **Split** | More than 12 requirements, or two capabilities, or more than one pull request a person can review | One page of intent (the problem, what is in, what is out), then at most five features, each one deliverable on its own |

### A fix belongs to a feature

A fix is attached to the feature whose requirement the code was breaking. Find it from the origin the living spec gives the requirement (`specs/NNN-slug`), or from the feature that declares it. The pull request adds one line to that feature's `tasks.md`, under a heading `## Fixes`, already ticked:

```
## Fixes

- [x] SCRUM-412 Late fee was charged twice when a payment was split (005/FR-003)
```

- The line names the ticket, says what was wrong in the user's terms, and cites the requirement as `NNN/FR-001`. The test that would have caught it carries the same citation.
- The task is ticked in the same pull request that fixes it, so a `Released` or `Closed` feature never holds an open task (S09). `spec.md` of a closed feature still does not change.
- A fix moves no Status. The feature stays `Released` or `Closed`; only the line under `## Fixes` is new.
- Work that restores no requirement because it is not about the product's behaviour (a typo, formatting, CI, tooling, a dependency update) has no feature to attach to and needs no task line: the pull request and its ticket are the record.
- If no requirement says what the right behaviour is, this is not a fix: the behaviour is new, and it goes through the Spec lane.
- If the fix shows the spec itself was wrong, correct the living spec in the same pull request and say so in the task line. No new feature is needed for that.
- A change in the Fix lane that adds a route, a screen, a column, a permission or an option has left the lane. The reviewer sends it back.

The number of lines under `## Fixes` is how many times a feature had to be repaired after release: read it before trusting a feature, and before planning the next one in the same area.

## Rules

| Id | Rule |
|---|---|
| S01 | `.claude/kit.yml` exists, is version 2, has no unknown keys, and each project has `name`, `interface` (true or false), a `root` inside the repo, a `test` that runs something and whose entries join commands with `&&` only (the exit status of `a || b`, `a; b`, `a | b` or `a &` is not the tests'), `release.pr_target`, `release.deploy_branches`, `tracker.type` and, unless that is `none`, `tracker.id_pattern`; every deviation has `rule`, `reason`, `fix`, is listed once on a rule that names nothing, and names what it covers where the rule names things. A rule that names things (S04 to S09, S11, S18, S19) may have several entries, each with its own reason, fix and names; a name held by two entries is a gap of S01. |
| S02 | `CLAUDE.md` exists, is 150 lines at most, and has no blank of the kit template left unfilled |
| S03 | `.specify/memory/constitution.md` exists and has no blank of the kit template left unfilled |
| S04 | `specs/` holds only `NNN-slug/` directories, `_living/`, `README.md`, the generated `INDEX.md` and `.kit-refs-baseline.json`; no number is used twice |
| S05 | No feature lives under `.specify/specs/` |
| S06 | Every feature has `spec.md`; from `Built` on it also has `plan.md` and `tasks.md` |
| S07 | Every `spec.md` has exactly one valid Status line, outside comments and code blocks |
| S08 | In a project with a tracker, every `spec.md` has a Ticket line, and from `Approved` on it matches the tracker pattern. Not judged when `tracker.type` is `none` |
| S09 | `tasks.md` lists its tasks as checkboxes (`- [ ]` / `- [x]`), not counting `## Fixes`; `Released` and `Closed` features have no open checkbox anywhere in the file. A line with no checkbox is not a task. A task that will not be done leaves the list in one of two ways, with no checkbox: dropped, below a line that starts with `Not done` and says that it is no longer open, why, and what it does not prove; or moved, under a heading `## Moved out`, below a line that names the spec or feature that takes each, or says that each needs its own spec. A `tasks.md` still holds at least one checkbox, so a feature none of whose tasks was done is `Dropped` or keeps a checkbox for the work it did |
| S10 | Once a feature is `Closed`, `specs/_living/` has at least one `<capability>/spec.md` |
| S11 | Every `Closed` feature is cited in `specs/_living/` as `specs/NNN-slug` |
| S12 | `docs/ARCHITECTURE.md` exists, starts with the kit pin, and is 200 lines at most |
| S13 | `docs/diagrams/map.refs.json` exists and carries a commit as its pin |
| S14 | The project's gate is the gate of the kit version it pins: the kit's template, unchanged. Where the manifest has no `gate`, or `gate: workflow`, it is `.github/workflows/kit-gate.yml`, with `ref:` set to a tag. With `gate: hook` it is `.githooks/pre-push`, with `KIT_REF=` set to a tag, held by git's index with mode `100755`; it guards the author's clone, not the release: a merge in GitHub's web interface and a push from a clone that has not switched the hook on are not judged. A project holds one gate: the file of the other gate is a gap where it is there (under `workflow`, only a `pre-push` that holds a `KIT_REF=` line, the kit's hook) |
| S15 | `.claude/settings.json` registers the marketplace and enables the plugin |
| S16 | A project with `interface: true` has `docs/VOICE.md` and `docs/DESIGN.md`: no line of the template left unfilled, and at least three lines of text each |
| S17 | Each project names under `audit` at least one command that checks its dependencies for known vulnerabilities; that command runs something, and each entry joins commands with `&&` only, so its exit status is the audit's. Skipped where no audit is named and git tracks no dependency manifest for the project (`requirements*.txt`, a `requirements/` directory of `.txt` files, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `composer.json`, `composer.lock`, `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`, `Gemfile`, `Gemfile.lock`, `pubspec.yaml`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `*.csproj`). A manifest in the project's root or above it, up to the git root, is the project's; one below the root of another listed project is that project's |
| S18 | `CLAUDE.md` names nothing that is gone: no path git once held and that was deleted or moved, no skill or agent of the project that does not exist, and each `test` command of the manifest is in the file or the file names `.claude/kit.yml`. The words around a path are not read: to write of a thing that is gone, write its name without backticks, or list it under `names:` of a deviation on this rule. In a repository of several projects the file at the git root is judged too, with the 150 lines of S02; a deviation for that file goes in the top-level `deviations` list. Without the whole history (a shallow clone) the rule is skipped, not passed |
| S19 | Each `test` entry of a project is run on pull requests by the project's own CI: a `run:` step of a workflow file under `.github/workflows` holds the words of the entry, in order and with its own `&&` (assignments such as `CI=1` in front of a command are left out), as the last command of its line, and the workflow's `on` names `pull_request` with no `branches` filter or with one that lists `release.pr_target` by name, and with no `types` list that leaves out `synchronize`. A step is read line by line, in `bash` or `sh`, and only while its lines are plain: empty, a comment, or one simple command; the last line of the step may join several with `&&`. A step that holds anything else before the entry or with it (a pipe, `;`, a group, an `if`, a function, a substitution, a heredoc, `set +e`, a `cd` that is not one path written out) is named as not judged, with the line. A step does not count under `continue-on-error` (unless `false`) or `if: false`, on itself or on its job, nor when the directory its command names is not the directory the entry names, the project root for an entry with no directory option (where a command runs is read from `working-directory` on the step, `defaults.run.working-directory` or a plain `cd <path>` before it, and joined with the path of its directory option). A directory option is `uv --directory <path>`, `go -C <path>` or `make -C <path>` written directly after the program, the path a word of its own, written out, inside the repository and followed by another word; it is read only in an entry of one command and in the command of a step that is matched against one: the entry `uv --directory api run pytest -q` is run by the step `uv run pytest -q` under `working-directory: api`, and the entry `go test ./...` of a project at `api` by the step `go -C api test ./...` at the git root. Every other way to name a directory is matched word for word: `uv --project X`, `uv --directory=X`, `uv run --directory X`, `go -CX`, `make --directory X`, `npm --prefix X`, `pnpm -C X`, and an entry `cd X && ...`, which no step under `working-directory: X` runs. A job of a workflow that counts which calls a workflow file of the same repository (`uses: ./.github/workflows/<file>`) is followed, one level deep: the `run:` steps of that file are read the same way, and where they run is read from that file alone. It is followed only when the file is there, can be read as a workflow and holds `workflow_call` under `on`, and the calling job is not under `if: false` or `continue-on-error`. Every other `uses:` on a job (a workflow of another repository, a path below `.github/workflows`, a call made by a called file or by a workflow that does not count), a job that holds a step using a local action (`uses: ./...`), and a workflow file that cannot be read as one, are named as not judged. The gate runs no test of a project. Skipped where the project has no `test` entry or no `release.pr_target`, which S01 reports |

## Two layers

**The frame** is this repository: the layout, the conventions, the rules, the loop, the skills and the scripts. It is the same in every project and is never edited inside one.

**The project's own files** are what running the frame leaves behind in a repository. They are how the same frame fits different projects:

| File | Holds | Written by |
|---|---|---|
| `.claude/kit.yml` | Facts: commands, branches that deploy, tracker, `interface`, recorded debt | `kit-init` or `kit-adopt`, from the user's answers |
| `CLAUDE.md` | What must never break, and where to read next | the same, with the user |
| `.specify/memory/constitution.md` | The project's own principles | `kit-init` from the user's answers; changed afterwards only by a person, through a pull request |
| `.claude/skills/<domain>/` | The rules of one domain of this project; each correction from the user adds a line | whoever works in that domain |
| `docs/ARCHITECTURE.md`, `docs/diagrams/` | The map, traced from the code | `project-mapper`, in a clean context; a session that did not write the code may run `map-project` itself |
| `docs/VOICE.md`, `docs/DESIGN.md` | How the product talks and looks | with the user |
| `specs/_living/` | What the system does today | `feature-closer`, one closed feature at a time |
| `specs/INDEX.md`, `specs/.kit-refs-baseline.json` | Generated | the scripts |

A project file holds facts and knowledge about that project. It never holds an alternative to the frame: a different layout, another status vocabulary, a rule switched off. Where a project cannot follow the frame yet, that is a deviation with a fix, not a setting.

The constitution and the domain skills add to the standard; they do not replace its layout or conventions.
