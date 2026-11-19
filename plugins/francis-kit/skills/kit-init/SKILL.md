---
name: kit-init
description: Start a NEW project on the francis-kit standard, or give a repository that has no process files its first standard layout. Use when a repo has no .claude/kit.yml and no specs, when asked to init, bootstrap or scaffold a project with the kit. For a project that already has specs, docs or its own process, use kit-adopt instead.
---

# Init a project on the standard

The standard is `${CLAUDE_SKILL_DIR}/../../STANDARD.md`: one layout, three conventions, rules S01 to S19. Read it first. The project conforms to it; nothing here is adapted per project except the facts in `.claude/kit.yml`.

If the repo already has `specs/`, `.specify/`, an architecture doc or a long CLAUDE.md, stop and use `kit-adopt`: this skill never moves or rewrites existing files.

## Read, ask once, then run

Three phases. The user answers one round of questions; after that you run to the end without asking again. If an answer contradicts what you then find in the repository, stop and say so: that is not a new question, it is a wrong fact.

### 1. Read

```bash
top=$(git rev-parse --show-toplevel)
python3 "${CLAUDE_SKILL_DIR}/scripts/kit_detect.py" --repo "$top"
```

It prints what the repository itself says: profile, sub-projects one level down, the commands that exist, the default branch, every workflow a push can start (`push_workflows`, each with the words that suggest it deploys), the ticket pattern in recent commits, interface frameworks and languages, where the gate is suggested to run (`gate_choice`, read from `workflows` and `hook_manager`), and `warnings` for what it could not read.

- `already_has` is not empty, or a sub-project has `has_process`: stop and use `kit-adopt` for that project.
- `sub_projects` is not empty: this may be a monorepo. Run the script again with `--project-root <dir>` for each one the user wants on the standard, and ask the questions per project.
- A reading is a suggestion. `push_workflows` lists every workflow a push starts, whether or not it looks like a deploy: `deploy_hints` is a word match and can be empty for a workflow that does deploy. Open each one that is not plainly a test or lint run. `starts_on` that says `all`, has `ignore` or `tags`, or says "check by hand", and every line in `warnings`, means the script could not name the branches: read the workflow before suggesting anything.

### 2. Ask once

Ask everything in one round (the question tool when it is available, otherwise one numbered message). Every question carries the reading from phase 1 as its suggested answer, so the user confirms more than they type. Ask only what the repository cannot tell you:

1. **Project**: name and profile, and in a monorepo which directories are projects. Suggested: the reading.
2. **Release**: which branch pull requests target, and which branches deploy when pushed. Suggested: the default branch and the branches of the workflows you judged to deploy; show the user the list of push workflows you set aside as not deploying. The default branch is often not the pull-request target, so always ask. "Nothing deploys" is a valid answer only when the user says so.
3. **Tracker**: Jira, GitHub, Azure DevOps, Monday or none, and what a ticket id looks like. Suggested: the pattern seen in commits, which can be a code word of the project and not a ticket: say where you saw it. Never write `tracker` from the reading alone: `none` is an answer the user gives, not a default.
4. **What must never break**: money, data that cannot be recomputed, production, anything irreversible. These become the hazards in `CLAUDE.md`. Do not invent any.
5. **Tests and a database**: only when a test command touches one. Which database do tests use, and where is that pinned? No proof, no command.
6. **Interface**, only when the reading found one or the user says there is one:
   - who reads the screen, and what they are doing when they do;
   - the languages, and how the product addresses its user in each;
   - three words for the tone, and five to ten words the product has its own name for;
   - whether a design direction exists: a Figma file, a brand guide, an existing product to match, or none yet.
7. **Gate**: where the standard is checked on each change, one answer per repository, also in a monorepo. Ask all of it in this same round, in this order:
   - First `Does GitHub start jobs on GitHub-hosted runners (such as ubuntu-latest) for this account?`, with the answers yes, no and don't know. The repository cannot tell; only the user can.
   - Then where the gate runs, suggested as `gate_choice` gives it for that answer (its `yes` for yes, its `no` for no and don't know), with its `why`; where that suggestion is null, suggest none and say why. The user may answer otherwise. The answers offered:
     - `hosted`: the workflow `.github/workflows/kit-gate.yml` on GitHub's runner `ubuntu-latest`; no variable is set.
     - `runner`: the same workflow on a runner of the project's own, chosen by the repository variable `KIT_GATE_RUNNER`, which a person sets with the line the scaffold prints; whoever may push a branch can then run a step on that runner by a pull request (README, "The gate in each project").
     - `hook`: `gate: hook` in the manifest and the git hook `.githooks/pre-push`, which runs the checks on each developer's machine at each push. Say it plainly before the user chooses: the hook guards the author's clone, not the release; a merge in GitHub's web interface and a push from a clone that has not switched it on are not judged.
   - Where `hook_manager` is not empty (`gate_choice` row 1), offer only `hosted` and `runner`: the kit's hook would replace the hooks that already run there.
   - For a `runner` answer, its labels: suggested as the `labels` of `gate_choice` where they are not null, whatever was suggested; where they are null, asked with no suggestion.

Do not ask about anything the standard already fixes: the layout, the status values, where specs live.

One decision is deliberately left for later: when no design direction exists, choosing one needs samples the user can look at. That happens before the first screen is built (`design-direction`), not here.

### 3. Run

1. Work on a branch, never on a branch that deploys.
2. Scaffold with the answer to the gate question. The script creates what is missing and never overwrites:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/kit_scaffold.py" --repo "$top" --gate-at <answer> --dry-run
   python3 "${CLAUDE_SKILL_DIR}/scripts/kit_scaffold.py" --repo "$top" --gate-at <answer>
   ```

   `<answer>` is `hosted`, `runner` or `hook`. For `runner` add one `--runner-label <label>` per label, in the order given (`--runner-label self-hosted --runner-label team-runner`), never one text that holds a comma. The scaffold writes `gate:` into the manifest and the gate file of the answer. Where the answer cannot be written it refuses and writes nothing; its line says what to do first: pass it to the user. The profile (`laravel-vue`, `python`, `generic`) is detected; pass `--profile` when the user chose another.
3. Write the answers into `.claude/kit.yml`:
   - `audit`: one command per package manager the project uses (`pip-audit`, `uv run pip-audit`, `npm audit --audit-level=high`, `composer audit`, `govulncheck ./...`). Run it once now and paste the output; what it reports is the user's to decide, not a reason to leave the key empty.
   - `setup`, `test`, `lint`: the exact commands, non-mutating (`pint --test`, not `pint`), each one present in this repo.
   - The deviation on S19 (tests run on pull requests) that the `python` and `laravel-vue` profiles write: its `names:` lists exactly the `test` entries no workflow of the project runs on pull requests to `release.pr_target`. Change it with `test`: add the entries you added, and add the whole entry in a `generic` project once `test` is filled. The scaffold writes no CI workflow; where one already runs an entry word for word, as the last command of its line, leave that entry out, and remove the deviation when none is left.
   - A test command that touches a database goes in only with proof that it uses an isolated one: quote the lines of `phpunit.xml`, `.env.testing` or the test settings that pin it. Laravel tests with `RefreshDatabase` wipe whatever database `.env` names. No proof: leave the command out and say so.
   - `release.deploy_branches` and `release.pr_target` as answered. The template leaves both blank so the doctor fails until they are filled.
   - `tracker`: the type and the id pattern, quoted (`'SCRUM-\d+'`, `'#\d+'`).
4. Fill the `CLAUDE.md` and constitution the scaffold just wrote (what the project is, the hazards as answered, the project principle). Then run `python3 "${CLAUDE_SKILL_DIR}/scripts/claude_md_audit.py" --repo "$top"` and paste its output: the file every session will read names nothing that is not there (S18). The doctor fails S02 and S03 while a blank of the template (`<...>`) is left, so an answer the user did not give is asked, not skipped. A file that existed before the scaffold is left as it is: say so and name it.
5. When the project has an interface: set `interface: true` in the manifest, write `docs/VOICE.md` from `${CLAUDE_SKILL_DIR}/../ui-copy/templates/VOICE.md` filled with the answers, and copy `${CLAUDE_SKILL_DIR}/../design-direction/templates/DESIGN.md` to `docs/DESIGN.md`. With a direction given, fill it in and make sure no S16 deviation is listed. Without one, leave the template and record S16 under `deviations` (the `laravel-vue` profile already lists it; add it for the others): the first screen is not built until that debt is paid. When the project has no interface, set `interface: false`.
6. Spec Kit commands: if the project has none, tell the user to run `specify init --here` themselves and to keep the constitution and layout this scaffold wrote (features in `specs/`, not `.specify/specs/`). Do not run it for them: it may overwrite files.
7. Check and paste the output:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/kit_doctor.py" --repo "$top"
   ```

   Expected on a new project: S12 and S13 as `DEBT` (no map yet), S19 as `DEBT` while no workflow of the project runs its `test` entries on pull requests, S16 as `DEBT` when the project has an interface and no direction was given, everything else `PASS` or `SKIP`. Any `GAP` is yours to fix now. Under `hook`, run `git add --chmod=+x .githooks/pre-push` before the doctor: S14 reports a hook git does not hold executable.

   In a monorepo run the scaffold once per project with `--project-root <dir>`, and add each project's entry to the manifest.
8. The gate. Under `hosted` and `runner` the workflow reads the public kit and needs no secret. The gate does not start on pull requests from a fork or from Dependabot. Under `runner` the scaffold's last two lines are the `gh variable set KIT_GATE_RUNNER` command for the labels and the note that the kit sets nothing on GitHub: give the user both; you do not run it. Under `hook`, tell the user the two commands the scaffold prints (`git add --chmod=+x .githooks/pre-push`, and `git config core.hooksPath .githooks` in each clone) and that every developer then needs Python with PyYAML and read access to the kit's repository.
9. Commit on the branch and report: what was written, what the user still has to do (`specify init`, a workflow that runs the tests on pull requests), and the next stage. Next: the `flow` skill. Once there is code, the `project-mapper` agent writes the map and the two deviations are removed.

## The manifest

`.claude/kit.yml` holds facts, never alternatives:

| Field | Meaning |
|---|---|
| `name`, `root` | Project id and directory from the git root |
| `setup`, `test`, `lint` | Lists of exact commands, run from `root` |
| `audit` | The commands that check dependencies for known vulnerabilities, one per package manager in use (S17). Run them before a pull request that adds or upgrades a package, and in CI |
| `ci_only` | Gates only CI can run, by name |
| `version` | Always `2`, at the top level |
| `gate` | Top level: `workflow` (the default, `.github/workflows/kit-gate.yml`) or `hook` (`.githooks/pre-push`, run at each push where no runner can run the gate). A project holds one gate |
| `interface` | `true` when people use the project through screens; then S16 applies |
| `tracker.type`, `tracker.id_pattern` | Where tickets live and what an id looks like |
| `release.pr_target`, `release.deploy_branches` | Where PRs go; branches whose push deploys |
| `deviations` | Rules this project does not meet yet: `rule`, `reason`, `fix`, and for S04 to S09 and S11 the exact names covered (`features: [...]`), for S18 and S19 under `names: [...]`. S14 and S15 go in a top-level `deviations` list. A rule that names things (S04 to S09, S11, S18, S19) may have several entries, each with its own reason, fix and names; a name held by two entries is a gap of S01. |
| `scratch` | Paths no build, test or deploy reads |

A monorepo lists one project per entry; each entry has its own standard layout under its `root`.
