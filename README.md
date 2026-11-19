# francis-ai-coworking

A Claude Code plugin, `francis-kit`, for building software with Claude across several projects. It gives every project the same layout and the same way of working, and it ships a doctor that checks a project against that layout.

The kit is built on spec-driven development:

- A change of behaviour starts as a short spec, about 3 to 12 requirements.
- Only a person approves a spec.
- A feature moves through `Draft → Approved → Built → Released → Closed`. Once closed, it is merged into a living spec of what the system does today.

The kit grew out of four real projects, and each rule in it comes from a mistake an agent made in one of them.

It relies on three things it does not ship:

- [Claude Code](https://claude.com/claude-code).
- [Spec Kit](https://github.com/github/spec-kit), whose commands write `plan.md` and `tasks.md`.
- Python 3.9 or newer, with git and PyYAML, for the scripts.

## Install

In Claude Code:

```
/plugin marketplace add dangthinh104/francis-ai-coworking
/plugin install francis-kit@francis-ai-coworking
```

Or let the scaffold write the keys into a project's `.claude/settings.json`, so every collaborator gets the plugin:

```json
{
  "extraKnownMarketplaces": {
    "francis-ai-coworking": { "source": { "source": "github", "repo": "dangthinh104/francis-ai-coworking" } }
  },
  "enabledPlugins": { "francis-kit@francis-ai-coworking": true }
}
```

## Start

- **A new project:** ask Claude to run the `kit-init` skill.
- **A project that already has its own specs, docs or process:** ask for `kit-adopt`. It measures the gaps first, records each gap it cannot close yet as debt with the step that removes it, and closes the gaps one small pull request at a time.
- **At the start of any session:** use the `flow` skill. It says which stage the work is at and what proves that stage is finished.

By hand:

```bash
K=<this repo>/plugins/francis-kit/skills/kit-init/scripts
python3 $K/kit_scaffold.py --repo . --dry-run     # what would be created
python3 $K/kit_scaffold.py --repo .               # profiles: laravel-vue, python, generic
python3 $K/kit_doctor.py --repo .                 # PASS, GAP, DEBT or SKIP for each rule
python3 $K/kit_gate.py --repo .                   # every check, and one verdict line
```

On Windows, where `python3` is often not found, use `python`.

## The standard in one screen

The full text, with rules S01 to S19, is in [`plugins/francis-kit/STANDARD.md`](plugins/francis-kit/STANDARD.md).

```
CLAUDE.md                            short: hazards, rules, where to read next
.claude/kit.yml                      facts about this project, nothing else
.claude/skills/<domain>/SKILL.md     home of the rules for one domain
.specify/memory/constitution.md      non-negotiable principles
specs/NNN-slug/spec.md plan.md tasks.md history.md
specs/_living/<capability>/spec.md   what the system does today
docs/ARCHITECTURE.md                 the map, 200 lines at most
docs/diagrams/map.refs.json          anchored citations for the map
.github/workflows/kit-gate.yml       the gate, on pull requests
.githooks/pre-push                   or the gate at each push
```

Work comes in three lanes:

- **Fix:** a fix that does not change behaviour needs no spec, only a ticked line under `## Fixes` in the feature that owns the behaviour.
- **Spec:** a change of behaviour is one feature.
- **Split:** anything larger is split into at most five features behind one page of intent.

## What is inside

| Type | Name | Purpose |
|---|---|---|
| Skill | `flow` | The loop, and how to find the current stage |
| Skill | `kit-init` | A new project on the standard |
| Skill | `kit-adopt` | An existing project onto the standard, gap by gap |
| Skill | `write-spec` | A request into a spec: the lane, one round of questions, a lint, stop at Draft |
| Skill | `map-project` | An architecture map whose citations can be checked |
| Skill | `close-feature` | After a release: merge the spec into the living spec, trim comments |
| Skill | `find-cause` | Before a fix: show the failure, state the cause with its evidence, stop after three failed fixes |
| Skill | `code-shape` | Checkable rules for simple code |
| Skill | `comment-discipline` | Five rules for comments, and citations of requirements in code |
| Skill | `security` | Input, permissions, secrets, files; adding a package that really exists |
| Skill | `ui-copy` | Words a user reads, in the user's language |
| Skill | `design-direction` | A visual direction before interface code |
| Skill | `shrink-claude-md` | A long `CLAUDE.md` into a short one, block by block, approved by the owner, then verified |
| Skill | `cleanup` | Remove clutter in a scoped area |
| Agent | `spec-writer` | Drafts one spec; never approves |
| Agent | `spec-reviewer` | Reads a spec cold before a person approves it |
| Agent | `project-mapper` | Writes the map in a clean context |
| Agent | `feature-closer` | Closes a released feature in a clean context |
| Agent | `repo-janitor` | Cleans one scoped area |

## The gate

A project chooses one gate, and the scaffold writes it:

- **A workflow** (`.github/workflows/kit-gate.yml`), on GitHub-hosted runners or on a runner of the project's own.
- **A `pre-push` hook** (`.githooks/pre-push`), for a project where no runner can run it.

Both check out this repository at the tag of the kit version that wrote them, and run `kit_gate.py`. A project moves to a newer kit by running `kit_scaffold.py --repo . --gate` again with that version. The doctor reports a gate that pins an older kit as a gap until it moves.

The workflow asks for a repository secret named `KIT_READ_TOKEN` and fails without it. This repository is public, so a token that can read public repositories is enough.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

`sh local-check.sh` runs the suite here, and on Linux with Python 3.9 and 3.12 in Docker.

The kit is developed in a private repository. This copy is published at each release, without history and without the specs and fixtures that came from private projects. Tests that need those files are left out of this copy.

## License

MIT. See [`LICENSE`](LICENSE).
