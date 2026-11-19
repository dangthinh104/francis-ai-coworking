#!/usr/bin/env python3
"""Check a repository against the francis-kit standard (STANDARD.md).

Usage: kit_doctor.py [--repo DIR] [--project-root DIR ...] [--all] [--roots]
       kit_doctor.py [--repo DIR] --lint-features ROOT

One line per rule: PASS, GAP, DEBT (a gap covered by an entry under
`deviations` in .claude/kit.yml) or SKIP (nothing to judge yet). Rules about
the repository (S01, S14, S15) are reported once; the rest per project. Nothing
of a project is run: S19 reads the workflow files under .github/workflows.

Exit 0 when there is no GAP. Exit 1 on a GAP, including a missing manifest, a
deviation that no longer applies, and an offender the recorded deviation
does not name. Exit 2 when nothing could be judged: bad arguments, a manifest
that does not parse, is larger than 200 kB or multiplies through its aliases,
or an internal error.
Without a manifest the repo is checked as one project at the git root, or at
each --project-root given. --all prints every offending name; --roots prints
the project roots and exits. --lint-features ROOT prints the feature directories
of that project root for the gate to hand to spec_lint.py, one per line, without
those a deviation on S04 to S07 or S09 lists; the names left out go to stderr.
"""
import argparse
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_md_audit  # noqa: E402
import kit_spec  # noqa: E402
from kit_spec import CODE_SPAN, COMMENT, FENCE, STATUSES  # noqa: E402

TRACKERS = ('none', 'jira', 'github', 'azure-devops', 'monday')
FEATURE = kit_spec.FEATURE_DIR
TICKET = re.compile(r'^\*\*Ticket\*\*:[ \t]*(\S+)[ \t]*$', re.M)
# Any list item, quoted or not: `* [ ]`, `1. [ ]` and `> - [ ]` are open tasks too.
ITEM = r'^[ \t>]*(?:[-*+]|\d+[.)])[ \t]+'
OPEN_TASK = re.compile(ITEM + r'\[ \]', re.M)
DONE_TASK = re.compile(ITEM + r'\[[xX]\]', re.M)
FIXES = re.compile(r'^#{2,3}[ \t]+Fixes\b[^\n]*$.*?(?=^#{1,3}[ \t]|\Z)', re.M | re.S | re.I)
BLANK = re.compile(r'<[a-z][^<>\n]*>')
NO_TEST = re.compile(r'^(?:(?:/bin/|/usr/bin/)?true|:|exit(?: 0)?|echo|printf)(?:\s.*)?$')
PIN = re.compile(r'kit:map revision=([0-9a-f]{7,40})')
MATCH_SECONDS = 5
MAX_NODES = 100_000
MARKETPLACE = 'francis-ai-coworking'
PLUGIN = 'francis-kit@francis-ai-coworking'
REPO_RULES = ['S01', 'S14', 'S15']
PROJECT_RULES = [f'S{n:02d}' for n in range(2, 14)] + ['S16', 'S17', 'S18', 'S19']
# What each rule is about, in a few words: an id alone tells a reader nothing.
ABOUT = {
    'S01': 'the manifest', 'S02': 'CLAUDE.md', 'S03': 'the constitution', 'S04': 'only features under specs/',
    'S05': 'no feature under .specify/specs/', 'S06': 'spec, plan and tasks files', 'S07': 'the Status line',
    'S08': 'the Ticket line', 'S09': 'tasks as checkboxes, none open after release', 'S10': 'a living spec',
    'S11': 'closed features cited in the living spec', 'S12': 'the map', 'S13': 'the map\'s citations',
    'S14': 'the gate','S15': 'the plugin is enabled', 'S16': 'voice and design direction',
    'S17': 'a dependency audit', 'S18': 'CLAUDE.md names nothing that is gone',
    'S19': 'tests run on pull requests',
}
NAMED_RULES = {'S04', 'S05', 'S06', 'S07', 'S08', 'S09', 'S11', 'S18', 'S19'}   # a deviation must name what it covers
NAMES_KEY = {'S18': 'names', 'S19': 'names'}       # what is named is not always a feature
PROJECT_KEYS = {'name', 'root', 'setup', 'test', 'lint', 'ci_only', 'tracker', 'release', 'deviations', 'interface', 'audit'}
COMMON = Path(__file__).resolve().parent.parent / 'templates' / 'common'
GATE_REF = re.compile(r'^[ \t]*ref:[ \t]*(v\d+\.\d+\.\d+)[ \t]*$', re.M)
TEMPLATES = {'VOICE.md': Path(__file__).resolve().parents[2] / 'ui-copy' / 'templates' / 'VOICE.md',
             'DESIGN.md': Path(__file__).resolve().parents[2] / 'design-direction' / 'templates' / 'DESIGN.md'}
TOP_KEYS = {'version', 'projects', 'deviations', 'scratch', 'gate'}
GATES = ('workflow', 'hook')
HOOK_FILE = '.githooks/pre-push'
WORKFLOW_FILE = '.github/workflows/kit-gate.yml'
HOOK_REF = re.compile(r'^KIT_REF=(v\d+\.\d+\.\d+)$', re.M)
KITS_HOOK = re.compile(r'^KIT_REF=', re.M)
# A project with none of these tracked has no dependency to audit.
DEPENDENCY_FILES = ('requirements*.txt', 'requirements/*.txt', 'pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile',
                    'Pipfile.lock', 'poetry.lock', 'uv.lock', 'package.json', 'package-lock.json', 'yarn.lock',
                    'pnpm-lock.yaml', 'composer.json', 'composer.lock', 'go.mod', 'go.sum', 'Cargo.toml', 'Cargo.lock',
                    'Gemfile', 'Gemfile.lock', 'pubspec.yaml', 'pom.xml', 'build.gradle', 'build.gradle.kts', '*.csproj')
LINT_DEBT_RULES = ('S04', 'S05', 'S06', 'S07', 'S09')     # debt on these keeps a feature out of the gate's lint
LIMIT = 5
MAX_CHARS = 200_000
ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*=')
# A command that starts with one of these is not read by S19: what it does to the lines after it is not known.
NOT_PLAIN = frozenset('if then else elif fi for while until do done case esac function select time coproc ! [[ eval '
                      'exec source . trap exit return set shopt alias unset pushd popd builtin command'.split())


read = kit_spec.read


def some(names):
    names = sorted(names)
    if LIMIT is None or len(names) <= LIMIT:
        return ', '.join(names)
    return ', '.join(names[:LIMIT]) + f', +{len(names) - LIMIT} more (--all lists them)'


def runs_nothing(command):
    """True when every part of a shell line is a no-op: `true`, `: todo`, `echo x; exit 0`."""
    parts = [p.strip() for p in re.split(r'&&|\|\||;|\|', command.split(' #')[0]) if p.strip()]
    return all(NO_TEST.match(p) for p in parts)


def _after_quote(text, i):
    """The index after the quoted text that opens at `i`; the end when nobody closed it."""
    quote, n = text[i], len(text)
    if quote != '"':
        end = text.find(quote, i + 1)
        return n if end < 0 else end + 1
    i += 1
    while i < n and text[i] != '"':
        i += 2 if text[i] == '\\' else 1
    return i + 1


def _after_substitution(text, i):
    """The index after the `$(...)` or `${...}` that opens at `i`, whatever it nests."""
    opener = text[i + 1]
    closer, depth, i, n = ')' if opener == '(' else '}', 1, i + 2, len(text)
    while i < n and depth:
        c = text[i]
        if c == '\\':
            i += 2
        elif c in '\'"`':
            i = _after_quote(text, i)
        else:
            depth += (c == opener) - (c == closer)
            i += 1
    return i


def shell_tokens(text):
    """The words and the cuts of a shell text, in order: ('word', text, index) and ('cut',
    sign, index), the index being where it starts in the text.

    One pass, as a shell splits the text. A cut is a line break or a run of `;`, `|`, `&`;
    `(` and `)` end a word and are given as ('group', sign, index).
    Nothing inside quotes, behind a backslash, inside `$(...)`, `${...}` or backticks, or in
    a comment is a cut or a word of its own; a redirection (`2>&1`, `&>`, `>|`) is part of a
    word; blanks end a word; a backslash before a line break lets the line go on.
    """
    i, n = 0, len(text)
    opened = None           # where the word being read began
    start = True            # a word may start here: where `#` opens a comment
    while i < n:
        c = text[i]
        step, cut, kind = 1, None, 'cut'
        if c == '\\':
            step = 2
            if text[i + 1:i + 2] == '\n':
                if opened is not None:
                    yield 'word', text[opened:i], opened
                opened = None
                i += 2
                continue
        elif c in '\'"`':
            step = _after_quote(text, i) - i
        elif c == '$' and text[i + 1:i + 2] in ('(', '{'):
            step = _after_substitution(text, i) - i
        elif c == '#' and start:
            end = text.find('\n', i)
            i = n if end < 0 else end
            continue
        elif c in ' \t\r':
            cut = ''
        elif c in '()':
            cut, kind = c, 'group'
        elif c == '\n':
            cut = '\n'
        elif c in ';|&':
            end = i
            while end < n and text[end] in ';|&':
                end += 1
            sign, before, after = text[i:end], text[i - 1:i] if i else '', text[end:end + 1]
            step = end - i
            if not ((sign == '&' and (before in ('<', '>') or after == '>')) or (sign == '|' and before == '>')):
                cut = sign
        if cut is None:
            if opened is None:
                opened = i
            start = False
        else:
            if opened is not None:
                yield 'word', text[opened:i], opened
            opened, start = None, True
            if cut:
                yield kind, cut, i
        i += step
    if opened is not None:
        yield 'word', text[opened:], opened


def joining_signs(command):
    """The signs that join the commands of one shell line, `&&` left out: each once, in order.

    The exit status of `a || b`, `a; b`, `a | b` or `a &` is not the status of `a`. Read by
    `shell_tokens`. A `;` or a line break with nothing after it joins nothing, and a line
    break after a sign goes on with the same line.
    """
    found, pending = [], None
    word = False            # a word was read since the last sign
    for kind, value, _ in shell_tokens(command):
        if kind == 'word':
            if pending and pending not in found:
                found.append(pending)
            pending, word = None, True
        elif kind == 'group':
            pass
        elif value == '\n':
            if word:
                pending = pending or 'a line break'
            word = False
        elif value == '&&':
            word = False
        elif not value.strip(';'):
            if word:
                pending = pending or value
            word = False
        else:
            if value not in found:
                found.append(value)
            pending, word = None, False
    return found


def shell_commands(text):
    """The commands of a shell text: [(words, cut)], the cut being what ended the command
    ('' at the end of the text). A cut with no word before it ends nothing."""
    out, words = [], []
    for kind, value, _ in shell_tokens(text):
        if kind == 'word':
            words.append(value)
        elif kind == 'cut' and words:
            out.append((words, value))
            words = []
    if words:
        out.append((words, ''))
    return out


def joined_entries(key, entries, whose, example):
    """One message per entry whose exit status is not its command's: the key, the entry, the sign."""
    out = []
    for entry in entries:
        signs = joining_signs(entry)
        if signs:
            named = ', '.join(s if ' ' in s else f'`{s}`' for s in signs)
            out.append(f'{key} entry {entry!r} joins commands with {named}, so its exit status is not {whose}: '
                       f'join with `&&` only (`{example}`)')
    return out


def _inside(path, directory):
    """True when `path` is `directory` or below it; both from the git root, '' being the root."""
    return not directory or path == directory or path.startswith(directory + '/')


def tracks_dependencies(root, repo, others=()):
    """True when git tracks a dependency manifest that is this project's, False when none, None
    when git cannot say.

    The project's are those in its root or in a directory above it, up to `repo`, and those
    below its root that are not below the root of another project (`others`) lying inside it.
    """
    out = claude_md_audit.git(repo, 'ls-files', '-z', '--', *(f':(glob)**/{name}' for name in DEPENDENCY_FILES))
    if out is None or out.returncode != 0:
        return None
    repo = repo.resolve()

    def from_repo(path):
        path = path.resolve()
        return '' if path == repo else path.relative_to(repo).as_posix()

    here = from_repo(root)
    nested = [o for o in map(from_repo, others) if o != here and _inside(o, here)]
    for name in out.stdout.split('\0'):
        if not name:
            continue
        folder = name.rpartition('/')[0]
        if _inside(here, folder):
            return True
        if _inside(folder, here) and not any(_inside(folder, o) for o in nested):
            return True
    return False


def unfilled(text, template):
    """The `<...>` blanks of the template that the file still carries.

    A long blank is looked for by itself. A short one (`<date>`) is ordinary enough to
    appear in a project's own prose, so it counts only on the template's whole line.
    """
    body = CODE_SPAN.sub('', text)
    lines = {line.strip() for line in body.splitlines()}
    left = set()
    for line in CODE_SPAN.sub('', COMMENT.sub('', read(template) or '')).splitlines():
        for blank in BLANK.findall(line):
            if (len(blank) >= 12 and blank in body) or (len(blank) < 12 and line.strip() in lines):
                left.add(blank)
    return sorted(left)


class Skipped:
    """A rule that has nothing to judge, and why. `lasting` is False when the reason is a gap
    of another rule that is about to be closed: a deviation recorded on this one then stays."""

    def __init__(self, reason, lasting=True):
        self.reason, self.lasting = reason, lasting


class Gap:
    """One finding. `firm` marks a rule that could not be checked at all: no recorded
    deviation covers that, since nobody knows what it would be covering. `detail` is what
    was read to reach it, printed again under a gap that only lists names.
    Names of a gap that carries `judged` are commands: they are printed quoted.
    `hint` is the way out for the names in `hint_for`: printed under a gap that names one
    of them, never under debt."""

    def __init__(self, message, offenders=None, firm=False, detail='', judged=None, hint='', hint_for=()):
        self.message, self.offenders, self.firm, self.detail = message, set(offenders or []), firm, detail
        self.judged = judged        # every name the rule looked at, where a listed name may be none of them
        self.hint, self.hint_for = hint, set(hint_for)


def expanded_size(node, seen):
    """How many values a YAML node stands for once every alias is written out."""
    if node is None:
        return 0
    if id(node) not in seen:
        seen[id(node)] = 1          # a cycle counts once
        children = getattr(node, 'value', None)
        total = 1
        if isinstance(children, list):
            for child in children:
                for part in (child if isinstance(child, tuple) else (child,)):
                    total += expanded_size(part, seen)
        seen[id(node)] = total
    return seen[id(node)]


def load_yaml(text):
    """Return (mapping, None), or (None, why the text cannot be read as one)."""
    try:
        import yaml
    except ImportError:
        return None, 'cannot be read: PyYAML is not installed (pip install pyyaml)'
    if len(text) > MAX_CHARS:
        return None, 'is larger than 200 kB'
    try:
        # Aliases are fine (a monorepo shares its commands); a file whose aliases multiply
        # into millions of values is not a manifest. Counted on the graph, so it costs nothing.
        if expanded_size(yaml.compose(text, Loader=yaml.SafeLoader), {}) > MAX_NODES:
            return None, f'expands to more than {MAX_NODES} values through its aliases'
        data = yaml.safe_load(text)
    except Exception as exc:  # yaml raises ValueError too, e.g. on an impossible date
        return None, f'does not parse: {(str(exc).splitlines() or [type(exc).__name__])[0]}'
    if not isinstance(data, dict):
        return None, 'is not a mapping'
    return data, None


def load_manifest(repo):
    """Return (data, problem, fatal)."""
    text = read(repo / '.claude' / 'kit.yml')
    if text is None:
        return None, '.claude/kit.yml is missing', False
    data, problem = load_yaml(text)
    if problem and 'PyYAML' in problem:
        return None, 'PyYAML is not installed (pip install pyyaml): the manifest cannot be read', True
    if problem and problem.startswith('is larger'):
        problem += ': it holds facts, not data'
    return data, f'.claude/kit.yml {problem}' if problem else None, bool(problem)


def check_deviations(entries, allowed, label):
    """Validate a deviations list. Returns ({rule: entry}, [problems]). The entries of a rule that
    names things are read together: one entry holding all their names and each `fix` in `fixes`."""
    listed, problems, holders = {}, [], {}
    if entries is None:
        return listed, problems
    if not isinstance(entries, list):
        return listed, [f'{label}: deviations must be a list']
    for d in entries:
        rule = d.get('rule') if isinstance(d, dict) else None
        if not isinstance(rule, str) or rule not in allowed:
            where = ' (S14 and S15 go in the top-level deviations list)' if rule in ('S14', 'S15') else ''
            problems.append(f'{label}: deviation {d!r} needs `rule`, one of {", ".join(allowed)}{where}')
            continue
        if rule in listed and rule not in NAMED_RULES:
            problems.append(f'{label}: deviation {rule} is listed twice')
            continue
        for key in ('reason', 'fix'):
            if not isinstance(d.get(key), str) or not d[key].strip():
                problems.append(f'{label}: deviation {rule} has no `{key}`')
        key = NAMES_KEY.get(rule, 'features')
        names = d.get(key)
        if rule in NAMED_RULES:
            if not (isinstance(names, list) and names and all(isinstance(n, str) for n in names)):
                problems.append(f'{label}: deviation {rule} must name what it covers: '
                                f'`{key}: [name, ...]` (run the doctor with --all to list them)')
                names = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
            if key != 'features' and 'features' in d:
                problems.append(f'{label}: deviation {rule} takes `{key}`, not `features`')
            if rule == 'S19':
                names = [' '.join(n.split()) for n in names]
            for name in dict.fromkeys(names):     # a name twice in one entry counts once
                holders[rule, name] = holders.get((rule, name), 0) + 1
            first = listed.get(rule)        # 018/FR-004: a further entry adds its names and its fix
            # `features`: one place for the report to read, whatever the key is called
            d = dict(first or d, features=(first or {}).get('features', []) + names,
                     fixes=(first or {}).get('fixes', []) + [d.get('fix')])
        else:
            if names is not None:
                problems.append(f'{label}: deviation {rule} does not take `features`')
            d = dict(d, fixes=[d.get('fix')])
        listed[rule] = d
    problems += [f'{label}: deviation {rule} lists {name} in more than one entry'
                 for (rule, name), count in holders.items() if count > 1]
    return listed, problems


def root_file_judged(data, repo):
    """True when the CLAUDE.md at the git root belongs to no project: several projects, none at
    the root, and the file is there. It is then judged with the repository (S02, S18)."""
    projects = data.get('projects') if isinstance(data, dict) else None
    listed = [p for p in projects if isinstance(p, dict)] if isinstance(projects, list) else []
    if len(listed) < 2 or not (repo / 'CLAUDE.md').is_file():
        return False
    for p in listed:
        root = p.get('root')
        if isinstance(root, str) and root and '\0' not in root and (repo / root).resolve() == repo:
            return False
    return True


def repo_deviation_rules(data, repo):
    """The rules a top-level deviation may name."""
    return ['S14', 'S15'] + (['S02', 'S18'] if root_file_judged(data, repo) else [])


def check_manifest(data, problem, repo):
    """S01 for the whole file."""
    if problem:
        return [problem]
    gaps = []
    if data.get('version') != 2:
        gaps.append('version must be 2')
    unknown = sorted(str(k) for k in data if k not in TOP_KEYS)
    if unknown:
        gaps.append(f'unknown top-level keys: {", ".join(unknown)}')
    if gate_problem(data):
        gaps.append(gate_problem(data))
    _, problems = check_deviations(data.get('deviations'), repo_deviation_rules(data, repo), 'repository')
    gaps += problems
    projects = data.get('projects')
    if not isinstance(projects, list) or not projects:
        return gaps + ['no projects listed']
    seen = set()
    for i, p in enumerate(projects):
        if not isinstance(p, dict):
            gaps.append(f'project {i} is not a mapping')
            continue
        named = isinstance(p.get('name'), str) and bool(p['name'])
        label = p['name'] if named else f'project {i}'
        unknown = sorted(str(k) for k in p if k not in PROJECT_KEYS)
        if unknown:
            gaps.append(f'{label}: unknown keys: {", ".join(unknown)}')
        ident = (p.get('name') if isinstance(p.get('name'), str) else i,
                 p.get('root') if isinstance(p.get('root'), str) else i)
        if ident[0] in {x[0] for x in seen} or ident[1] in {x[1] for x in seen}:
            gaps.append(f'{label}: name or root already used by another project')
        seen.add(ident)
        if not named:
            gaps.append(f'{label}: name must be a non-empty string')
        if not isinstance(p.get('interface'), bool):
            gaps.append(f'{label}: interface must be true or false (true when people use the project through screens)')
        root = p.get('root')
        if not isinstance(root, str) or not root:
            gaps.append(f'{label}: root must be a path from the git root')
        elif '\0' in root:
            gaps.append(f'{label}: root is not a valid path')
        else:
            resolved = (repo / root).resolve()
            if resolved != repo and repo not in resolved.parents:
                gaps.append(f'{label}: root {root!r} is outside the repository')
            elif not resolved.is_dir():
                gaps.append(f'{label}: root {root!r} does not exist')
        test = p.get('test')
        commands = [t.strip() for t in test if isinstance(t, str) and t.strip()] if isinstance(test, list) else []
        if not commands:
            gaps.append(f'{label}: test must be a non-empty list of commands')
        elif all(runs_nothing(c) for c in commands):
            gaps.append(f'{label}: test runs nothing ({commands[0]!r}): name the command that runs the tests')
        gaps += [f'{label}: {m}. S01 cannot be recorded as a deviation, so the entry has to change'
                 for m in joined_entries('test', commands, "the tests'", 'cd api && pytest -q')]
        release = p.get('release')
        if not isinstance(release, dict):
            gaps.append(f'{label}: release must have pr_target and deploy_branches')
        else:
            if not isinstance(release.get('pr_target'), str) or not release['pr_target']:
                gaps.append(f'{label}: release.pr_target must name a branch')
            if not isinstance(release.get('deploy_branches'), list):
                gaps.append(f'{label}: release.deploy_branches must be a list (empty only if no push deploys)')
        tracker = p.get('tracker')
        kind = tracker.get('type') if isinstance(tracker, dict) else None
        if not isinstance(kind, str) or kind not in TRACKERS:
            gaps.append(f'{label}: tracker.type must be one of {", ".join(TRACKERS)}')
        elif kind != 'none':
            pattern = tracker.get('id_pattern')
            if not isinstance(pattern, str) or not pattern:
                gaps.append(f'{label}: tracker.id_pattern must be a regex string')
            else:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    gaps.append(f'{label}: tracker.id_pattern is not a valid regex: {exc}')

        _, problems = check_deviations(p.get('deviations'), PROJECT_RULES, label)
        gaps += problems
    return gaps


def ticket_pattern(project):
    tracker = project.get('tracker')
    if isinstance(tracker, dict) and tracker.get('type') in TRACKERS[1:] \
            and isinstance(tracker.get('id_pattern'), str) and tracker['id_pattern']:
        try:
            re.compile(tracker['id_pattern'])
        except re.error:
            return None
        return tracker['id_pattern']
    return None


MATCHER = '''import json, re, sys
pattern, tickets = json.load(sys.stdin)
rx = re.compile(pattern)
print(json.dumps([bool(rx.fullmatch(t)) for t in tickets]))
'''


def tickets_match(pattern, tickets):
    """Which tickets the project's pattern accepts, or None when it did not finish.

    The pattern is the project's own text and some patterns take minutes on a short
    string, so it runs in a process that can be stopped.
    """
    if not tickets:
        return []
    try:
        out = subprocess.run([sys.executable, '-I', '-c', MATCHER], input=json.dumps([pattern, tickets]),
                             capture_output=True, text=True, encoding='utf-8', timeout=MATCH_SECONDS)
        found = json.loads(out.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    return found if isinstance(found, list) and len(found) == len(tickets) else None


def judge_docs(root, gaps):
    """S02, S03: CLAUDE.md and the constitution exist and are the project's own words."""
    claude = read(root / 'CLAUDE.md')
    if claude is None:
        gaps['S02'].append(Gap('CLAUDE.md is missing'))
    elif not claude.strip():
        gaps['S02'].append(Gap('CLAUDE.md is empty'))
    elif len(claude.splitlines()) > 150:
        gaps['S02'].append(Gap(f'CLAUDE.md has {len(claude.splitlines())} lines (150 at most)'))
    elif unfilled(claude, COMMON / 'CLAUDE.md'):
        gaps['S02'].append(Gap('CLAUDE.md still has blanks of the template: '
                               + ' '.join(b if len(b) <= 44 else b[:40] + '...>'
                                          for b in unfilled(claude, COMMON / 'CLAUDE.md'))))

    constitution = read(root / '.specify' / 'memory' / 'constitution.md') or ''
    if not constitution.strip():
        gaps['S03'].append(Gap('.specify/memory/constitution.md is missing or empty'))
    elif unfilled(constitution, COMMON / 'constitution.md'):
        gaps['S03'].append(Gap('constitution.md still has blanks of the template: '
                               + ' '.join(unfilled(constitution, COMMON / 'constitution.md'))))


def find_features(root, gaps):
    """S04, S05: where features live. Returns (specs directory, feature directories)."""
    specs = root / 'specs'
    features, numbers, strays = [], {}, []
    if not specs.is_dir():
        gaps['S04'].append(Gap('specs/ is missing'))
    else:
        for entry in sorted(specs.iterdir()):
            m = FEATURE.match(entry.name) if entry.is_dir() and not entry.is_symlink() else None
            if m:
                features.append(entry)
                numbers.setdefault(m.group(1), []).append(entry.name)
            elif entry.name not in ('_living', 'README.md', 'INDEX.md', '.kit-refs-baseline.json'):
                strays.append(entry.name)
        if strays:
            gaps['S04'].append(Gap(f'{len(strays)} entries are not NNN-slug/: {some(strays)}', strays))

    hidden = root / '.specify' / 'specs'
    hidden_dirs = [e for e in sorted(hidden.iterdir()) if e.is_dir()] if hidden.is_dir() else []
    misplaced = [e for e in hidden_dirs if FEATURE.match(e.name)]
    if hidden_dirs:
        gaps['S05'].append(Gap(f'{len(hidden_dirs)} directories under .specify/specs/: '
                               f'{some(e.name for e in hidden_dirs)}', [e.name for e in hidden_dirs]))
    for entry in misplaced:    # judged like any feature, wherever they sit
        features.append(entry)
        numbers.setdefault(FEATURE.match(entry.name).group(1), []).append(entry.name)
    twice = [n for names in numbers.values() if len(names) > 1 for n in names]
    if twice:
        gaps['S04'].append(Gap(f'feature number used twice: {some(twice)}', twice))
    return specs, features


def judge_features(features, pattern, tracked, gaps):
    """S06 to S09, one pass over every feature. Returns the names of the Closed ones."""
    no_spec, no_plan, bad_status, bad_ticket, bad_tasks, open_after, closed = [], [], [], [], [], [], []
    judged = with_tasks = 0
    to_match = []
    for feature in features:
        name = feature.name
        spec = read(feature / 'spec.md')
        if spec is None:
            no_spec.append(name)
            continue
        plain = kit_spec.prose(spec)
        status = kit_spec.status(spec)    # two Status lines are no status: which one is read is chance
        if status is None:
            bad_status.append(name)
        rank = STATUSES.index(status) if status in STATUSES else None   # None: unknown or ended
        judged += rank is not None
        t = TICKET.search(plain)
        if not tracked:
            pass                  # no tracker: a line that can only say `none` tells nobody anything
        elif not t:
            bad_ticket.append(name)
        elif pattern and rank is not None and rank >= 1:
            to_match.append((name, t.group(1)))
        tasks = read(feature / 'tasks.md')
        if rank is not None and rank >= 2 and (tasks is None or not (feature / 'plan.md').is_file()):
            no_plan.append(name)
        if tasks is not None:
            with_tasks += 1
            tasks = COMMENT.sub('', CODE_SPAN.sub('``', FENCE.sub('', tasks)))
            planned = FIXES.sub('', tasks)    # a fix logged later is not the feature's task list
            if not OPEN_TASK.search(planned) and not DONE_TASK.search(planned):
                bad_tasks.append(name)
            if rank is not None and rank >= 3 and OPEN_TASK.search(tasks):     # its own question: an open fix counts
                open_after.append(name)
        if status == 'Closed':
            closed.append(name)

    matched = tickets_match(pattern, [ticket for _, ticket in to_match]) if pattern else []
    slow_pattern = matched is None
    if not slow_pattern:
        bad_ticket += [name for (name, _), ok in zip(to_match, matched) if not ok]
        bad_ticket.sort()

    total = len(features)
    if not features:
        for rule in ('S06', 'S07', 'S08', 'S09'):
            gaps[rule] = None
    else:
        if no_spec:
            gaps['S06'].append(Gap(f'no spec.md in {len(no_spec)} of {total}: {some(no_spec)}', no_spec))
        if no_plan:
            gaps['S06'].append(Gap(f'Built or later without plan.md and tasks.md: {some(no_plan)}', no_plan))
        if bad_status:
            gaps['S07'].append(Gap(f'no single valid Status line in {len(bad_status)} of {total}: {some(bad_status)}', bad_status))
        if slow_pattern:
            gaps['S08'].append(Gap(f'tracker.id_pattern did not finish in {MATCH_SECONDS} s: no ticket was checked. '
                                   f'Write it plainly, like SCRUM-\\d+', firm=True))
        if bad_ticket:
            gaps['S08'].append(Gap(f'no valid Ticket line in {len(bad_ticket)} of {total}: {some(bad_ticket)}', bad_ticket))
        if bad_tasks:
            gaps['S09'].append(Gap(f'tasks.md without checkboxes (`- [ ]` / `- [x]`) in {len(bad_tasks)}: {some(bad_tasks)}', bad_tasks))
        if open_after:
            gaps['S09'].append(Gap(f'Released or Closed with open tasks: {some(open_after)}', open_after))
        # A rule that looked at nothing must not read as a pass.
        if not gaps['S06'] and not judged and not no_spec:
            gaps['S06'] = None
        if not gaps['S09'] and not with_tasks:
            gaps['S09'] = None
        if len(no_spec) == total:
            gaps['S07'] = gaps['S08'] = None
        if not tracked:
            gaps['S08'] = None
    return closed


def judge_living(specs, closed, gaps):
    """S10, S11: every Closed feature is cited in the living spec."""
    living = specs / '_living'
    living_specs = sorted(living.glob('*/spec.md')) if living.is_dir() else []
    if not closed:
        gaps['S10'] = gaps['S11'] = None
    elif not living_specs:
        gaps['S10'].append(Gap(f'{len(closed)} Closed features but no specs/_living/<capability>/spec.md'))
        gaps['S11'].append(Gap(f'Closed but not cited in specs/_living/: {some(closed)}', closed))
    else:
        text = '\n'.join(read(p) or '' for p in living_specs)
        uncited = [n for n in closed
                   if not re.search(r'(?<![\w/-])specs/' + re.escape(n) + r'(?![\w-])', text)]
        if uncited:
            gaps['S11'].append(Gap(f'Closed but not cited in specs/_living/: {some(uncited)}', uncited))


def judge_map(root, gaps):
    """S12, S13: the map and its citation file carry a pin."""
    doc = read(root / 'docs' / 'ARCHITECTURE.md')
    if doc is None:
        gaps['S12'].append(Gap('docs/ARCHITECTURE.md is missing'))
    else:
        lines = doc.splitlines()
        if not lines or not PIN.search(lines[0]):
            gaps['S12'].append(Gap('docs/ARCHITECTURE.md does not start with the kit pin'))
        if len(lines) > 200:
            gaps['S12'].append(Gap(f'docs/ARCHITECTURE.md has {len(lines)} lines (200 at most)'))

    refs = read(root / 'docs' / 'diagrams' / 'map.refs.json')
    if refs is None:
        gaps['S13'].append(Gap('docs/diagrams/map.refs.json is missing'))
    else:
        try:
            data = json.loads(refs)
            pinned = data['meta']['repository']['revision']
        except (ValueError, KeyError, TypeError):
            data = pinned = None
        if not isinstance(pinned, str) or not re.fullmatch(r'[0-9a-f]{7,40}', pinned):
            gaps['S13'].append(Gap('map.refs.json has no commit in meta.repository.revision'))
        elif not cites_something(data):
            gaps['S13'].append(Gap('map.refs.json cites nothing: no `sources` entry with a `path`'))
        else:
            first = doc.splitlines()[0] if doc else ''
            markdown = PIN.search(first)
            if markdown and pin_behind(root, markdown.group(1), pinned):
                prefix = claude_md_audit.git(root, 'rev-parse', '--show-prefix')
                where = (prefix.stdout.strip() if prefix and prefix.returncode == 0 else '') + 'docs/ARCHITECTURE.md'
                note(f'S13: {where} is pinned to {markdown.group(1)[:8]}, behind map.refs.json at {pinned[:8]}: '
                     f'read the REVIEW list of map_check.py, then set line 1 of the map (map-project, Refresh step 4)')


def pin_behind(root, markdown, json_pin):
    """True only when git proves the map's pin lacks the commit of its citation file's pin (023/FR-003);
    a pin git cannot resolve, or any pin in a shallow clone, where ancestry is cut, is not compared."""
    shallow = claude_md_audit.git(root, 'rev-parse', '--is-shallow-repository')
    if shallow is None or shallow.stdout.strip() != 'false':
        return False
    commits = []
    for rev in (markdown, json_pin):
        out = claude_md_audit.git(root, 'rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}')
        if out is None or out.returncode != 0:
            return False
        commits.append(out.stdout.strip())
    out = claude_md_audit.git(root, 'merge-base', '--is-ancestor', commits[1], commits[0])
    return out is not None and out.returncode == 1


def cites_something(node):
    """True when a citation file holds at least one `sources` entry that names a path."""
    if isinstance(node, dict):
        sources = node.get('sources')
        if isinstance(sources, list) and any(isinstance(s, dict) and isinstance(s.get('path'), str) and s['path']
                                             for s in sources):
            return True
        return any(cites_something(v) for v in node.values())
    return isinstance(node, list) and any(cites_something(v) for v in node)


def judge_interface(root, project, gaps):
    """S16: a project people use through screens has its voice and its design direction."""
    if project.get('interface') is not True:
        gaps['S16'] = None
    else:
        for name, template in TEMPLATES.items():
            text = read(root / 'docs' / name) or ''
            given = {l.strip() for l in (read(template) or '').splitlines()}
            # A table row the project filled in is text; the template's own rows and `|---|` are not.
            written = [l for l in text.splitlines()
                       if re.search(r'\w', l) and not l.lstrip().startswith(('#', '<!--')) and l.strip() not in given]
            blanks = {l for l in given if '<' in l and '>' in l}
            left = [l for l in text.splitlines() if l.strip() in blanks]
            if not text.strip():
                gaps['S16'].append(Gap(f'docs/{name} is missing or empty'))
            elif left:
                gaps['S16'].append(Gap(f'docs/{name} still has {len(left)} line(s) of the template not filled in'))
            elif len(written) < 3:
                gaps['S16'].append(Gap(f'docs/{name} says almost nothing: fewer than three lines of text'))


def judge_audit(root, project, repo, others, gaps):
    """S17: the project names a dependency audit that runs something and keeps its result."""
    audit = project.get('audit')
    named = [a.strip() for a in audit if isinstance(a, str) and a.strip()] if isinstance(audit, list) else []
    if not named:
        # Nothing named and nothing to scan is not a gap. Where git cannot say what it tracks,
        # or the key holds something that is not a command, nobody knows: the gap stays.
        if (audit is None or audit == []) and tracks_dependencies(root, repo, others) is False:
            gaps['S17'] = Skipped('no audit is named and git tracks no dependency manifest for this project')
            return
        gaps['S17'].append(Gap('no dependency audit named: `audit: [command, ...]` '
                               '(pip-audit, npm audit, composer audit, govulncheck)'))
        return
    if all(runs_nothing(a) for a in named):
        gaps['S17'].append(Gap(f'audit runs nothing ({named[0]!r})'))
    gaps['S17'] += [Gap(m) for m in joined_entries('audit', named, "the audit's", 'cd app && npm audit')]


_NOTED = set()
NO_HISTORY = type("NoHistory", (list,), {})()   # the verdict of S18 where git cannot say what it once held


def note(message):
    if message not in _NOTED:
        _NOTED.add(message)
        print(f'note: {message}', file=sys.stderr)


def judge_claude_md(path, repo, tests, project_roots=(), found_out=None):
    """S18 for one CLAUDE.md: [Gap], or None when there is no file or no git history to ask.
    For the root file of a monorepo, the paths found under one of `project_roots` are added to
    `found_out` (021)."""
    text = read(path)
    if text is None:
        return None
    # Without the whole history of this very repository, "git never knew it" proves nothing:
    # the rule is skipped, never passed.
    top = claude_md_audit.git(repo, 'rev-parse', '--show-toplevel')
    shallow = claude_md_audit.git(repo, 'rev-parse', '--is-shallow-repository')
    if top is None or top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo.resolve():
        note('S18: this directory is not the root of a git repository, so what git once knew cannot be asked')
        return NO_HISTORY
    if shallow is None or shallow.stdout.strip() != 'false':
        note('S18: this is a shallow clone, so a path deleted earlier cannot be seen: fetch the history '
             '(`git fetch --unshallow`, or `fetch-depth: 0` in the gate)')
        return NO_HISTORY
    try:
        found = claude_md_audit.audit(text, path.parent, repo, tests, project_roots)
    except claude_md_audit.Unjudged as exc:
        note(f'S18: {exc}')
        return NO_HISTORY
    if found_out is not None:
        found_out += found.found
    if not found:
        return []
    names = sorted({f.name for f in found})
    return [Gap(f'{path.relative_to(repo).as_posix()} names what is gone, or leaves out a test command of the manifest: '
                f'{some(names)}', names, hint=claude_md_audit.TWO_WAYS,
                hint_for={f.name for f in found if f.kind in claude_md_audit.HINTED})]


def _within(base, path):
    """The directory `path` as seen from `base`, both from the git root (`.`), or None when
    it cannot be known: an expression, a variable, a shell operator, a path outside the repository."""
    if base is None or not isinstance(path, str):
        return None
    path = path.strip().replace('\\', '/')
    if not path or path[0] in '/~-' or path[1:2] == ':' or any(c in path for c in '$`*?\'"<>|&;()'):
        return None
    found = posixpath.normpath(posixpath.join(base, path))
    return None if found == '..' or found.startswith('../') or len(found) > 4096 else found


def _run_default(node, key, inherited):
    """`defaults.run.<key>` of a workflow or a job, or what it inherits."""
    for step in ('defaults', 'run'):
        node = node.get(step) if isinstance(node, dict) else None
    found = node.get(key) if isinstance(node, dict) else None
    return inherited if found is None else found


def _thrown_away(node):
    """How a step or a job gives up its result (004/FR-004), or ''."""
    keeps = node.get('continue-on-error')
    if keeps is not None and keeps is not False and not (isinstance(keeps, str) and keeps.strip() == 'false'):
        return 'under `continue-on-error`'
    unless = node.get('if')
    if unless is False or (isinstance(unless, str) and unless.strip() == 'false'):
        return 'under `if: false`'
    return ''


def _not_plain(words, here):
    """(what, directory): the word or sign that makes a command one this rule does not read,
    or None, and where the commands after it run.

    A plain command is words, with assignments in front and redirections, that hold no brace,
    backtick, `$(` or `<<` outside quotes and do not start with a word of NOT_PLAIN or a
    backslash. `set` is plain when it only switches flags on; `cd` only as `cd <path written
    out>` inside the repository, and it moves the directory (004/FR-005, 004/FR-006).
    """
    for word in words:
        i, n = 0, len(word)
        while i < n:
            c = word[i]
            if c in '{}`' or word[i:i + 2] in ('$(', '<<'):
                return (c if c in '{}`' else word[i:i + 2]), here
            i = i + 2 if c == '\\' else _after_quote(word, i) if c in '\'"' else i + 1
    command = _without_assignments(words)
    first, rest = (command[0], command[1:]) if command else ('', [])
    if first == 'set' and rest and rest[0].startswith('-') and not any(a.startswith('+') for a in rest):
        return None, here
    if first in NOT_PLAIN or first.startswith('\\'):
        return first, here
    if first == 'cd':
        here = _cd_path(here, rest[0] if len(words) == 2 and rest else None)
        return (None if here else 'cd'), here
    return None, here


def _cd_path(here, path):
    """The directory a path written out names from `here`, one pair of quotes around it taken off,
    or None: what a plain `cd` accepts (004/FR-006)."""
    if path and len(path) > 1 and path[0] in '\'"' and path[-1] == path[0]:
        path = path[1:-1]
    return _within(here, path)


# The options that change the directory a tool runs in, read only directly after the program and
# with the path as a word of its own (014). `uv --project` and `npm --prefix` do not move every command.
DIRECTORY_OPTIONS = {'uv': '--directory', 'go': '-C', 'make': '-C'}


def _named(words, where):
    """(bare form, directory) of a command run in `where`: the command with its directory option
    and the option's path taken out, and the directory it names, or the command itself and `where`
    when it carries no directory option (014, definitions)."""
    lead = len(words) - len(_without_assignments(words))
    command = words[lead:]
    if len(command) > 3 and DIRECTORY_OPTIONS.get(command[0]) == command[1]:
        named = _cd_path(where, command[2])
        if named:
            return words[:lead] + command[:1] + command[3:], named
    return words, where


def plain_commands(text, directory):
    """(commands, unread): the commands of the plain lines of a `run:` text, [(words, cut,
    where)] with the cut `&&` or a line break, up to the first line that is not plain; `unread`
    says which line that is and what it holds, or is ''.

    A plain line is empty, a comment, or one plain command; the last line that holds anything
    may join several with `&&` (004/FR-005). Anywhere else the shell goes on when a command in
    front of `&&` fails, so the lines after it say nothing about the one behind it.
    Nothing is read from a line that is not plain on: what it does to the lines after it is
    not known. A line continued by a backslash, or by a quote left open, is one line.
    """
    out, line, words, here = [], [], [], directory
    start = joined = 0
    tokens = list(shell_tokens(text)) + [('cut', '\n', len(text))]
    for n, (kind, value, at) in enumerate(tokens):
        what = None
        if kind == 'word':
            if not words:
                start = at
            words.append(value)
            continue
        if kind != 'cut' or value not in ('&&', '\n'):
            what = value
        elif words:
            what, moved = _not_plain(words, here)
            line.append((words, value, here))
            here, words, at = moved, [], start
        elif value == '&&' or joined:
            what = '&&'                     # a line that starts or ends with it
        if not what and value == '\n' and len(line) > 1 and any(t[:2] != ('cut', '\n') for t in tokens[n + 1:]):
            what = '&&'                     # joined commands, and not the last line
        if what:
            return out, f"line {text.count(chr(10), 0, at) + 1} holds shell this rule does not read (`{what}`)"
        joined = value == '&&'
        if value == '\n':
            out += line
            line = []
    return out, ''


def read_workflows(repo):
    """The workflow files of the git root as S19 reads them, by name. Each is
    {'name', 'problem'} when it cannot be read as a workflow, else {'name', 'on', 'called',
    'steps', 'unjudged'}: whether its `on` names `workflow_call`, the plain lines of its `run:`
    steps cut into commands, and the jobs that run their work elsewhere, each as {'job',
    'uses', 'call', 'lost'} with `call` the file a job calls (006/FR-002) or None."""
    folder, out = repo / '.github' / 'workflows', []
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        if path.suffix not in ('.yml', '.yaml') or not path.is_file():
            continue
        text = read(path)
        data, problem = load_yaml(text) if text is not None else (None, 'cannot be read')
        if not problem and not isinstance(data.get('jobs'), dict):
            problem = 'has no `jobs` mapping'
        if problem:
            out.append({'name': path.name, 'problem': problem})
            continue
        steps, unjudged = [], []
        base = [_run_default(data, key, None) for key in ('working-directory', 'shell')]
        for name, job in data['jobs'].items():
            if not isinstance(job, dict):
                continue
            lost = _thrown_away(job)
            if isinstance(job.get('uses'), str):
                # A job that holds steps too is one GitHub refuses: its call is not read as one.
                unjudged.append({'job': name, 'uses': job['uses'], 'lost': lost,
                                 'call': None if 'steps' in job else _called_file(job['uses'])})
            ours = [_run_default(job, key, inherited) for key, inherited in zip(('working-directory', 'shell'), base)]
            for n, step in enumerate(job['steps'] if isinstance(job.get('steps'), list) else [], 1):
                if not isinstance(step, dict):
                    continue
                if isinstance(step.get('uses'), str) and step['uses'].startswith('./'):
                    unjudged.append({'job': name, 'uses': step['uses'], 'lost': lost, 'call': None})
                if isinstance(step.get('run'), str):
                    folder, shell = [ours[i] if step.get(key) is None else step[key]
                                     for i, key in enumerate(('working-directory', 'shell'))]
                    here = '.' if folder is None else _within('.', folder)
                    if shell is not None and not (isinstance(shell, str) and shell.split()[:1] in (['bash'], ['sh'])):
                        commands, unread = [], f'its `shell` is {shell!r}'
                    elif here is None:
                        commands, unread = [], 'its `working-directory` is not a path written out'
                    else:
                        commands, unread = plain_commands(step['run'], here)
                    steps.append({'job': f'{name} step {n}', 'lost': _thrown_away(step) or lost,
                                  'commands': commands, 'unread': unread})
        # PyYAML reads the bare key `on` as the boolean true.
        on = data['on'] if 'on' in data else data.get(True)
        out.append({'name': path.name, 'problem': None, 'on': on, 'steps': steps, 'unjudged': unjudged,
                    'called': 'workflow_call' in on if isinstance(on, (list, dict)) else on == 'workflow_call'})
    return out


def _called_file(uses):
    """The workflow file a job's `uses:` calls, or None when it is not a call: another
    repository, a path below `.github/workflows` or one that leaves it."""
    here, _, name = uses.rpartition('/')
    return name if here == './.github/workflows' and name.endswith(('.yml', '.yaml')) else None


def _refused(job, by_name):
    """Why a call at the first level is not followed (006/FR-002, 006/FR-003), or ''."""
    called = by_name.get(job['call'])
    if called is None:
        return 'which is missing'
    if called['problem']:
        return 'which cannot be read as a workflow'
    if not called['called']:
        return 'which has no `workflow_call` under `on`'
    return f"and the job is {job['lost']}" if job['lost'] else ''


def on_pull_requests_to(on, target):
    """True when a workflow's `on` names `pull_request` with no `branches` filter, or with one
    that lists `target` by name, and with no `types` list that leaves out `synchronize`
    (004/FR-003). A pattern is not a name."""
    if isinstance(on, str):
        return on == 'pull_request'
    if isinstance(on, list):
        return 'pull_request' in on
    if not isinstance(on, dict) or 'pull_request' not in on:
        return False
    event = on['pull_request']
    if not isinstance(event, dict):
        return True
    types = event.get('types')
    if types is not None and 'synchronize' not in (types if isinstance(types, list) else [types]):
        return False            # nothing starts when a commit is pushed to the pull request
    if 'branches' not in event:
        return True
    branches = event['branches']
    return target in (branches if isinstance(branches, list) else [branches])


def _without_assignments(words):
    for i, word in enumerate(words):
        if not ASSIGNMENT.match(word):
            return words[i:]
    return []


def _same_words(have, words):
    """True when a command of a step is the command `words` taken as written or with the
    assignments in front of it left out (004/FR-002)."""
    return have == words or _without_assignments(have) == words


def _held(commands, i, wanted, entry):
    """(cut, directory) when the commands of a step from the `i`-th hold the entry cut into
    `wanted`, with `cut` what ends the last one and `directory` the one the step names, or None.
    `entry` is the entry's bare form for an entry of one command (014/FR-001 to FR-003); the
    commands of a longer one are matched word for word and the step's directory is the first's."""
    if entry is not None:
        have, cut, where = commands[i]
        have, where = _named(have, where)
        return (cut, where) if _same_words(have, entry) else None
    for t, (words, cut) in enumerate(wanted):
        have, sign, _ = commands[i + t]
        if (t < len(wanted) - 1 and sign != cut) or not _same_words(have, words):
            return None
    return sign, commands[i][2]


def step_runs(step, wanted, here):
    """True when the step runs the entry, cut into the commands `wanted`, in the directory the
    entry names from the project root `here`, and keeps its result (004/FR-002, FR-004 to
    FR-006, 014): on a plain line, as its last command. Otherwise how it holds the entry
    without counting, one phrase per way, or [] when it does not hold it where it was read."""
    commands, k, why = step['commands'], len(wanted), []
    entry, named = _named(wanted[0][0], here) if k == 1 else (None, here)
    for i in range(len(commands) - k + 1 if k else 0):
        found = _held(commands, i, wanted, entry)
        if found is None:
            continue
        sign, where = found
        if step['lost']:
            how = step['lost']
        elif sign == '&&':
            how = 'followed by `&&`, so it is not the last command of its line'
        elif where != named:
            how = 'at the git root' if where == '.' else f'in {where}'
        else:
            return True
        if how not in why:
            why.append(how)
    return why


def judge_ci(project, here, workflows):
    """S19: each `test` entry of the project is run by a step of a workflow that starts on
    pull requests to `release.pr_target` (004/FR-001), or of a workflow file that one calls
    (006/FR-001). `here` is the project root from the
    git root. Returns [Gap], or Skipped where S01 already reports what is missing."""
    test, release = project.get('test'), project.get('release')
    # Named with runs of blanks as one, the way a step is matched. S01 reports an entry that runs
    # nothing: no workflow has to run `true`.
    entries = {' '.join(t.split()): t for t in test if isinstance(t, str) and t.strip() and not runs_nothing(t)} \
        if isinstance(test, list) else {}
    target = release.get('pr_target') if isinstance(release, dict) else None
    if not entries:
        return Skipped('no `test` entry that runs something to look for, which S01 (the manifest) reports', lasting=False)
    if not isinstance(target, str) or not target:
        return Skipped('no `release.pr_target` to read the workflows against, which S01 (the manifest) reports',
                       lasting=False)
    read_as = [w for w in workflows if not w['problem']]
    started = [w for w in read_as if on_pull_requests_to(w['on'], target)]
    # A call is followed from a workflow that counts, and only from there: one level, so a
    # circle of calls ends (006/FR-005). A file that counts itself is not read a second time.
    by_name, counts = {w['name']: w for w in workflows}, {w['name'] for w in started}
    readings, callers, unjudged, unjudged_in = [(w, '') for w in started], {}, [], []
    for w in read_as:
        for job in w['unjudged']:
            why = _refused(job, by_name) if job['call'] and w['name'] in counts else None
            if why == '':
                via = f"{w['name']} job {job['job']}"
                if job['call'] not in counts:
                    readings.append((by_name[job['call']], f', called by {via},'))
                    callers.setdefault(job['call'], []).append(via)
                continue
            unjudged.append(f"{w['name']} job {job['job']} not judged (it calls {job['uses']}{', ' + why if why else ''})")
            unjudged_in.append(w['name'])
    missing, near, holding = [], [], set()
    for entry, written in entries.items():
        wanted, held, holds = shell_commands(written), [], set()
        for w, via in readings:
            for step in w['steps']:
                found = step_runs(step, wanted, here)
                if found is True:
                    break
                if found:
                    holds.add(id(step))             # this entry is in the lines read: a step read for it
                at = f"{w['name']}{via} job {step['job']}"
                held += [f'{at} has {entry!r} {how}' for how in found]
                if step['unread'] and w['name'] != 'kit-gate.yml':      # the kit's own gate: S14 keeps tests out of it
                    held.append(f'{at} not judged: {step["unread"]}')
            else:
                continue
            break
        else:
            missing.append(entry)
            near += held
            holding |= holds                        # only what holds an entry no step runs
    if not missing:
        return []
    said = []
    if not workflows:
        said.append('There is no workflow file under .github/workflows')
    if read_as:
        said.append('Read: ' + ', '.join(
            f"{w['name']} (called by {', '.join(callers[w['name']])})" if w['name'] in callers else
            f"{w['name']} ({'on' if w['name'] in counts else 'not on'} pull requests to {target})" for w in read_as))
    said += [f"{w['name']} not judged ({w['problem']})" for w in workflows if w['problem']]
    said += dict.fromkeys(unjudged)
    if near:
        said.append('Not counted: ' + some(dict.fromkeys(near)))
    # Could read no step (016/FR-006): every step S19 matches, the kit's own gate left out, is not judged
    # and holds no entry in the lines read, and a place S19 reads, or a file it could not read, is not
    # judged. Then how an entry is matched is not what is wrong. A workflow that does not count, and
    # what it leaves unjudged, plays no part.
    ours = {w['name'] for w, _ in readings} - {'kit-gate.yml'}
    matched = [step for w, _ in readings if w['name'] in ours for step in w['steps']]
    blind = all(step['unread'] and id(step) not in holding for step in matched) and bool(
        any(step['unread'] for step in matched) or ours.intersection(unjudged_in)
        or any(w['problem'] for w in workflows))
    if not blind:
        said.append('An entry is matched word for word, the path of uv --directory, go -C or make -C written directly '
                    'after the program read as the directory the tool runs in, so a step that runs the same tool '
                    'written another way does not count: write the entry as CI runs it, or the step as the manifest says')
    said.append(f'Make a workflow run each entry on pull requests to {target}, as the last command of a line, in a step '
                f'that holds only plain commands before it, '
                f'or record a deviation on S19 that names it (`names: [...]`)')
    detail = '. '.join(said)
    opening = 'no step this rule can read runs' if blind else 'no step runs'
    return [Gap(f'{opening} on pull requests to {target}: {some(map(repr, missing))}. {detail}', missing, detail=detail, judged=set(entries))]


def check_project(root, project, repo, others=(), workflows=None):
    """Return {rule: [Gap] or None}. None means there was nothing to judge."""
    gaps = {r: [] for r in PROJECT_RULES}
    here = '.' if root == repo else root.relative_to(repo).as_posix()
    gaps['S19'] = judge_ci(project, here, read_workflows(repo) if workflows is None else workflows)
    tests = project.get('test') if isinstance(project.get('test'), list) else []
    gaps['S18'] = judge_claude_md(root / 'CLAUDE.md', repo, [c for c in tests if isinstance(c, str)])
    judge_docs(root, gaps)
    specs, features = find_features(root, gaps)
    tracker = project.get('tracker')
    tracked = isinstance(tracker, dict) and tracker.get('type') in TRACKERS[1:]
    closed = judge_features(features, ticket_pattern(project), tracked, gaps)
    judge_living(specs, closed, gaps)
    judge_map(root, gaps)
    judge_interface(root, project, gaps)
    judge_audit(root, project, repo, others, gaps)
    return gaps


def kit_ref():
    """The tag of the kit this script belongs to, `v1.2.3`, or '' when it cannot be read."""
    try:
        manifest = Path(__file__).resolve().parents[3] / '.claude-plugin' / 'plugin.json'
        return 'v' + json.loads(manifest.read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError, TypeError):
        return ''


def screens(root):
    """What in the project suggests an interface, in a few words, or ''. A reading, not a verdict."""
    found = []
    try:
        deps = json.loads(read(root / 'package.json') or '{}')
        names = {**(deps.get('dependencies') or {}), **(deps.get('devDependencies') or {})} if isinstance(deps, dict) else {}
    except (ValueError, TypeError):
        names = {}
    ui = sorted(n for n in ('vue', 'react', 'svelte', '@angular/core', 'next', 'nuxt') if n in names)
    if ui:
        found.append('package.json has ' + ', '.join(ui))
    for d in ('lang', 'locales', 'resources/lang', 'resources/js/locales', 'src/locales', 'src/i18n'):
        if (root / d).is_dir():
            found.append(f'{d}/ holds locale files')
            break
    for d in ('templates', 'resources/views'):
        if (root / d).is_dir() and any((root / d).rglob('*.html')) or (root / d).is_dir() and any((root / d).rglob('*.blade.php')):
            found.append(f'{d}/ holds pages')
            break
    return '; '.join(found)


def gate_problem(data):
    """What S01 says of the key `gate` of a manifest read as a mapping, or '' (010/FR-001)."""
    if 'gate' in data and not (isinstance(data['gate'], str) and data['gate'] in GATES):
        return 'gate must be workflow or hook'
    return ''


def gate_named(data):
    """The gate the manifest names: `hook` when its key `gate` is that text, `workflow` in every other case."""
    return 'hook' if isinstance(data, dict) and data.get('gate') == 'hook' else 'workflow'


def version_of(tag):
    """`v1.2.3` as the integers (1, 2, 3), or None for a tag of any other shape (`v0.16.0-rc1`, '')."""
    m = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', tag)
    return tuple(int(n) for n in m.groups()) if m else None


def judge_gate_file(text, template, name, key, path):
    """The first of the four gaps of a gate file against its template, or None (010/FR-002)."""
    pins = HOOK_REF.findall(text) if key == 'KIT_REF=' else GATE_REF.findall(text)[:1]
    if not text.strip():
        return f'{path} is missing or empty'
    if len(pins) != 1:
        example = '`KIT_REF=v1.2.3`' if key == 'KIT_REF=' else '`ref: v1.2.3`'
        return f'{name} does not pin the kit to a tag ({example})'
    pin, kit = pins[0], kit_ref()
    if pin != kit:
        # The same body with another ref would run another version's scripts inside this file.
        # Only this kit's template is here, so the gate is not judged, only which side has to move.
        if version_of(kit) and version_of(pin) < version_of(kit):
            return (f'{name} pins {pin}, and a newer kit, {kit}, is installed here: the gate runs and is judged by '
                    f'the checks of {pin}, and this doctor judges only a gate of {kit}. To take {kit}, write the '
                    f'gate again with `kit_scaffold.py --repo . --gate`')
        if version_of(kit) and version_of(pin) > version_of(kit):
            return (f'{name} pins {pin}, newer than the kit installed here, {kit}: this doctor judges only a gate '
                    f'of {kit}. Update the installed plugin (claude plugin marketplace update francis-ai-coworking, '
                    f'then claude plugin update francis-kit@francis-ai-coworking, again with --scope project where the '
                    f'project installed it) and run the doctor again; writing the gate again with this kit would '
                    f'take it back to {kit}')
        return (f'{name} pins {pin} and this kit is {kit}: the gate is judged by '
                f'the version it pins. Move with `kit_scaffold.py --repo . --gate`')
    if text.strip() != (read(COMMON / template) or '').replace('{{KIT_REF}}', pins[0]).strip():
        # The rules and the start of kit_gate.py live in this file, not behind the pin:
        # raising the pin alone runs a new kit inside an old file.
        return (f'{name} is not the gate of this kit version: write it again with '
                f'`kit_scaffold.py --repo . --gate` (raising `{key}` alone is not enough)')
    return None


def hook_in_index(repo):
    """The gap of how git's index holds the hook file, or None when it holds it executable (010/FR-003)."""
    top = claude_md_audit.git(repo, 'rev-parse', '--show-toplevel')
    listed = claude_md_audit.git(repo, 'ls-files', '-s', '--', HOOK_FILE)
    if top is None or top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo.resolve() \
            or listed is None or listed.returncode != 0:
        return f'{HOOK_FILE}: git could not say how the index holds it (not a git repository, or no git)'
    if not listed.stdout.strip():
        return f'{HOOK_FILE} is not tracked by git: run `git add --chmod=+x {HOOK_FILE}`'
    mode = listed.stdout.split()[0]
    if mode != '100755':
        return f'{HOOK_FILE} is not executable in the index (mode {mode}): run `git add --chmod=+x {HOOK_FILE}`'
    return None


def crlf_in_index(repo):
    """True when git's index holds the hook file with a carriage return; False when it does not or cannot say."""
    try:
        blob = subprocess.run(['git', 'show', ':' + HOOK_FILE], cwd=repo, capture_output=True)
    except OSError:
        return False
    return blob.returncode == 0 and b'\r' in blob.stdout


def judge_gate(repo, data):
    """S14: the gate the manifest names is the kit's template of the version it pins, and the other is absent."""
    workflow, hook = read(repo / WORKFLOW_FILE) or '', read(repo / HOOK_FILE) or ''
    if gate_named(data) == 'hook':
        found = [judge_gate_file(hook, 'pre-push', 'pre-push', 'KIT_REF=', HOOK_FILE)]
        if not found[0] and crlf_in_index(repo):
            # read() drops carriage returns, but a clone checks out the blob as it is, and sh on Linux
            # cannot start a file whose first line ends in \r: such a blob is not HOOK unchanged.
            found[0] = ('pre-push is not the gate of this kit version: write it again with '
                        '`kit_scaffold.py --repo . --gate` (raising `KIT_REF=` alone is not enough)')
        if hook.strip():
            found.append(hook_in_index(repo))
        if (repo / WORKFLOW_FILE).is_file():
            found.append(f'{WORKFLOW_FILE} is there and the manifest names the hook: a project holds one gate, '
                         f'remove the file')
    else:
        found = [judge_gate_file(workflow, 'kit-gate.yml', 'kit-gate.yml', 'ref:', WORKFLOW_FILE)]
        if KITS_HOOK.search(hook):
            found.append(f"{HOOK_FILE} is the kit's hook and the manifest names the workflow: a project holds one "
                         f'gate, remove the file or set gate: hook')
    return [Gap(m) for m in found if m]


def check_repo(repo, data=None):
    gaps = {'S14': judge_gate(repo, data), 'S15': []}
    try:
        settings = json.loads(read(repo / '.claude' / 'settings.json') or '')
    except ValueError:
        settings = None
    markets = settings.get('extraKnownMarketplaces') if isinstance(settings, dict) else None
    plugins = settings.get('enabledPlugins') if isinstance(settings, dict) else None
    if not (isinstance(markets, dict) and MARKETPLACE in markets
            and isinstance(plugins, dict) and plugins.get(PLUGIN) is True):
        gaps['S15'].append(Gap('.claude/settings.json does not register and enable the kit'))
    return gaps


def monorepo_dirs(repo):
    """The directories one level down that the scaffold's note names, each once, where the git root
    holds no code marker of the scaffold's (018/FR-002)."""
    from kit_scaffold import detect_profile     # not at the top: kit_scaffold imports this module
    if detect_profile(repo) != 'generic':
        return []
    return sorted({p.parent.name for pat in ('*/artisan', '*/pyproject.toml', '*/requirements.txt')
                   for p in repo.glob(pat)})


def report(rules, gaps, listed, totals):
    for rule in rules:
        found = gaps.get(rule)
        entry = listed.get(rule)
        if found is NO_HISTORY:       # a debt entry stays: where the history is whole, it is judged
            print(f'  SKIP {rule} ({ABOUT[rule]}): git cannot be asked here (see the note)')
            totals['SKIP'] += 1
        elif isinstance(found, Skipped):
            # The project did nothing wrong by recording the debt before the rule stopped applying.
            print(f'  SKIP {rule} ({ABOUT[rule]}): {found.reason}')
            totals['SKIP'] += 1
            if entry and found.lasting:
                note(f'{rule}: skipped, so the deviation recorded on it can be removed from .claude/kit.yml')
        elif found is None:
            if entry:
                print(f'  GAP  {rule} listed under deviations but there is nothing to judge: remove the entry')
                totals['GAP'] += 1
            else:
                print(f'  SKIP {rule} ({ABOUT[rule]}): nothing to judge yet')
                totals['SKIP'] += 1
        elif not found:
            if entry:
                print(f'  GAP  {rule} listed under deviations but conforms now: remove the entry')
                totals['GAP'] += 1
            else:
                print(f'  PASS {rule} ({ABOUT[rule]})')
                totals['PASS'] += 1
        elif not entry or any(g.firm for g in found):
            for g in found:
                if g.firm or not entry:
                    print(f'  GAP  {rule} {g.message}')
                    if g.hint_for:
                        print(f'         {g.hint}')
            totals['GAP'] += 1
        else:
            new = stale = strangers = set()
            show = some
            if rule in NAMED_RULES:
                names = set(entry.get('features') or [])
                offenders = {n for g in found for n in g.offenders}
                new, stale = offenders - names, names - offenders
                judged = [g.judged for g in found if g.judged is not None]
                if judged:          # the names are commands: quoted, and a name may be none of them
                    strangers = stale - set().union(*judged)
                    stale = stale - strangers
                    show = lambda names: some(map(repr, names))     # noqa: E731
            if new or stale or strangers:
                if strangers:
                    print(f'  GAP  {rule} listed under the deviation but no `test` entry that the rule looks for, '
                          f'remove: {show(strangers)}')
                if new:
                    print(f'  GAP  {rule} not covered by the recorded deviation: {show(new)}')
                    for g in found:
                        if g.detail:
                            print(f'         {g.detail}')
                        if g.hint_for & new:
                            print(f'         {g.hint}')
                if stale:
                    print(f'  GAP  {rule} listed under the deviation but conforming now, remove: {show(stale)}')
                totals['GAP'] += 1
            else:
                for g in found:
                    print(f'  DEBT {rule} {g.message}')
                for fix in entry['fixes']:          # 018/FR-007: one line per entry, in the list's order
                    print(f"         fix (from .claude/kit.yml): {fix or '(no fix written)'}")
                totals['DEBT'] += 1


def main(argv=None):
    """A crash is never a verdict: it exits 2, like an unreadable manifest."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    try:
        return _main(argv)
    except Exception as exc:
        print(f'cannot check: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


def _main(argv=None):
    global LIMIT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--repo', type=Path, default=Path('.'), help='git root (default: .)')
    ap.add_argument('--project-root', action='append', default=[],
                    help='project directory under the repo; only used when there is no manifest')
    ap.add_argument('--all', action='store_true', help='print every offending name')
    ap.add_argument('--roots', action='store_true', help='print the project roots and exit')
    ap.add_argument('--lint-features', metavar='ROOT',
                    help='print the features of that project root for the gate to lint, and exit')
    args = ap.parse_args(argv)
    if args.roots or args.lint_features is not None:
        try:
            sys.stdout.reconfigure(newline='\n')      # a shell reads these lines, on any system
        except (AttributeError, ValueError):
            pass
    if args.all:
        LIMIT = None
    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f'no such directory: {repo}', file=sys.stderr)
        return 2

    data, problem, fatal = load_manifest(repo)
    if fatal:
        print(f'cannot check: {problem}', file=sys.stderr)
        return 2
    projects = [p for p in (data or {}).get('projects') or [] if isinstance(p, dict)] \
        if isinstance((data or {}).get('projects'), list) else []
    if data is None:
        projects = [{'name': Path(r).name or repo.name, 'root': r}
                    for r in (args.project_root or ['.'])]
    elif args.project_root:
        print('note: --project-root is ignored because .claude/kit.yml lists the projects', file=sys.stderr)

    def root_of(project):
        root = project.get('root')
        resolved = (repo / root).resolve() if isinstance(root, str) and root and '\0' not in root else None
        if resolved is None or not resolved.is_dir() or (resolved != repo and repo not in resolved.parents):
            return None
        return resolved

    if args.roots:
        for project in projects:
            if root_of(project):
                print(project['root'])
        return 0

    if args.lint_features is not None:
        project = next((p for p in projects if p.get('root') == args.lint_features and root_of(p)), None)
        if project is None:
            print(f'no project with the root {args.lint_features!r}: `--roots` lists them', file=sys.stderr)
            return 2
        specs = root_of(project) / 'specs'
        names = [e.name for e in sorted(specs.iterdir())
                 if e.is_dir() and not e.is_symlink() and FEATURE.match(e.name)] if specs.is_dir() else []
        listed, _ = check_deviations(project.get('deviations'), PROJECT_RULES, '')
        debt = {n for rule in LINT_DEBT_RULES for n in (listed.get(rule) or {}).get('features') or []}
        left = [n for n in names if n in debt]
        if left:
            print(f"left out of the spec lint, recorded as debt in .claude/kit.yml: {', '.join(left)}", file=sys.stderr)
        for name in names:
            if name not in debt:
                print(name)
        return 0

    totals = {'PASS': 0, 'GAP': 0, 'DEBT': 0, 'SKIP': 0}
    workflows = read_workflows(repo)
    nested = monorepo_dirs(repo) if data is None and not args.project_root else []
    if nested:
        print(f'note: no code markers at the root but found projects in: {", ".join(nested)}. For a monorepo '
              f'pass --project-root once per project, or list the projects in .claude/kit.yml.')
    print('repository')
    repo_gaps = check_repo(repo, data)
    repo_gaps['S01'] = [Gap(m) for m in check_manifest(data, problem, repo)]
    # In a repository of several projects the file at the git root is loaded on top of each
    # project's own, and belongs to none of them: it is judged here.
    shared = repo / 'CLAUDE.md'
    repo_rules = list(REPO_RULES)
    found_under = []
    if root_file_judged(data, repo):
        lines = len((read(shared) or '').splitlines())
        repo_gaps['S02'] = [Gap(f'CLAUDE.md at the git root has {lines} lines (150 at most)')] if lines > 150 else []
        roots = [p['root'] for p in data['projects'] if isinstance(p, dict) and isinstance(p.get('root'), str)]
        repo_gaps['S18'] = judge_claude_md(shared, repo, None, roots, found_under)
        repo_rules += ['S02', 'S18']
    repo_listed, _ = check_deviations((data or {}).get('deviations'), repo_deviation_rules(data, repo), 'repository')
    report(repo_rules, repo_gaps, repo_listed, totals)
    for f in found_under:           # 021/FR-003: S18 is the last rule of the repository, so these stand below it
        print(f'         note: CLAUDE.md:{f.line} {f.name} is {f.why}')

    for project in projects:
        print(f"project {project.get('name') or '?'} (root {project.get('root') or '?'})")
        root = root_of(project)
        if root is None:
            print('  SKIP all: root is not a directory inside the repository (see S01)')
            continue
        release = project.get('release') if isinstance(project.get('release'), dict) else {}
        deploys = release.get('deploy_branches') if isinstance(release.get('deploy_branches'), list) else []
        if release.get('pr_target') in deploys:
            print(f"  note: pull requests target `{release['pr_target']}`, which deploys on push: "
                  f'every merge is a release, a docs-only one included')
            if gate_named(data) == 'hook':
                print('  note: the gate is the hook: it guards pushes from the clones that switched it on; '
                      'a merge on GitHub and a push from any other clone are not judged')
        if project.get('interface') is False:
            seen = screens(root)
            if seen:
                print(f'  note: interface is false, yet this looks like a project people use through screens '
                      f'({seen}). If so, set it to true: S16 then applies')
        listed, _ = check_deviations(project.get('deviations'), PROJECT_RULES, '')
        others = [r for r in map(root_of, projects) if r]
        report(PROJECT_RULES, check_project(root, project, repo, others, workflows), listed, totals)
    print(f"summary: {totals['PASS']} pass, {totals['GAP']} gap, {totals['DEBT']} debt, "
          f"{totals['SKIP']} skipped")
    if data is None:
        print('provisional: there is no .claude/kit.yml, so the projects judged here are a guess and these '
              'verdicts can change once it lists them')
    return 1 if totals['GAP'] else 0


if __name__ == '__main__':
    sys.exit(main())
