# Changelog

What changes for a project that uses the kit, newest first. Each version says what can turn a green gate red after moving to it, and how to clear it.

A project moves to a version by writing its gate again with that version's scaffold: `kit_scaffold.py --repo . --gate`. Until it does, the doctor reports S14 as a gap. Tags in this repository never move: a fix is a new version.

## 0.19.0

New:
- **The doctor says when git does not start the hook.** Under `gate: hook`, in a clone whose `core.hooksPath` is not `.githooks`, the doctor prints a note with the command that switches the hook on (`git config core.hooksPath .githooks`), or, where a hook manager runs the clone's hooks, says to have it start `.githooks/pre-push`. A CI run (`CI=true`) gets no such note.
- **The doctor's `summary:` line counts its notes**, ending in `, 1 note` or `, <n> notes` when there are any.
- **`map_check.py` counts fewer files as changed since the pin:** the map, its citation file, and a gate file changed only on its pin lines are left out.
- **`shrink-claude-md`** prints from the code each count that moves into a new file before it asks anything, and stops when one differs from `CLAUDE.md`.

Nothing turns red: no verdict changes, and the gate template is the one of 0.18.0 except its pin lines. A script that reads the `summary:` line whole may need to allow the count of notes at its end.

## 0.18.0

New:
- **The gate pins a commit.** Both gate templates name the commit of the kit's tag and keep the tag beside it: `ref: <commit>  # v<version>` in the workflow, `KIT_COMMIT=` beside `KIT_REF=` in the hook. A tag moved later no longer changes what a gate runs. Writing a gate now reads the kit's repository over the network (`git ls-remote`, 60 seconds at most), and writes nothing when it cannot.

Can turn red when you move:
- **S14 reports `does not pin the kit to a commit and its tag`** for a gate that pins a tag. Write the gate again with `kit_scaffold.py --repo . --gate`.

## 0.17.0

New:
- **The plugin's first hook.** It is active as soon as the plugin is enabled: before an Edit or Write adds an `Approved` Status line to a `specs/NNN-*/spec.md`, Claude Code shows a permission prompt. The prompt is a confirmation, not the approval, and the hook never blocks an edit. It is turned off only by disabling the plugin or by `disableAllHooks`. What it does not see is under "Known limits" in the README.

Nothing turns red: the hook is not part of the gate.

## 0.16.2

New:
- **`claude_md_shrink.py merged`.** After a merge or a finished rebase of a branch that applied a shrink, it names each line that one side added to `CLAUDE.md` and that the merged result lost. Run it before you push, and paste its output. It exits 1 when a line is lost and 2 when nothing could be checked.
- **Map pins.** `cite_refs.py --fix` prints a `map pin:` line, and the doctor a `note: S13`, when the pin on line 1 of `docs/ARCHITECTURE.md` is behind the pin of `docs/diagrams/map.refs.json`. Read the `REVIEW` list of `map_check.py`, then set line 1 (map-project, Refresh step 4). No tool writes that pin, and no verdict changes.
- **The `REVIEW` count of `map_check.py`** reads `of which cited by the map: D directly, U under a cited directory`.
- **What declares a requirement.** A line declares its first id only when a marker comes before it: a list item, a heading, a table row or `**`. A paragraph that starts with an id declares nothing. `STANDARD.md` lists the markers.

Can turn red when you move:
- **`specs/INDEX.md` is stale**, because a paragraph that starts with an id no longer counts in the FR column. Run `spec_index.py --root .` and commit the index.
- **An `NNN/FR-xxx` citation in code becomes `dead`**, or **a `## Fixes` line becomes a lint error**, when it cites an id that only such a paragraph declared. Cite the feature that really declares the id.

## 0.16.1

- **The workflow gate needs no secret**, because this kit is public. It checks out the kit at its tag with the workflow's own token.
- **`STANDARD.md`:** the S01 row escapes its `|`, so GitHub no longer cuts the row.

Nothing turns red; the gate template is otherwise the one of 0.16.0.

## 0.16.0

The first public version.
