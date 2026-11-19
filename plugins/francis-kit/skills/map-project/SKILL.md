---
name: map-project
description: Create or refresh a project's architecture map with file citations that can be checked. Use when the architecture map is missing or stale, before any cleanup, when onboarding to a codebase, when asked to map, document or explain the project structure, and when asked for a diagram of the project or about one it has.
---

# Map a project

The map is what every later agent reads first. It must be short, cited, and able to fail when it goes stale.

The map lives at `docs/ARCHITECTURE.md` and its citations at `docs/diagrams/map.refs.json`, under the project root (STANDARD rules S12, S13). In a monorepo work on one project entry of `.claude/kit.yml` per run. Below, `<root>` is that entry's `root`.

## Two kinds of citation

- **Path citations** in the Markdown map: a path in backticks, written from the project root. `map_check.py` checks the path exists.
- **Anchored citations** in JSON under `docs/diagrams/`: `{"path", "line", "end_line", "label"}` inside `sources` lists, with the commit in `meta.repository.revision`. `cite_refs.py` reads the cited line's text at that commit and looks for it in the working tree, so it can tell moved from lost and re-point what moved.

**Anchored paths are written from the git root**, because git reads them. In a monorepo that means `<root>/src/app/main.py`, not `src/app/main.py`. This is the only place the kit uses git-root paths.

Anything that names a line belongs in an anchored citation. The Markdown map names files, not lines.

## Does a map already exist?

- `docs/ARCHITECTURE.md` exists and its first line carries the kit pin: yes. Go to Refresh.
- `docs/ARCHITECTURE.md` exists without the pin: stop. It is someone's document; `kit-adopt` moves it to `docs/ARCHITECTURE.legacy.md` first.
- Anything else that describes the architecture (a root `ARCHITECTURE.md`, a project-context page, a codebase skill) is input. Read it, trace the code, and write the standard map. Do not delete or edit the older document: list it in your report.
- Nothing: go to Writing a new map.

## Writing a new map

Trace, do not summarise the README. Open the entry points and follow real calls.

Write `<root>/docs/ARCHITECTURE.md` with exactly these sections, 200 lines at most:

1. **Purpose**: what the system does and for whom, 3 lines.
2. **Layout**: top-level directories and the role of each.
3. **Entry points**: every way the system starts (CLI, scheduler, HTTP, CI job).
4. **Main flows**: 2 to 5 flows, each as numbered steps from trigger to output.
5. **Key files**: table of file and why it matters. Include what this project actually has: constitution, spec index, CI gates, env examples, migrations, schedulers, generated-file sources.
6. **Rules home**: where each kind of rule lives.
7. **Danger zones**: code that moves money, changes permissions, deletes data, sizes a trade, or deploys. Name the files.
8. **Not covered**: what this map leaves out on purpose.

Rules for the text:

- First line: `<!-- kit:map revision=<full commit sha> -->`, the commit you read.
- Backticks with a slash are reserved for repo paths. Write a URL with a leading slash (`/api/v1`), and leave MIME types, import paths and git refs out of backticks.
- Each entry point, flow step and danger zone has a backticked path, or an anchored citation whose label names the step. The line count, the section list and this pairing are review rules: no script checks them.
- No counts, durations or dates. No line numbers in prose.

Write `<root>/docs/diagrams/map.refs.json`:

```json
{
  "meta": { "repository": { "revision": "<full commit sha>" } },
  "sections": [
    { "label": "Entry points",
      "sources": [ { "path": "<root>/src/app/main.py", "line": 42, "end_line": 60, "label": "CLI entry" } ] }
  ]
}
```

Cite a line with substance: a `def`, a `class`, a call, a named key. It needs at least 6 non-space characters, so cite `name: Deploy`, not `i18n:` or a lone bracket. A label may say `Name :123` for a definition in a cited file; the checker verifies that form for common definition keywords and nothing else in a label.

## Diagrams

A diagram of the project is made with the `archify` skill and with nothing else: no Mermaid block, no ASCII drawing, no SVG or HTML written by hand, in the map, in a spec or in an answer. When asked to draw or change a diagram, load `archify`. Where it is not installed, say so, name where it comes from (https://github.com/tt-a1i/archify, tried with 3.2) and stop: draw no substitute. The map itself needs no diagram: without archify, write the map and say that no diagram was drawn.

When asked about a diagram the project has, read its JSON under `<root>/docs/diagrams/`, not a rendered page, and run `cite_refs.py --diagrams <root>/docs/diagrams --root <root> --check` before repeating what it says: a diagram whose citations fail is not an answer. Checking needs no archify.

With archify, produce one architecture diagram and one per main flow under `<root>/docs/diagrams/`, following archify's repository-authoring path so each node carries `sources`. Archify candidates are citation files as they are, in whatever sub-folders archify uses: `cite_refs.py` finds them recursively. Track the JSON, not the rendered HTML.

## Verify

A shallow clone cannot verify pins. Run `git rev-parse --is-shallow-repository`; if `true`, deepen first (`git fetch --deepen=1000` or the project's own way).

Commit the map and the citation files on the current branch (never a branch in `release.deploy_branches`, never push), then run and paste all of:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/map_check.py" <root> docs/ARCHITECTURE.md
python3 "${CLAUDE_SKILL_DIR}/scripts/cite_refs.py" --diagrams <root>/docs/diagrams --root <root> --check
python3 "${CLAUDE_SKILL_DIR}/scripts/cite_refs.py" --diagrams <root>/docs/diagrams --root <root> --report
```

All must be green. Reading the output:

- `map_check.py`: `BROKEN` fails. `UNCHECKED` is a path not written from the project root: rewrite it. `REVIEW` lists cited files that changed since the pin: re-read those sections. Right after the first commit the changed count is the map's own files.
- `cite_refs.py --check` exits 1 for `lost`, `file gone`, `past eof`, `ambiguous`, `weak anchor`, a path outside the repository, a wrong `Name :123`, or when it finds no citation file at all, and prints each failing citation; 2 when a file is unreadable, malformed, a symlink, cites nothing, has `sources` without a commit as its pin, or the pin is not in the clone.
- `--report` also shows `moved`, which does not fail (run `--fix`). For `ambiguous` and `weak anchor`, re-cite a longer or more distinctive line: `--fix` will not touch that file until you do.

## Refresh

1. Run Verify.
2. `moved` only: commit the code first, run `cite_refs.py ... --fix`, commit the changed JSON. `--fix` re-points numbers and advances the pin together, per file, and refuses while a cited file is uncommitted. It exits 1 and prints each citation it left other than `ok` (path, line, verdict), whatever kept it from repairing it: those need you, and no second run of `--check` is needed to find them. Exit 0 means every citation it read is `ok`.
3. Anything else red, or `REVIEW` files whose section no longer matches: re-trace that part of the code, rewrite only the affected section and its citations.
4. Set the Markdown pin on line 1 to the commit you just verified against, and commit.
5. If `.claude/kit.yml` still lists S12 or S13 under `deviations`, remove those entries: the doctor fails on a deviation that no longer applies.

In CI, check out with full history (`fetch-depth: 0`).

As a PostToolUse hook: `python3 "${CLAUDE_PLUGIN_ROOT}/skills/map-project/scripts/cite_refs.py" --diagrams <dir> --touched <files>` reports citations into the files just changed and always exits 0. The plugin ships the script, not the hook wiring.

## Report

1. Sections written or refreshed, and where the map lives
2. Checker output
3. Older architecture documents found, for `kit-adopt` to retire
4. Open questions: things the code does that you could not explain
