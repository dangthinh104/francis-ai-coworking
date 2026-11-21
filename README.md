# francis-ai-coworking

A Claude Code plugin, `francis-kit`, for building software with Claude across several projects. It gives every project the same layout and the same way of working, and it ships a doctor that checks a project against that layout.

The kit is built on spec-driven development:

- A change of behaviour starts as a short spec, about 3 to 12 requirements.
- Only a person approves a spec.
- A feature moves through `Draft → Approved → Built → Released → Closed`. Once closed, it is merged into a living spec of what the system does today.

What changed in each version, and what can turn a gate red when you move to it: [`CHANGELOG.md`](CHANGELOG.md).

The kit grew out of four real projects, and each rule in it comes from a mistake an agent made in one of them.

It relies on three things it does not ship:

- [Claude Code](https://claude.com/claude-code).
- [Spec Kit](https://github.com/github/spec-kit), whose commands write `plan.md` and `tasks.md`.
- Python 3.9 or newer, with git and PyYAML, for the scripts.

### Spec Kit and OpenSpec

The kit's living spec works like that of [OpenSpec](https://github.com/Fission-AI/OpenSpec). A feature lists what it adds, modifies and removes, and closing the feature merges that into `specs/_living/<capability>/spec.md`, the description of what the system does today. OpenSpec does the same with the delta specs of a change folder, merged when the change is archived. Anyone who knows OpenSpec will recognise the model.

The kit does not use OpenSpec for two reasons:

- It was built on Spec Kit, whose commands already write the plan and the tasks and build from them. The delta sections are a convention inside a Spec Kit feature, not a second tool.
- Its value is the checks, not the spec format: the doctor's rules S01 to S19, the audit of `CLAUDE.md` against what git once held, the check that a project's tests run on pull requests, and the gate that runs them on every pull request or push. Those would work the same with another spec tool underneath.

One more skill is optional: [archify](https://github.com/tt-a1i/archify), which draws a project's diagrams for `map-project`. Install it on its own. Without it, a session asked for a diagram says so and stops. Checking a diagram (`cite_refs.py`) needs only the kit.

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

## Updates

Claude Code does not update a plugin from this marketplace by itself until you turn that on: auto-update is off by default for third-party marketplaces.

- **Turn on auto-update:** run `/plugin`, open the **Marketplaces** tab, select `francis-ai-coworking`, and switch auto-update on. A new version is fetched in the background, and loads at your next launch or after `/reload-plugins`.
- **Update now:** run `claude plugin marketplace update francis-ai-coworking`, then `claude plugin update francis-kit@francis-ai-coworking`, then start a new session.
- **Be told of a release:** on GitHub, use **Watch → Custom → Releases** for this repository. Each version has a release page, and its section in [`CHANGELOG.md`](CHANGELOG.md) says what can turn red when you move.

A project's gate does not follow the plugin: it checks out the kit at the tag it pins, and moves only when you write the gate again (`kit_scaffold.py --repo . --gate`).

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

## The gate in each project

A project chooses one gate, and the scaffold writes it:

- **A workflow** (`.github/workflows/kit-gate.yml`), on GitHub-hosted runners or on a runner of the project's own.
- **A `pre-push` hook** (`.githooks/pre-push`), for a project where no runner can run it.

Both check out this repository at the commit of the tag of the kit version that wrote them, and run `kit_gate.py`. The file names the commit and keeps the tag beside it: `ref: <commit>  # v<version>`, or `KIT_COMMIT=` beside `KIT_REF=` in the hook. A project moves to a newer kit by running `kit_scaffold.py --repo . --gate` again with that version. The doctor reports a gate that pins an older kit as a gap until it moves.

Neither gate needs a secret: the kit is public. The workflow does not start on pull requests from a fork or from Dependabot.

The gate runs the kit at the commit its file names, so a tag moved later does not change what it runs. The version beside the commit is checked by the gate itself: the doctor it runs is the kit at that commit, and it reports a pin whose version is not its own. The tags of this repository are still never moved: a fix is a new version.

Writing a gate reads the source over the network, with read access to it: the scaffold runs `git ls-remote` on this repository, or on what `git config kit.gateSource` names, with no prompt and 60 seconds at most, and writes nothing when it cannot read the commit of the tag. A cache of the hook named by a tag (`.git/kit-gate/v<version>`, before 0.18.0) is no longer used and may be deleted.

When a project moves to a newer kit, it writes its gate again before it records a second deviation on a rule. The gate runs the doctor of the version it pins, and an older doctor reports that entry as listed twice.

## Known limits

- The doctor checks structure, not truth. It cannot tell whether a `Released` feature really shipped, or whether the living spec is right. Review and the `feature-closer` agent cover that.
- The gate does not run a project's tests.
- S19 checks that the tests run on pull requests, and it does this by reading the workflow files under `.github/workflows` word for word. A project whose CI is elsewhere records S19 as debt.
- The hook guards the author's clone, not the release: `git push --no-verify` skips it, and a merge in GitHub's web interface is not judged.
- The plugin's hook raises a permission prompt before an Edit or Write adds an `Approved` Status line to a `specs/NNN-*/spec.md` that did not hold one. The prompt is a confirmation, not the approval: the approval is still the person's yes to the question that names the feature, its number of requirements and that no open question is left (`STANDARD.md`, Status). The hook asks and never refuses or allows; where it fails while checking a spec, it asks and names the error.
- What the hook does not see. With no Python, or a plugin root that does not lead to `hooks/guard.py`, nothing is checked and nothing says so. A spec written through Bash or PowerShell (`sed`, `echo >`, `Set-Content`) is not seen, nor one written by NotebookEdit. MultiEdit is not matched: in a Claude Code version that still has it, it is a way around the hook. The path rule reads the path as text, so an alias of a spec's path is not recognised and raises no prompt: on Windows a trailing dot (`spec.md.`), a stream name (`spec.md::$DATA`), an 8.3 short name (`SPEC~1.MD`); on any system a symlink (on Windows also a junction) that leads to the spec. A line the person writes in their own editor raises no prompt, and that line is the approval. A subagent's write is asked like any other, because the input does not say it comes from a subagent; the prompt's reason says it is not an approval. A Status line the kit does not read (indented, or in front matter, a closed fenced block, a code span or an HTML comment) raises no prompt. On Windows without Git Bash, what happens to the hook's command is unverified. In `dontAsk` mode Claude Code refuses whatever would prompt, so the prompt becomes a refusal; what `bypassPermissions`, `acceptEdits` and plan mode do with it is unverified, and a `deny` rule in the settings still wins. The hook cannot be turned off on its own: disabling the plugin, or setting `disableAllHooks`, turns it off. It sets no timeout, and what Claude Code's default timeout does to it is unverified.
- The other rules that hold within a session are in the skills, not in a hook. No gate can check them.
- The test suite needs the full git history. On Windows without the symlink privilege, the tests that create a symlink are skipped one by one. A run that skipped more tests than it ran exits 1.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

`sh local-check.sh` runs the suite here, and on Linux with Python 3.9 and 3.12 in Docker.

The kit is developed in a private repository. This copy is published at each release, without history and without the specs and fixtures that came from private projects. Tests that need those files are left out of this copy.

## Author

Francis Dang, [francisdang.com](https://francisdang.com).

## License

MIT. See [`LICENSE`](LICENSE).
