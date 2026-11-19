#!/usr/bin/env python3
"""Print what can be read from a repository before asking the user anything.

    kit_detect.py --repo DIR [--project-root DIR]

Output is JSON. Every value is a reading, not a decision: kit-init shows it to
the user as the suggested answer, and the user's answer is what gets written.
A key is null or empty when nothing was found; `warnings` says what could not
be read, and that nothing was detected from git where the repository has no
commit or git tracks no file under the project root. Needs PyYAML. Exit 0, or 2 when the
directory cannot be used.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kit_doctor import KITS_HOOK, _called_file  # noqa: E402
from kit_scaffold import detect_profile  # noqa: E402

UI_PACKAGES = ('vue', 'react', 'svelte', '@angular/core', 'next', 'nuxt', '@inertiajs/vue3')
LOCALE_DIRS = ('lang', 'resources/lang', 'resources/js/locales', 'src/locales', 'locales', 'frontend/src/locales')
LOCALE = re.compile(r'[a-z]{2}(?:[-_][A-Za-z]{2})?')
DEPLOY = re.compile(r'deploy|release|publish|\bship|rsync|ssh|docker compose up|kubectl|terraform apply', re.I)
# "cd" the pipeline, however a workflow spells it. `cd` the shell command is taken out of
# the commands first (`names_in`), so that no name a workflow gives itself is lost.
# An underscore joins a name as a hyphen does: `ci_cd`, `cd_prod`.
CD = re.compile(r'(?<![a-z0-9])(?:cd|cicd)(?![a-z0-9])', re.I)
PATH_CD = re.compile(r'(?<=/)cd(?=/)')      # a directory on the way to a file: `build/cd/image.iso`
NOT_SHELL_BELOW = ('with', 'env', 'matrix', 'strategy')     # what stands under these is handed on, not run here
SHELLS = ('sh', 'bash', 'zsh', 'dash', 'ash', 'ksh')
OPENERS = ('{', '!', 'then', 'do', 'else', 'elif', 'if', 'while', 'until')
ASSIGNMENT = re.compile(r'\w+=')
# The pull request number a merge writes into the subject: `Add login (#12)`, `Revert "Add login (#12)"`.
PR_NUMBER = re.compile(r'\(#\d+\)')
NOT_TICKETS = {'FR', 'SC', 'UTF', 'ISO', 'SHA', 'CVE', 'RFC', 'HTTP'}
HOSTED = re.compile(r'(ubuntu|windows|macos)-(latest|\d[\w.]*)(-[a-z0-9]+)*', re.I)
GATE_QUESTION = 'Does GitHub start jobs on GitHub-hosted runners (such as ubuntu-latest) for this account?'
# Labels that many runners carry: two label lists name the same runner only by another one.
DEFAULT_LABELS = {'self-hosted', 'linux', 'windows', 'macos', 'x64', 'arm', 'arm64'}
HOOK_FILES = ('lefthook.yml', 'lefthook.yaml', '.lefthook.yml', '.lefthook.yaml', '.pre-commit-config.yaml')


def read(path):
    try:
        return path.read_text(encoding='utf-8-sig', errors='replace')
    except OSError:
        return ''


def load_json(path):
    try:
        data = json.loads(read(path))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def git(repo, *args):
    try:
        out = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def commands(root):
    """Commands that exist in this repository, by kind. Nothing here is proven safe to run."""
    found = {'test': [], 'lint': [], 'build': []}
    scripts = load_json(root / 'package.json').get('scripts')
    for name in scripts if isinstance(scripts, dict) else ():
        if name.startswith('test'):
            found['test'].append(f'npm run {name}')
        elif name in ('lint', 'typecheck', 'type-check'):
            found['lint'].append(f'npm run {name}')
        elif name == 'build':
            found['build'].append('npm run build')
    pyproject = read(root / 'pyproject.toml')
    runner = 'uv run ' if (root / 'uv.lock').is_file() else ''
    if 'laravel/pint' in read(root / 'composer.json'):
        found['lint'].append('./vendor/bin/pint --test')
    if (root / 'tsconfig.json').is_file() and 'vue-tsc' in read(root / 'package.json'):
        found['lint'].append('npx vue-tsc --noEmit')
    if (root / 'artisan').is_file():
        found['test'].append('php artisan test   # only with proof of an isolated test database')
    if (root / 'pytest.ini').is_file() or 'pytest' in pyproject:
        found['test'].append(f'{runner}pytest -q')
    if 'ruff' in pyproject:
        found['lint'].append(f'{runner}ruff check .')
    return found


def as_list(value):
    if value is None:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def triggers(workflow):
    """How pushes start this workflow: a list of entries {via, branches|'all', ignore, tags}."""
    on = workflow.get('on', workflow.get(True))   # YAML 1.1 reads the key `on` as true
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = {name: None for name in on}
    if not isinstance(on, dict):
        return []
    out = []
    for via in ('push', 'workflow_run'):
        if via not in on:
            continue
        spec = on[via] if isinstance(on[via], dict) else {}
        entry = {'via': via, 'branches': as_list(spec.get('branches')) or 'all'}
        if spec.get('branches-ignore'):
            entry['ignore'] = as_list(spec['branches-ignore'])
        if spec.get('tags'):
            entry['tags'] = as_list(spec['tags'])
            if not spec.get('branches'):
                entry['branches'] = []
        out.append(entry)
    return out


def runner_of(value):
    """A `runs-on` value as (kind, labels, text), the kind `hosted`, `own` or `unknown`."""
    labels = [str(v) for v in value] if isinstance(value, list) else [str(value)]
    if isinstance(value, dict):
        labels = [str(v) for v in (value.get('labels') if isinstance(value.get('labels'), list)
                                   else [value.get('labels') or value.get('group') or ''])]
    text = ', '.join(labels)
    if any(v.lower() == 'self-hosted' for v in labels):
        return 'own', labels, text
    if isinstance(value, dict) or any('${{' in v for v in labels):
        return 'unknown', labels, text      # an expression or a runner group: only GitHub knows
    if all(HOSTED.fullmatch(v) for v in labels):
        return 'hosted', labels, text
    return 'own', labels, text              # a custom label is a runner the project registered


def runners(repo, warnings):
    """Where this repository's workflows run. In a repository whose only runner is its own
    machine the gate runs there only when KIT_GATE_RUNNER names it, and asks for a hosted one otherwise."""
    import yaml
    found = {'hosted': set(), 'own': set(), 'unknown': set()}
    others = {'hosted': set(), 'own': set(), 'unknown': set()}     # every workflow but the kit's gate (009/FR-010)

    def walk(node, kinds):
        if isinstance(node, dict):
            for key, value in node.items():
                if key != 'runs-on':
                    walk(value, kinds)
                    continue
                kind, _, text = runner_of(value)
                for bucket in kinds:
                    bucket[kind].add(text)
        elif isinstance(node, list):
            for value in node:
                walk(value, kinds)

    files = sorted((repo / '.github' / 'workflows').glob('*.y*ml'))
    for wf in files:
        try:
            walk(yaml.safe_load(read(wf)), [found] if wf.name == 'kit-gate.yml' else [found, others])
        except Exception:      # push_workflows already warns about a file that cannot be read
            continue
    if others['own'] and not others['hosted']:      # a runner only GitHub knows hides no own runner
        warnings.append('every workflow here runs on the project\'s own runner: kit-gate.yml asks for ubuntu-latest '
                        'unless the repository variable KIT_GATE_RUNNER names a runner, as JSON ("team-runner" or '
                        '["self-hosted", "team-runner"]); gate_choice says where the gate is suggested to run')
    return {kind: sorted(texts) for kind, texts in found.items()}


def load_mapping(path):
    import yaml
    try:
        data = yaml.safe_load(read(path))
    except Exception:          # push_workflows already warns about a file that cannot be read
        return None
    return data if isinstance(data, dict) else None


def started_by(workflow, events):
    """True when the workflow's `on` names one of `events`, as a text, an item of a list or a key."""
    on = workflow.get('on', workflow.get(True))   # YAML 1.1 reads the key `on` as true
    if isinstance(on, str):
        return on in events
    return isinstance(on, (list, dict)) and any(str(name) in events for name in on)


def jobs_of(workflow):
    jobs = workflow.get('jobs')
    return [job for job in jobs.values() if isinstance(job, dict)] if isinstance(jobs, dict) else []


def asked_by(job):
    """The runner a job asks for as (kind, labels, text), or None; a job that calls a workflow asks for an unknown one."""
    if 'uses' in job:
        return 'unknown', None, str(job['uses'])
    return runner_of(job['runs-on']) if 'runs-on' in job else None


def workflows(repo, pushes):
    """Each workflow but the kit's gate, by file name as a text: its entry, the runners it asks for in
    order with the file each came through, and the runners its own jobs ask for (011/FR-001 to 011/FR-005)."""
    folder = repo / '.github' / 'workflows'
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.name.endswith(('.yml', '.yaml'))
                    and p.name != 'kit-gate.yml'), key=lambda p: p.name) if folder.is_dir() else []
    out, parsed = [], {}

    def called_mapping(name):
        """A called file, parsed once however many jobs call it."""
        if name not in parsed:
            parsed[name] = load_mapping(folder / name) if (folder / name).is_file() else None
        return parsed[name]

    for path in files:
        data = load_mapping(path)
        if data is None:
            continue
        asks, own_jobs, calls = [], [], []
        for job in jobs_of(data):
            called = _called_file(str(job['uses'])) if 'uses' in job else None
            callee = called_mapping(called) if called else None
            if callee is not None and started_by(callee, ('workflow_call',)):
                calls += [] if called in calls else [called]
                asks += [(*asked, called) for asked in map(asked_by, jobs_of(callee)) if asked]
                continue
            asked = asked_by(job)
            if asked:
                asks.append((*asked, None))
                own_jobs += [] if 'uses' in job else [asked]   # a job that calls a workflow deploys from nothing
        named = {'hosted': [], 'own': [], 'unknown': []}
        for kind, labels, text, _ in asks:
            value = labels if kind == 'own' else text
            named[kind] += [] if value in named[kind] else [value]
        push = pushes.get(path.name)
        out.append({'entry': {'workflow': path.name,
                              'pull_requests': started_by(data, ('pull_request', 'pull_request_target')),
                              'deploys': bool(push and isinstance(push['starts_on'], list) and push['deploy_hints']),
                              'calls': calls, 'runners': named},
                    'asks': asks, 'deploys_from': own_jobs})
    return out


def same_path(top, path, other):
    """True when two paths, a relative one taken from `top` and `\\` read as `/`, are one path."""
    def norm(p):
        return os.path.normcase(os.path.normpath(os.path.join(str(top), p.replace('\\', '/'))))
    return norm(path) == norm(other)


def hook_manager(repo):
    """What runs this clone's hooks, other than git's own hooks directory and a `.githooks`
    that holds only the kit's hook (011/FR-006 to 011/FR-008)."""
    top = Path(git(repo, 'rev-parse', '--show-toplevel') or repo)
    githooks = top / '.githooks'

    def kits_or_empty(path):
        text = read(path)
        return path == githooks / 'pre-push' and (KITS_HOOK.search(text) or not text.strip())
    kits_only = not githooks.is_dir() or all(kits_or_empty(p) for p in githooks.rglob('*') if p.is_file())
    found = []
    value = git(top, 'config', '--local', '--get', 'core.hooksPath')
    if value:
        common = git(top, 'rev-parse', '--git-common-dir')
        ours = ([os.path.join(common, 'hooks')] if common else []) + (['.githooks'] if kits_only else [])
        if value.startswith('~') or not any(same_path(top, value, p) for p in ours):
            found.append(f'core.hooksPath={value}')
    if not kits_only:
        found.append('.githooks/')
    if (top / '.husky').is_dir():
        found.append('.husky/')
    return found + [name for name in HOOK_FILES if (top / name).is_file()]


def same_runner(labels, other):
    """Two label lists name the same runner when they share a label that is not a default one,
    or when either holds default labels only."""
    a, b = ({v.lower() for v in side} - DEFAULT_LABELS for side in (labels, other))
    return not a or not b or bool(a & b)


def gate_choice(found, managers):
    """The first row of 011's table that applies: a suggested gate for each answer to the question,
    and why (011/FR-009 to 011/FR-011)."""
    pulls = [w for w in found if w['entry']['pull_requests']]
    deploying = [w for w in found if w['entry']['deploys']]

    def row(number, yes, no, why, labels=None):
        variable = None if labels is None else json.dumps(labels[0] if len(labels) == 1 else labels)
        return {'question': GATE_QUESTION, 'row': number, 'why': why, 'yes': yes, 'no': no,
                'labels': labels, 'variable': variable}

    def deploys_from(labels):
        return next((w['entry']['workflow'] for w in deploying for kind, own, _ in w['deploys_from']
                     if kind == 'own' and same_runner(labels, own)), None)

    if managers:
        return row(1, None, None, f"this clone's hooks are run by {', '.join(managers)}: the kit's hook would "
                                  f"replace them, so no gate is suggested")
    for w in pulls:
        for kind, labels, _, _ in w['asks']:
            deploy = deploys_from(labels) if kind == 'own' else None
            if deploy:
                return row(2, 'hook', 'hook', f"pull requests already start {w['entry']['workflow']} on the runner "
                                              f"{json.dumps(labels)}, which {deploy} deploys from: the hook is "
                                              f"suggested; answer runner where that risk is already accepted", labels)
    unknown = next(((w, text, via) for w in pulls for kind, _, text, via in w['asks'] if kind == 'unknown'), None)
    if unknown is None and any(kind == 'own' for w in pulls for kind, *_ in w['asks']):
        unknown = next(((w, text, None) for w in deploying for kind, _, text in w['deploys_from']
                        if kind == 'unknown'), None)
    if unknown:
        w, text, via = unknown
        name = w['entry']['workflow'] + (f' through {via}' if via else '')
        return row(3, None, 'hook', f'{name} asks for the runner {text}, which only GitHub knows: the hook is '
                                    f'suggested where GitHub starts no hosted job for this account, and no gate '
                                    f'where it does')
    safe = next(((w, labels) for w in pulls for kind, labels, *_ in w['asks'] if kind == 'own'), None)
    if safe:
        w, labels = safe
        return row(4, 'runner', 'runner', f"pull requests already start {w['entry']['workflow']} on the runner "
                                          f"{json.dumps(labels)}, which no workflow that deploys deploys from: "
                                          f"whoever may push a branch can then run a step on that machine by a "
                                          f"pull request", labels)
    return row(5, 'hosted', 'hook', "no workflow a pull request starts asks for a runner of this repository's own "
                                    "or for one only GitHub knows")


def reads_specs(repo, warnings):
    """Workflows that name `specs/`: a path filter or a script that walks the spec tree.

    The scaffold adds `specs/_living/`, `specs/README.md` and later `specs/INDEX.md`; a guard
    that expects every entry under specs/ to be a feature goes red on the very pull request
    that adopts the kit.
    """
    out = []
    for wf in sorted((repo / '.github' / 'workflows').glob('*.y*ml')):
        if wf.name == 'kit-gate.yml':
            continue                # the kit's own gate knows the layout
        try:
            if re.search(r'(?<![\w.-])(?:\./)?specs(?![\w-])', read(wf)):
                out.append(wf.name)
        except OSError:
            continue
    if out:
        warnings.append('these workflows read specs/ and may fail once specs/_living/ and specs/README.md exist: '
                        + ', '.join(out) + '. Read each one and run it before the first pull request')
    return out


def shell_words(text):
    """The words of a shell text as (word, quoted); a joining sign is a word with quoted None.

    One pass, no backtracking: a workflow is read whatever its length.
    """
    out, word, quoted, i, n = [], [], False, 0, len(text)

    def flush():
        nonlocal word, quoted
        if word or quoted:
            out.append((''.join(word), quoted))
        word, quoted = [], False

    while i < n:
        c = text[i]
        if c in '\'"':
            end = text.find(c, i + 1)
            end = n if end < 0 else end
            word.append(text[i + 1:end])
            quoted = True
            i = end + 1
            continue
        if c == '\n':
            flush()
            out.append((';', None))
        elif c in ' \t\r':
            flush()
        elif c in ';|&':
            flush()
            end = i
            while end < n and text[end] in ';|&':
                end += 1
            out.append((text[i:end], None))
            i = end
            continue
        elif c in '()`':
            flush()
            out.append((c, None))
        else:
            word.append(c)
        i += 1
    flush()
    return out


def names_in(command):
    """What a step runs, with each shell `cd` taken out: what is left may name a pipeline.

    A shell `cd` is the first word of a command, after assignments at most, and is not
    piped on (`cd|ci)` is an arm of a `case`). When unsure the word stays: a missed
    hint costs more than one too many.
    """
    words = shell_words(command.replace('\\\r\n', ' ').replace('\\\n', ' '))
    kept, start, shell, before = [], True, False, None
    for at, (word, quoted) in enumerate(words):
        if quoted is None:
            start, shell, before = word != ')', False, None
            continue
        if start and not quoted and word in OPENERS:
            continue
        if start and not quoted and ASSIGNMENT.match(word):
            kept.append(word)
            continue
        if start and not quoted and word in ('cd', 'cd..'):
            start = False
            after = words[at + 1] if at + 1 < len(words) else None
            if after in ((')', None), ('|', None)):
                kept.append(word)
            continue
        kept.append(names_in(word) if quoted and before == '-c' and shell else word)
        shell = shell or word.rsplit('/', 1)[-1] in SHELLS
        start, before = False, word
    return PATH_CD.sub('', ' '.join(kept))


def names_of(node, run_here=True):
    """Every key and text of a workflow; what a step runs itself, without its shell `cd`.

    Only `run` is read as shell, and not below `with`, `env` or a matrix: what is
    handed to an action may be anything, so a `cd` there stays.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            if key == 'run' and run_here and isinstance(value, str):
                yield names_in(value)
            else:
                yield from names_of(value, run_here and key not in NOT_SHELL_BELOW)
    elif isinstance(node, list):
        for value in node:
            yield from names_of(value, run_here)
    elif isinstance(node, str):
        yield node


def push_workflows(repo, warnings):
    """Every workflow a push can start, with the words that suggest it deploys.

    All of them are listed, not only the ones that look like a deploy: a deploy
    this script fails to recognise must still be in front of the user.
    """
    import yaml
    out = []
    for wf in sorted((repo / '.github' / 'workflows').glob('*.y*ml')):
        try:
            data = yaml.safe_load(read(wf))
            if not isinstance(data, dict):
                raise ValueError('not a mapping')
            started = triggers(data)
            rest = {k: v for k, v in data.items() if k not in ('on', True)}
            body = json.dumps(rest, default=str, ensure_ascii=False)
            names = '\n'.join(names_of(rest))
        except Exception as exc:   # any shape PyYAML or this walk cannot take: the user reads it by hand
            warnings.append(f'{wf.name}: could not be read ({type(exc).__name__}); check by hand whether it deploys')
            continue
        hints = {m.lower() for m in DEPLOY.findall(wf.stem + ' ' + body)}
        if CD.search(wf.stem + '\n' + names):
            hints.add('cd')
        hints = sorted(hints)
        if '"environment"' in body:
            hints.append('environment')
        if not started and not hints:
            continue
        out.append({'workflow': wf.name, 'starts_on': started or 'not a push: check by hand',
                    'deploy_hints': hints})
    return out


def tracker(repo):
    log = git(repo, 'log', '-300', '--no-merges', '--format=%s') or ''
    keys = Counter(k for k in re.findall(r'\b([A-Z][A-Z0-9]{1,9})-\d+\b', log) if k not in NOT_TICKETS)
    if keys and keys.most_common(1)[0][1] >= 3:
        return {'type': 'jira', 'id_pattern': rf'{keys.most_common(1)[0][0]}-\d+'}
    if len(re.findall(r'(?<![\w/])#\d+\b', PR_NUMBER.sub('', log))) >= 3:
        return {'type': 'github', 'id_pattern': r'#\d+'}
    return None


def interface(root):
    deps = {}
    pkg = load_json(root / 'package.json')
    for key in ('dependencies', 'devDependencies'):
        if isinstance(pkg.get(key), dict):
            deps.update(pkg[key])
    locales = {}
    for d in LOCALE_DIRS:
        base = root / d
        if base.is_dir():
            names = sorted({p.stem if p.is_file() else p.name for p in base.iterdir()
                            if LOCALE.fullmatch(p.stem if p.is_file() else p.name)})
            if names:
                locales[d] = names
    return {'frameworks': sorted(p for p in UI_PACKAGES if p in deps), 'locales': locales,
            'playwright': '@playwright/test' in deps or 'playwright' in json.dumps(pkg.get('scripts', ''))}


def existing(repo, root):
    """Signs that this is not a new project: use kit-adopt instead."""
    signs = [p for p in ('specs', '.specify/specs', 'docs/ARCHITECTURE.md', 'ARCHITECTURE.md') if (root / p).exists()]
    signs += [p for p in ('.claude/kit.yml', '.claude/skills', '.claude/agents') if (repo / p).exists()]
    lines = len(read(root / 'CLAUDE.md').splitlines())
    if lines:
        signs.append(f'CLAUDE.md ({lines} lines)')
    return signs


def sub_projects(root):
    """Directories one level down that look like projects of their own."""
    out = []
    for child in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')):
        kind = detect_profile(child)
        has_ui = bool(interface(child)['frameworks'])
        if kind != 'generic' or has_ui or (child / 'go.mod').is_file() or (child / 'specs').is_dir():
            out.append({'dir': child.name, 'profile': kind, 'interface': has_ui,
                        'has_process': bool(existing(child, child))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--project-root', default='.')
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    root = (repo / args.project_root).resolve()
    if not root.is_dir() or not root.is_relative_to(repo):
        print(f'{root} is not a directory inside {repo}')
        return 2
    try:
        import yaml  # noqa: F401
    except ImportError:
        # Without it the workflows a push starts cannot be read, and a deploy would go unseen.
        print('PyYAML is not installed (pip install pyyaml): nothing was read', file=sys.stderr)
        return 2
    warnings = []
    if git(repo, 'rev-parse', '--git-dir') is None:
        warnings.append('git is not available here or this is not a repository: tracker and default branch not read')
    elif git(repo, 'rev-parse', '--is-shallow-repository') == 'true':
        warnings.append('shallow clone: the ticket pattern is read from very few commits')
    # An empty reading from a repository that holds nothing is not "looked, found nothing wrong".
    empty = None
    if git(repo, 'rev-parse', '--git-dir') is not None:
        if git(repo, 'rev-parse', '--verify', '--quiet', 'HEAD') is None:
            empty = ('the repository has no commit, so nothing was detected from git: '
                     'the default branch, the tracker and the history were not read')
        elif not git(root, 'ls-files', '--', '.'):
            empty = (f'git tracks no file under the project root `{args.project_root}`, so nothing was detected '
                     f'from git there: the files in it are not tracked')
    # The remote's answer when it can be had; the local ref only records what was true at clone time.
    default_branch = None
    try:
        asked = subprocess.run(['git', '-C', str(repo), 'ls-remote', '--symref', 'origin', 'HEAD'],
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
                               # a private remote must fail, not open a password prompt nobody answers
                               env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'})
        found = re.search(r'^ref: refs/heads/(\S+)\tHEAD$', asked.stdout, re.M) if asked.returncode == 0 else None
        default_branch = found.group(1) if found else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    if default_branch is None:
        head = git(repo, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD') or ''
        default_branch = head.split('/', 1)[1] if '/' in head else None
        if default_branch:
            warnings.append(f'default_branch `{default_branch}` is what the clone recorded; the remote could not '
                            f'be asked, so check it on the host')
    pushes = push_workflows(repo, warnings)
    found = workflows(repo, {p['workflow']: p for p in pushes})
    managers = hook_manager(repo)
    readings = {
        'name': root.name,
        'profile': detect_profile(root),
        'sub_projects': sub_projects(root),
        'commands': commands(root),
        'default_branch': default_branch,
        'push_workflows': pushes,
        'runners': runners(repo, warnings),
        'workflows': [w['entry'] for w in found],
        'hook_manager': managers,
        'gate_choice': gate_choice(found, managers),
        'reads_specs': reads_specs(repo, warnings),
        'tracker': tracker(repo),
        'interface': interface(root),
        'already_has': existing(repo, root),
        'warnings': warnings,
    }
    if empty:       # last, after what could not be read
        warnings.append(empty)
    print(json.dumps(readings, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8 by default
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    try:
        sys.exit(main())
    except Exception as exc:      # a crash is "nothing was checked", never a verdict
        print(f'kit_detect.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
