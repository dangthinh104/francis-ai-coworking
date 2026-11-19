#!/usr/bin/env python3
"""Report what a CLAUDE.md names that is not there.

    claude_md_audit.py --repo DIR [--project-root DIR ...]

Claude Code loads CLAUDE.md at the start of every session, so a path in it that
no longer exists is believed by every session. Judged: the file at the git root
and the one at the root of each project in `.claude/kit.yml`, and the one in each
directory given with --project-root, whether the manifest lists it or not.

For each file: its lines and its size estimated as characters divided by four,
then every finding with its line:

    path      a path in backticks that git does not track, from the git root or
              from the directory of the file, and that git once knew: it was
              deleted or moved, and the file still sends its reader there. A copy
              on this disk that git does not track is not the path: a clone has none.
              A file git tracks that is missing from this working tree is reported
              as that
    skill     `.claude/skills/<name>` or `.claude/agents/<name>` with nothing there,
              or with a copy git once held and no longer tracks. A file below a skill
              that is there is a path like any other
    command   a `test` command of the manifest that the project's file neither
              holds as a whole command (`make test` is not held by `make test-all`)
              nor replaces by naming `.claude/kit.yml` outside a code block or comment

Judged as a path: a code span with a `/`, or a file name with an extension
(`app.properties`, `.env.example`).

In the root CLAUDE.md of a repository whose manifest lists its projects, a path that
would be reported and that git tracks under a project root of the manifest, in this
working tree, is not reported: it is named with that root, `found` in place of `path`,
"not at the git root; found under <root>/", and counts as no finding.

Not judged: a path that is absolute, starts with `~` or a drive letter, or holds
`<`, `{`, `*` or `NNN`; a path git ignores (a file made at run time); a path under a
submodule that was not fetched; anything inside a fenced code block or an HTML
comment (a code span in an indented block is read); a skill or command named
without its path, since it may come from a plugin. The history is every commit
behind HEAD, those of a merged branch too. A path that never existed, a
typing mistake from the first day, is not reported either: nothing tells it from a
branch pattern or a host name.

The words around a path are not read: "there is no `docs/old.md` any more" names
`docs/old.md` in backticks, and it is reported like any other. A file that has to
speak of a thing that is gone has two ways, and a run that reported a path or a
skill ends with the line that names them:
write the name without backticks, or list it under `names:` of a deviation on S18.

Exit 0 when nothing was found, 1 when something was, 2 when a file that was to
be judged is missing or cannot be read, when the manifest is there and cannot be
read as one, when this is not a git repository or git cannot list what it tracks.
"""
import argparse
import os
import re
import subprocess
import posixpath
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_spec  # noqa: E402

SPAN = re.compile(r'`([^`\n]+)`')
PATHISH = re.compile(r'[\w.@+-]+(?:/[\w.@+-]*)*')
EXTENSION = re.compile(r'\.[A-Za-z][A-Za-z0-9]{0,9}$')
LINE_REF = re.compile(r':\d+(?:-\d+)?$')
NOT_A_PATH = re.compile(r'[<{*]|NNN|^~|^[A-Za-z]:[\\/]|^/')
TRAILING = re.compile(r'(?:#[\w.-]*)?[.,;:]*$')               # `docs/g.md.`, `docs/g.md#part`
OWN = re.compile(r'^\.claude/(skills|agents)/([\w.-]+)/?(.*)$')
# A comment, or a code span that is skipped so that a `<!--` quoted in it opens none.
# A backtick inside a comment opens no span: the comment is met first.
COMMENT_OR_SPAN = re.compile(r'<!--.*?-->|`[^`\n]*`', re.S)
MANIFEST_NAMED = re.compile(r'(?<![\w./-])(?:\./)?\.claude/kit\.yml(?![\w/-]|\.\w)')
# 007/FR-001. The doctor prints the same words under a gap on S18.
TWO_WAYS = ('The words around a name are not read. Of a thing that is gone, write the name without backticks, '
            'or keep them and list it under `names:` of a deviation on S18.')
HINTED = ('path', 'skill')         # the kinds of finding TWO_WAYS answers


class Unjudged(Exception):
    """The manifest is there and cannot be read: which files to judge is not known."""


class Finding:
    def __init__(self, kind, name, line, why):
        self.kind, self.name, self.line, self.why = kind, name, line, why


class Findings(list):
    """The findings of one file. `found` holds the paths of the root file found under a project
    root (021): no finding, so they are not in the list; `shown` is both in the order of the file."""

    def __init__(self, findings=(), found=(), shown=()):
        super().__init__(findings)
        self.found, self.shown = list(found), list(shown)


def under(root):
    """A project root as the manifest writes it, without a trailing `/`, followed by `/`."""
    return root.rstrip('/') + '/'


def uncommented(text):
    """The text without its HTML comments, line for line."""
    return COMMENT_OR_SPAN.sub(lambda m: '\n' * m.group(0).count('\n') if m.group(0).startswith('<!--') else m.group(0),
                               text)


def prose(text):
    """The text without fenced code blocks and HTML comments, line for line."""
    return uncommented(kit_spec.FENCE.sub('', text, keep_lines=True))


def named_paths(text):
    """(path, line number) for every code span that reads as a path. Code blocks are
    left out: a command shown as an example names files that need not exist."""
    for number, line in enumerate(prose(text).split('\n'), 1):
        for m in SPAN.finditer(line):
            candidate = LINE_REF.sub('', m.group(1).strip())
            candidate = LINE_REF.sub('', TRAILING.sub('', candidate))
            if NOT_A_PATH.search(candidate) or not PATHISH.fullmatch(candidate):
                continue
            if '/' in candidate or EXTENSION.search(candidate):
                if re.search(r'[A-Za-z]', candidate):
                    yield candidate, number


def commands_text(text):
    """Where a test command may stand: everything but HTML comments, code blocks included,
    as one line. A `<!--` inside a code block opens no comment."""
    whole, kept = text.split('\n'), kit_spec.FENCE.sub('', text, keep_lines=True).split('\n')
    bare = uncommented('\n'.join(kept)).split('\n')
    lines = [line if line.strip() and not fenced.strip() else plain for line, fenced, plain in zip(whole, kept, bare)]
    return ' '.join(' '.join(lines).split())


def git(repo, *args, stdin=None):
    try:
        return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, input=stdin,
                              encoding='utf-8', errors='replace')
    except OSError:
        return None


def above(path):
    return [p.as_posix() for p in PurePosixPath(path).parents if p.as_posix() not in ('.', '/')]


class Repository:
    """What git says of the paths of one repository, asked once each: a file that names
    four hundred paths costs the same few calls as one that names four."""

    def __init__(self, root):
        self.root, self._history = root, None
        # -z: without it git quotes a name that is not ASCII, and the name no longer compares.
        staged = git(root, 'ls-files', '-z', '--stage')
        self.readable = staged is not None and staged.returncode == 0
        self.files, self.submodules = set(), set()
        for entry in staged.stdout.split('\0') if self.readable else []:
            mode, tab, path = entry.partition('\t')
            if tab:
                (self.submodules if mode.startswith('160000 ') else self.files).add(path)
        self.directories = {d for path in self.files | self.submodules for d in above(path)}

    @staticmethod
    def place(relative):
        return posixpath.normpath(relative)

    def listed(self, relative):
        """True when git tracks the path or something below it."""
        path = self.place(relative)
        return path in self.files or path in self.directories or path in self.submodules

    def submodule_above(self, relative):
        """The submodule a path lies in, or None."""
        return next((d for d in above(self.place(relative)) if d in self.submodules), None)

    def unfetched(self, relative):
        """True when the path lies in a submodule this checkout did not fetch: whether the
        file is there cannot be known here, and a clone that fetches it may well have it."""
        module = self.submodule_above(relative)
        return module is not None and not os.path.lexists(self.root / module / '.git')

    def ignored(self, places):
        """Those of `places` git ignores: a file made at run time is not expected in a clone."""
        # git refuses a path that leads out of the repository or into a submodule, and with it
        # the whole list: neither is asked, and neither is ignored by this repository.
        places = sorted({p.rstrip('/') for p in places
                         if not self.place(p).startswith('..') and self.submodule_above(p) is None})
        if not places:
            return set()
        asked = git(self.root, 'check-ignore', '-z', '--stdin', stdin='\0'.join(places) + '\0')
        if asked is not None and asked.returncode in (0, 1):
            return set(asked.stdout.split('\0')) - {''}
        # One path git refuses for another reason (it runs through a symbolic link) fails the
        # list. When git answers for a plain name, the paths are asked one by one; when it
        # does not, nothing is known.
        probe = git(self.root, 'check-ignore', '-q', '--', '.kit-no-such-path')
        if probe is None or probe.returncode not in (0, 1):
            raise Unjudged('git cannot say what it ignores here (`git check-ignore` failed)')
        one = {p: git(self.root, 'check-ignore', '-q', '--', p) for p in places}
        return {p for p, answer in one.items() if answer is not None and answer.returncode == 0}

    def found_under(self, root, relative):
        """True when git tracks `<root>/<relative>`, a path that stays below the root, and it is
        in the working tree (021)."""
        base, path = self.place(root), self.place(f'{root}/{relative}')
        return path.startswith(base + '/') and self.listed(path) and os.path.exists(self.root / path)

    def in_history(self, relative):
        """True when a commit behind HEAD holds the path: it was there, and is gone or was moved.
        Every commit is read, those of a merged branch too."""
        if self._history is None:
            names = set()
            born = git(self.root, 'rev-parse', '-q', '--verify', 'HEAD')
            if born is None:
                raise Unjudged('git cannot be run here (`git rev-parse` failed)')
            if born.returncode == 0:        # a repository with no commit yet has no history
                # -O/dev/null: a `diff.orderFile` of the user that is not there would fail the call.
                log = git(self.root, 'log', '-m', '--no-renames', '--no-show-signature', '--name-only', '--format=',
                          '-z', '-O/dev/null')
                if log is None or log.returncode != 0:
                    raise Unjudged('git cannot read the history here (`git log` failed)')
                names = {name.strip('\n') for name in log.stdout.split('\0')} - {''}
            self._history = names | {d for name in names for d in above(name)}
        return self.place(relative) in self._history


def audit(text, file_dir, git_root, test_commands=None, project_roots=()):
    """Findings for one CLAUDE.md. `test_commands` is None for a file no manifest speaks for.
    `project_roots`, given for the root file of a monorepo only, are the roots of the manifest
    in its order: a path that would be reported and that git tracks under one is found there."""
    repo = Repository(git_root)
    if not repo.readable:
        raise Unjudged('git cannot list what it tracks here (`git ls-files` failed)')
    inside = file_dir.resolve().relative_to(git_root.resolve()).as_posix()
    bases = (git_root, file_dir)
    missing = 'git tracks it; it is missing from this working tree'
    untracked = 'git knew it; the copy on this disk is one git does not track'
    named = list(dict.fromkeys(named_paths(text)))
    open_, verdicts = {}, {}             # name -> (places, on disk, tracked); name -> (kind, why) or None
    for name in dict.fromkeys(name for name, _ in named):
        try:
            on_disk = any((base / name).exists() for base in bases)
        except OSError:                     # a name longer than the file system takes is not a path
            continue
        places = [name] if inside == '.' else [name, f'{inside}/{name}']
        # A copy on this disk is not the answer: a clone holds what git tracks, and the
        # verdict must be the same here and there.
        held = any(repo.listed(place) for place in places)
        if on_disk and (held or any(repo.submodule_above(place) for place in places)):
            continue
        # A submodule nobody fetched leaves no file here, and the file is not gone. In one
        # that was fetched the file is there or it is not, and the history is asked.
        if any(repo.unfetched(place) for place in places):
            continue
        open_[name] = places, on_disk, held
    ignored = repo.ignored(place for places, _, _ in open_.values() for place in places)
    for name, (places, on_disk, held) in open_.items():
        if any(place.rstrip('/') in ignored for place in places):
            continue
        known = lambda: any(repo.in_history(place) for place in places)
        own = OWN.match(name)
        if own:        # the project's own skill or agent, named by its path: it is there or it is not
            itself = f'.claude/{own.group(1)}/{own.group(2)}'
            if not any((base / itself).exists() for base in bases):
                verdicts[name] = 'skill', missing if held else f'no such {own.group(1)[:-1]}'
                continue
            if not own.group(3):
                if known():
                    verdicts[name] = 'skill', untracked
                continue
            # What is named below a skill that is there is a path like any other.
        if held:
            verdicts[name] = 'path', missing
        elif known():
            roots = [under(root) for root in project_roots if repo.found_under(root, name)]
            if roots:
                verdicts[name] = 'found', f'not at the git root; found under {", ".join(roots)}'
            else:
                verdicts[name] = 'path', untracked if on_disk else 'git knew it; it is gone or was moved'
    shown = [Finding(verdicts[name][0], name, line, verdicts[name][1]) for name, line in named if name in verdicts]
    findings = Findings([f for f in shown if f.kind != 'found'], [f for f in shown if f.kind == 'found'], shown)
    if test_commands:
        if not MANIFEST_NAMED.search(prose(text)):
            flat = commands_text(text)
            for command in test_commands:
                # The whole command, not the start of another: `make test` is not `make test-all`.
                # A slash at the end of it is the same path: `pytest -q tests/`. A colon or a full
                # stop before a space is punctuation; before a letter it is another command.
                whole = (r'(?<![\w./-])' + re.escape(' '.join(command.split()).rstrip('/'))
                         + r'(?:/(?![\w./-]))?(?![\w/=-]|[.:]\w)')
                if not re.search(whole, flat):
                    missed = Finding('command', command, 0,
                                     'the manifest runs this as a test; the file neither says so nor names '
                                     '.claude/kit.yml')
                    findings.append(missed)
                    findings.shown.append(missed)
    return findings


def size(text):
    return len(text.splitlines()), len(text) // 4


def targets(repo, project_roots):
    """[(label, file, project or None)]: the root file first, then one per project root."""
    data = None
    manifest = kit_spec.read(repo / '.claude' / 'kit.yml')
    if manifest is None and os.path.lexists(repo / '.claude' / 'kit.yml'):
        raise Unjudged('.claude/kit.yml is there and cannot be read')
    if manifest is not None:
        # A manifest that cannot be read is not "no manifest": judging the root file alone
        # would pass over every project it lists.
        try:
            import yaml
        except ImportError:
            raise Unjudged('.claude/kit.yml cannot be read without PyYAML (`pip install pyyaml`)')
        try:
            data = yaml.safe_load(manifest)
        except Exception as exc:
            raise Unjudged(f'.claude/kit.yml cannot be parsed ({type(exc).__name__})')
        # A manifest of another shape lists projects this reading would not find.
        if not isinstance(data, dict):
            raise Unjudged('.claude/kit.yml is not a mapping')
        listed = data.get('projects')
        if 'projects' in data and not (isinstance(listed, list) and all(
                isinstance(p, dict) and isinstance(p.get('root'), str) for p in listed)):
            raise Unjudged('.claude/kit.yml: `projects` is not a list of projects that each name a `root`')
        for p in listed or []:
            if not p['root'].strip():
                raise Unjudged('.claude/kit.yml: a project has an empty `root`')
            if 'test' in p and not isinstance(p['test'], list):
                raise Unjudged(f'.claude/kit.yml: `test` of the project at {p["root"]!r} is not a list of commands')
    projects = []
    if isinstance(data, dict) and isinstance(data.get('projects'), list):
        projects = list(data['projects'])
    listed = len(projects)
    # A root given by hand is judged too, listed or not; one the manifest lists is judged once.
    projects += [{'root': r} for r in project_roots]
    out, roots = [], set()
    for n, project in enumerate(projects):
        root = (repo / project['root']).resolve()
        if n >= listed and root in roots:
            continue
        if root == repo or repo in root.parents:
            roots.add(root)
            out.append((project.get('name') or project['root'], root / 'CLAUDE.md', project))
        else:
            named = '.claude/kit.yml' if n < listed else '--project-root'
            raise Unjudged(f'{named}: the root {project["root"]!r} is outside the repository')
    if repo not in roots:
        root_file = repo / 'CLAUDE.md'
        if root_file.is_file() or not out:
            out.insert(0, ('repository root', root_file, None))
    # The root file is read against the project roots of the manifest, never those given by hand (021).
    return [(label, file, project, [p['root'] for p in projects[:listed]] if project is None else [])
            for label, file, project in out]


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--repo', type=Path, default=Path('.'), help='git root (default: .)')
    ap.add_argument('--project-root', action='append', default=[],
                    help='a directory under the repo whose CLAUDE.md is judged too, listed in the manifest or not')
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f'no such directory: {repo}', file=sys.stderr)
        return 2
    inside = git(repo, 'rev-parse', '--is-inside-work-tree')
    if inside is None or inside.returncode != 0:
        print(f'{repo} is not a git repository: what git once knew cannot be asked', file=sys.stderr)
        return 2
    shallow = git(repo, 'rev-parse', '--is-shallow-repository')
    if shallow is not None and shallow.stdout.strip() == 'true':
        print('note: this is a shallow clone; a path deleted before the history that was fetched is not seen')
    found = unread = 0
    gone = False
    try:
        judged = targets(repo, args.project_root)
    except Unjudged as exc:
        print(f'{exc}: nothing was judged', file=sys.stderr)
        return 2
    for label, path, project, project_roots in judged:
        rel = path.relative_to(repo).as_posix()
        text = kit_spec.read(path)
        if text is None:
            print(f'{rel} ({label}): missing or not readable')
            unread += 1
            continue
        tests = project.get('test') if project and isinstance(project.get('test'), list) else None
        try:
            findings = audit(text, path.parent, repo, [t for t in tests if isinstance(t, str)] if tests else None,
                             project_roots)
        except Unjudged as exc:
            print(f'{exc}: nothing was judged', file=sys.stderr)
            return 2
        lines, tokens = size(text)
        print(f'{rel} ({label}): {lines} lines, about {tokens} tokens (characters / 4, an estimate), '
              f'{len(findings)} finding(s)')
        for f in findings.shown:        # a `found` line stands where its finding would have (021/FR-002)
            where = f'{rel}:{f.line}' if f.line else rel
            print(f'  {f.kind:<8}{where}  {f.name}  ({f.why})')
        found += len(findings)
        gone = gone or any(f.kind in HINTED for f in findings)
    if gone:
        print(TWO_WAYS)
    if unread:
        return 2
    return 1 if found else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:      # a crash is "nothing was checked", never "the file is wrong"
        print(f'claude_md_audit.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
