#!/usr/bin/env python3
"""Create the files of the francis-kit standard that a repository lacks.

Usage: kit_scaffold.py --repo DIR [--project-root DIR] [--profile P] [--name NAME] [--dry-run]
                       [--gate] [--gate-at hosted|runner|hook|none [--runner-label LABEL ...]]

Never overwrites: an existing file (or symlink) is reported and left alone.
The one exception is asked for by name: --gate writes the gate file again from
this kit version, which is how a project moves to a newer gate. The gate file is
the one the manifest names: .github/workflows/kit-gate.yml, or .githooks/pre-push
under `gate: hook`. With a manifest there, PyYAML is needed to read which.
--gate-at is where the person answered the gate runs: its gate file is written,
and a manifest without the key `gate` gets the one line that names it.
Every run that writes or keeps a gate file, --dry-run included, first reads the commit of
the kit's tag with `git ls-remote` from kit.gateSource or the kit's repository, and writes
nothing when it cannot: the gate pins that commit, its tag beside it (spec 026).
The files it edits are .claude/settings.json, where it adds the kit keys
that are absent and keeps everything else, including a plugin the user turned
off, and that one line of .claude/kit.yml. It does not write the map: that is
traced from code by map-project.

--project-root puts the project's own files (CLAUDE.md, .specify/, specs/)
under that directory; .claude/ and .github/ always go to the git root.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit_doctor  # noqa: E402

KIT =Path(__file__).resolve().parents[3]
TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'
MARKETPLACE = 'francis-ai-coworking'
SOURCE = {'source': {'source': 'github', 'repo': 'dangthinh104/francis-ai-coworking'}}
PLUGIN = 'francis-kit@francis-ai-coworking'
PROFILES = ['laravel-vue', 'python', 'generic']
ANSWERS = {'hosted': 'workflow', 'runner': 'workflow', 'hook': 'hook', 'none': None}
# What keeps the printed gh line from pasting as it is, or turns one label into two.
NOT_IN_A_LABEL = re.compile('[ \t\'",]')
DEFAULT_SOURCE = 'https://github.com/dangthinh104/francis-ai-coworking.git'
LS_REMOTE_SECONDS = 60
NOTHING_SET = ('the kit sets nothing on GitHub: run it once in a POSIX shell (Git Bash on Windows), signed in as '
               "someone who may change the repository's variables")


def detect_profile(root):
    if (root / 'artisan').is_file() and (root / 'composer.json').is_file():
        return 'laravel-vue'
    if any((root / f).is_file() for f in ('pyproject.toml', 'requirements.txt', 'pytest.ini', 'setup.py')):
        return 'python'
    return 'generic'


def kit_ref():
    """The tag the gate pins to, or None when the kit has no usable version."""
    try:
        version = json.loads((KIT / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        return None
    return f'v{version}'


def git_config(repo, key):
    """What `git config --get <key>` prints in `repo`, or '' (also where git is missing)."""
    try:
        r = subprocess.run(['git', 'config', '--get', key], cwd=repo, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def shown_source(source):
    """The source as the hook prints it: the `user:pass@` of a URL taken out (010/FR-008)."""
    if '://' not in source:
        return source
    scheme, rest = source.split('://', 1)
    host, slash, path = rest.partition('/')
    return f'{scheme}://{host.rpartition("@")[2]}{slash}{path}'


def without_credential(text, source):
    """`text` with the `user:pass@` of `source` taken out, wherever git echoed it (on Windows, in its error)."""
    if '://' in source:
        host = source.split('://', 1)[1].partition('/')[0]
        if '@' in host:
            text = text.replace(host.rpartition('@')[0] + '@', '')
    return text


def kit_commit(repo, tag):
    """(the source, the commit of `tag` there, None) or (the source, None, why) (026/FR-003).

    The person's own credentials, no prompt: GIT_TERMINAL_PROMPT=0, ssh in batch mode unless the person set
    their own ssh command, and LS_REMOTE_SECONDS at most. Output goes to files, not pipes: an ssh that git
    started could hold a pipe open after git is stopped.
    """
    source = git_config(repo, 'kit.gateSource') or DEFAULT_SOURCE
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    if not {'GIT_SSH_COMMAND', 'GIT_SSH'} & set(env) and not git_config(repo, 'core.sshCommand'):
        env['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes'
    pattern = f'refs/tags/{tag}'
    posix = os.name == 'posix'
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(['git', 'ls-remote', source, pattern, pattern + '^{}'], cwd=repo, env=env,
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=posix)
        except OSError as exc:
            return source, None, f'git could not be started ({exc})'
        try:
            code = proc.wait(timeout=LS_REMOTE_SECONDS)
        except subprocess.TimeoutExpired:
            if posix:
                os.killpg(proc.pid, signal.SIGKILL)
            else:   # git's helper (git-remote-https, ssh) is a child of git: stop the tree
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
                proc.kill()
            proc.wait()
            return source, None, f'timed out after {LS_REMOTE_SECONDS} seconds'
        out.seek(0)
        err.seek(0)
        lines = out.read().decode('utf-8', 'replace').splitlines()
        said = [l.strip() for l in err.read().decode('utf-8', 'replace').splitlines() if l.strip()]
    if code != 0:
        fatal = [l[len('fatal:'):].strip() for l in said if l.startswith('fatal:')]
        why = (fatal or said)[0].rstrip('.') if said else f'git exited {code}'
        return source, None, without_credential(why, source)
    found = dict(reversed(l.split('\t', 1)) for l in lines if '\t' in l)
    commit = found.get(pattern + '^{}') or found.get(pattern)
    if not commit or not re.fullmatch(r'[0-9a-f]{40}', commit):
        return source, None, f'no tag {tag}'
    return source, commit, None


def gate_of(repo):
    """(the gate the manifest names, None, the manifest) or (None, why it cannot be known, None).
    No manifest: the workflow, and no manifest."""
    path = repo / '.claude' / 'kit.yml'
    if not os.path.lexists(path):
        return 'workflow', None, None
    text = kit_doctor.read(path)
    data, problem = kit_doctor.load_yaml(text) if text is not None else (None, 'cannot be read')
    problem = problem or kit_doctor.gate_problem(data)
    if problem:
        return None, problem, None
    return kit_doctor.gate_named(data), None, data


def option_problem(args):
    """Options that do not go together, then a label that cannot be pasted, or None (012/FR-004, 012/FR-005)."""
    if args.gate_at == 'runner' and args.runner_label is None:
        return '--gate-at runner needs --runner-label, once per label of the runner'
    if args.runner_label is not None and args.gate_at != 'runner':
        return '--runner-label goes only with --gate-at runner'
    if args.gate and args.gate_at == 'none':
        return '--gate does not go with --gate-at none, which writes no gate file'
    for label in args.runner_label or ():
        if not label or label.startswith('-') or NOT_IN_A_LABEL.search(label):
            shown = label.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')   # one line, always
            return (f"--runner-label '{shown}' would not paste as one label: a label is not empty, does not "
                    f"start with -, and holds no space, tab, quote or comma")
    return None


def with_gate_line(text, gate):
    """`text` with `gate: <gate>` directly below its first line that starts with `version:`, with that
    line's line end, or None where no line does (012/FR-001)."""
    lines = re.findall(r'[^\n]*\n|[^\n]+$', text)
    for at, line in enumerate(lines):
        if line.lstrip('﻿').startswith('version:'):
            end = '\r\n' if line.endswith('\r\n') else '\n'
            if not line.endswith('\n'):
                lines[at], end = line + '\n', ''
            lines.insert(at + 1, f'gate: {gate}{end}')
            return ''.join(lines)
    return None


def gate_refusal(repo, args, gate, data, manifest_text):
    """Why the gate cannot be written as asked, the first in the spec's order, or None
    (012/FR-006, 012/FR-010, 010/FR-011, 012/FR-009)."""
    answered = ANSWERS.get(args.gate_at) is not None
    if answered and data is not None and 'gate' in data and kit_doctor.gate_named(data) != gate:
        return (f'.claude/kit.yml names the gate {kit_doctor.gate_named(data)} and --gate-at {args.gate_at} the '
                f'{gate}: set gate: {gate} in .claude/kit.yml by hand first')
    if answered and data is not None and 'gate' not in data and with_gate_line(manifest_text, gate) is None:
        return '.claude/kit.yml has no version: line to write gate: below'
    workflow = repo / '.github' / 'workflows' / 'kit-gate.yml'
    workflow_there = os.path.lexists(workflow) and (workflow.is_symlink() or not workflow.is_dir())
    if args.gate and data is None and (answered or (args.gate_at is None and not workflow_there)):
        return 'there is no .claude/kit.yml to name the gate: run it without --gate first'     # 018/FR-001
    if args.gate_at == 'hook':
        from kit_detect import hook_manager     # not at the top: kit_detect imports this module
        managers = hook_manager(repo)
        if managers:
            return (f"this clone's hooks are run by {', '.join(managers)}, which the kit's hook would replace: "
                    f"answer hosted or runner")
    hook = kit_doctor.read(repo / '.githooks' / 'pre-push')
    if gate == 'hook' and hook is not None and hook.strip() and not kit_doctor.KITS_HOOK.search(hook):
        return ".githooks/pre-push is a hook of the project's own (no line starts with KIT_REF=) and the manifest names the hook"
    if answered and gate == 'hook' and (repo / '.github' / 'workflows' / 'kit-gate.yml').is_file():
        return ('.github/workflows/kit-gate.yml is there and --gate-at hook names the hook: '
                'a project holds one gate: remove it first')
    if answered and gate == 'workflow' and kit_doctor.KITS_HOOK.search(hook or ''):
        return (f".githooks/pre-push is the kit's hook and --gate-at {args.gate_at} names the workflow: "
                f"a project holds one gate: remove it first")
    return None


def write_new(path, text, mode=None):
    """Write a whole file in one replace: a failed write leaves nothing half-made."""
    body = text.encode('utf-8')       # fails here, before anything is on disk
    # A fresh, unpredictable name beside the target: a planted file or symlink is never
    # written through, and a failed write leaves the old file and no leftover.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.kit-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(body)
        if path.is_file():
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def load_settings(path):
    """Return (settings dict, newline, error)."""
    if not os.path.lexists(path):
        return {}, '\n', None
    if path.is_symlink():
        return None, '\n', 'a symlink, which is not followed'
    try:
        raw = path.read_bytes().decode('utf-8')
        bom = raw.startswith('\ufeff')
        data = json.loads(raw.lstrip('\ufeff'))
    except (OSError, ValueError) as exc:
        return None, '\n', f'not valid JSON ({exc})'
    newline = ('\ufeff' if bom else '') + ('\r\n' if '\r\n' in raw else '\n')
    if not isinstance(data, dict):
        return None, '\n', 'not a JSON object'
    for key in ('extraKnownMarketplaces', 'enabledPlugins'):
        if key in data and not isinstance(data[key], dict):
            return None, '\n', f'`{key}` is not an object'
    return data, newline, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--repo', type=Path, required=True, help='git root')
    ap.add_argument('--project-root', default='.', help='project directory under the repo')
    ap.add_argument('--profile', choices=PROFILES)
    ap.add_argument('--name')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--gate', action='store_true',
                    help='write the gate file the manifest names again from this kit version: '
                         '.github/workflows/kit-gate.yml, or .githooks/pre-push under `gate: hook`. The one file '
                         'that is replaced, because it holds what starts kit_gate.py')
    ap.add_argument('--gate-at', choices=list(ANSWERS),
                    help='where the gate runs, as the person answered: hosted and runner write the workflow, hook '
                         'the hook, none no gate file; a manifest without the key gate gets the line that names it')
    ap.add_argument('--runner-label', action='append', metavar='LABEL',
                    help='with --gate-at runner, once per label of the runner: the command that sets the '
                         'repository variable is printed for a person to run, never run')
    args = ap.parse_args(argv)
    problem = option_problem(args)
    if problem:
        print(f'ERROR   {problem}. Nothing was written.')
        return 1
    status = scaffold(args)
    if status == 0 and args.gate_at == 'runner':
        labels = args.runner_label
        print(f"gh variable set KIT_GATE_RUNNER --body '{json.dumps(labels[0] if len(labels) == 1 else labels)}'")
        print(NOTHING_SET)
    return status


def scaffold(args):
    repo = args.repo.resolve()
    root = (repo / args.project_root).resolve()
    if not repo.is_dir() or not root.is_dir() or (root != repo and repo not in root.parents):
        print('--repo must be a directory and --project-root a directory inside it', file=sys.stderr)
        return 2
    rel_root = '.' if root == repo else root.relative_to(repo).as_posix()

    settings_path = repo / '.claude' / 'settings.json'
    settings, newline, error = load_settings(settings_path)
    if error:
        print(f'ERROR   .claude/settings.json is {error}; fix it by hand first. Nothing was written.')
        return 1

    ref = kit_ref()
    if ref is None:
        print('ERROR   the kit has no semver `version` in its plugin.json, so the gate cannot be '
              'pinned to a tag. Nothing was written.')
        return 1
    named, problem, data = gate_of(repo)
    if problem:
        print(f'ERROR   .claude/kit.yml {problem}: the gate it names cannot be known. Nothing was written.')
        return 1
    manifest = repo / '.claude' / 'kit.yml'
    gate = ANSWERS[args.gate_at] if args.gate_at else named
    add_key = data is not None and 'gate' not in data and args.gate_at not in (None, 'none')
    try:
        manifest_text = manifest.read_bytes().decode('utf-8') if add_key else None
    except UnicodeDecodeError:
        print('ERROR   .claude/kit.yml is not UTF-8 text: the gate line cannot be added to it. Nothing was written.')
        return 1
    refusal = gate_refusal(repo, args, gate or named, data, manifest_text)
    if refusal:
        print(f'ERROR   {refusal}. Nothing was written.')
        return 1
    if gate == 'hook':
        gate_target, gate_template = repo / '.githooks' / 'pre-push', TEMPLATES / 'common' / 'pre-push'
    else:
        gate_target, gate_template = repo / '.github' / 'workflows' / 'kit-gate.yml', TEMPLATES / 'common' / 'kit-gate.yml'

    profile = args.profile or detect_profile(root)
    name = args.name or (repo.name if root == repo else root.name)
    fills = {'{{NAME}}': json.dumps(name), '{{TITLE}}': name,
             '{{ROOT}}': json.dumps(rel_root), '{{KIT_REF}}': ref}
    plan = [
        (root / 'CLAUDE.md', TEMPLATES / 'common' / 'CLAUDE.md'),
        (manifest, TEMPLATES / 'profiles' / f'{profile}.yml'),
        (root / '.specify' / 'memory' / 'constitution.md', TEMPLATES / 'common' / 'constitution.md'),
        (root / 'specs' / 'README.md', TEMPLATES / 'common' / 'specs-README.md'),
        (root / 'specs' / '_living' / 'README.md', TEMPLATES / 'common' / 'living-README.md'),
        (gate_target, gate_template),
    ]
    if gate is None:
        plan = plan[:-1]          # --gate-at none: no gate file
    mode = 0o755 if gate == 'hook' else None
    if args.gate:
        # the gate, and the one line of a manifest that lacks the key: no other file is created or touched
        plan = [(t, s) for t, s in plan if t == gate_target or (t == manifest and add_key)]
    for target, _ in plan:
        for parent in target.relative_to(repo).parents:
            blocker = repo / parent
            if os.path.lexists(blocker) and (blocker.is_symlink() or not blocker.is_dir()):
                print(f'ERROR   {parent} exists and is not a plain directory. Nothing was written.')
                return 1
    if args.gate and gate_target in dict(plan) and gate_target.is_symlink():
        print(f'ERROR   {gate_target.relative_to(repo).as_posix()} is a symlink, which is not written through. '
              f'Replace it with a file.')
        return 1
    if gate is not None:
        source, commit, why = kit_commit(repo, ref)
        if commit is None:
            print(f'ERROR   could not read the commit of {ref} from {shown_source(source)}: {why}. '
                  f'Nothing was written.')
            return 1
        fills['{{KIT_COMMIT}}'] = commit
    if not (repo / '.git').exists():
        print('note: --repo has no .git; .claude/ and .github/ belong at the git root')
    print(f'profile: {profile}')
    if profile == 'generic' and root == repo:
        nested = sorted(p.parent.name for pat in ('*/artisan', '*/pyproject.toml', '*/requirements.txt')
                        for p in repo.glob(pat))
        if nested:
            print(f'note: no code markers at the root but found projects in: {", ".join(nested)}. '
                  f'For a monorepo run once per project with --project-root.')

    for target, template in plan:
        rel = target.relative_to(repo).as_posix()
        if args.gate and target == gate_target and target.is_symlink():
            print(f'ERROR   {rel} is a symlink, which is not written through. Replace it with a file.')
            return 1
        if target == manifest and add_key:
            print(f'  update  {rel} (gate: {gate})')
            if not args.dry_run:
                write_new(manifest, with_gate_line(manifest_text, gate))
            if rel_root != '.':
                print(f'          add a project entry with root {rel_root!r} by hand')
            continue
        if args.gate and target.is_file():
            fresh = re.sub(r'\{\{[A-Z_]+\}\}', lambda m: fills.get(m.group(0), m.group(0)),
                           template.read_text(encoding='utf-8'))
            if target.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n') == fresh:
                print(f'  kept    {rel} (already the gate of {ref})')
            else:
                print(f'  replace {rel} (the gate of {ref})')
                if not args.dry_run:
                    write_new(target, fresh, mode)
            continue
        if os.path.lexists(target):
            print(f'  kept    {rel}')
            if rel == '.claude/kit.yml' and rel_root != '.':
                print(f'          add a project entry with root {rel_root!r} by hand')
            continue
        print(f'  create  {rel}')
        if args.dry_run:
            continue
        text = re.sub(r'\{\{[A-Z_]+\}\}', lambda m: fills.get(m.group(0), m.group(0)),
                      template.read_text(encoding='utf-8'))
        if target == manifest and gate is not None and args.gate_at:
            text = with_gate_line(text, gate)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_new(target, text, mode if target == gate_target else None)
    if gate == 'hook':
        print('  then, once per repository: git add --chmod=+x .githooks/pre-push')
        print('  and once per clone:        git config core.hooksPath .githooks')
    if args.gate:
        return 0

    changed = False
    markets = settings.setdefault('extraKnownMarketplaces', {})
    if MARKETPLACE not in markets:
        markets[MARKETPLACE] = SOURCE
        changed = True
    plugins = settings.setdefault('enabledPlugins', {})
    if PLUGIN not in plugins:
        plugins[PLUGIN] = True
        changed = True
    elif plugins[PLUGIN] is not True:
        print('  note    the kit plugin is turned off in .claude/settings.json; left as it is')
    if not changed:
        print('  kept    .claude/settings.json')
    else:
        print('  update  .claude/settings.json (kit keys added)')
        if not args.dry_run:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            bom, eol = newline[:-len(newline.lstrip('\ufeff'))], newline.lstrip('\ufeff')
            text = json.dumps(settings, indent=2, ensure_ascii=False) + '\n'
            write_new(settings_path, bom + text.replace('\n', eol))
    return 0


if __name__ == '__main__':
    if sys.version_info < (3, 9):
        sys.exit('kit_scaffold.py needs Python 3.9 or newer')
    for _stream in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8 by default
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    try:
        sys.exit(main())
    except (OSError, UnicodeError) as exc:
        print(f'ERROR   could not write: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
    except Exception as exc:      # a crash is "nothing was written for sure", never the refusal that exits 1
        print(f'kit_scaffold.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
