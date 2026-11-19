#!/usr/bin/env python3
"""Check the shape of feature specs: size, one capability, open questions, fix lines.

    spec_lint.py --root DIR [FEATURE ...] [--strict]

FEATURE is a directory name under specs/ (`012-late-fee`) or its number; none
means every feature. The doctor checks that the lines exist (Status, Ticket,
checkboxes); this checks what they say.

Errors, exit 1
    no single valid Status line
    a requirement id declared twice under the Requirements heading of a Draft
    or Approved spec (a test table elsewhere may repeat ids)
    `[NEEDS CLARIFICATION` left in a spec that is Approved or later
    a top-level line under `## Fixes` in tasks.md that is not ticked, cites no `NNN/FR-001`,
    or cites a requirement no feature declares

Warnings, exit 1 only with --strict; judged on Draft and Approved specs, since
an earlier feature is not rewritten to fit
    more than 12 requirements (FR): split it
    no `**Capability**:` line, or one that names several capabilities
    a requirement with no checkable verb (MUST, SHOULD, MAY or their negations)
    in a Draft or Approved spec: a requirement that holds two behaviours, read as a
    second MUST, SHOULD, MAY, PHẢI, KHÔNG ĐƯỢC or NÊN in capitals (not the PHẢI
    of KHÔNG PHẢI), or `and also`, `as well as`, `và cũng`

Exit 2 when nothing could be judged.
"""
import argparse
import re
import sys
from pathlib import Path

import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'kit-init' / 'scripts'))
try:
    import kit_spec  # noqa: E402
except ImportError:        # the script was copied out of the kit: nothing was checked
    sys.exit(2 if print('spec_lint.py needs kit_spec.py from the kit (skills/kit-init/scripts)',
                        file=sys.stderr) is None else 2)

LIMIT = 12
EARLY = ('Draft', 'Approved')
# Where requirements are declared: the section whose heading says so. A test table or a
# traceability list elsewhere repeats ids on purpose and declares nothing.
SECTION = re.compile(r'^(#{1,4})[ \t]+(?:(?:Functional|Non-functional)[ \t]+)?(?:Requirements|Yêu cầu(?:[ \t]+chức năng)?)'
                     r'[ \t]*(?:\*[^\n]*)?$', re.M | re.I)
DECLARED = re.compile(rf'^[ \t]*(?:[-*][ \t]+|\d+\.[ \t]+)\**[ \t]*({kit_spec.ID})\**[ \t]*:[ \t]*'
                      r'((?:.*)(?:\n[ \t]+\S.*)*)', re.M)
HEADED = re.compile(rf'^#{{2,5}}[ \t]+\**({kit_spec.ID})\b', re.M)
VERB = re.compile(r'\b(?:MUST|SHALL|SHOULD|MAY|PHẢI|KHÔNG ĐƯỢC|NÊN)\b', re.I)
# Two behaviours under one id: a second obligation word, in capitals as a spec writes them, or a phrase that adds one.
# `KHÔNG PHẢI` is "is not", not an obligation; the text is read with its white space cut to one space.
OBLIGATION = re.compile(r'\b(?:MUST|SHOULD|MAY|(?<!KHÔNG )PHẢI|KHÔNG ĐƯỢC|NÊN)\b')
EMPHASIS = re.compile(r'\*+|(?<!\w)_+|_+(?!\w)')      # `*`, `**`, and `_`, `__` at the edge of a word
JOINED = re.compile(r'(?<!\w)(?:and also|as well as|và cũng)(?!\w)', re.I)
FIXES = re.compile(r'^#{2,3}[ \t]+Fixes\b[^\n]*$(.*?)(?=^#{1,3}[ \t]|\Z)', re.M | re.S | re.I)
# A top-level list item (a sub-step is not a fix). One without a checkbox is a fix nobody ticked.
BOX = re.compile(r'^(?:[-*+]|\d+[.)])[ \t]+(?:\[(.)\][ \t]*)?(.*)$', re.M)
CITE = re.compile(rf'(?<![\w/-])(\d{{3}})/({kit_spec.ID})(?![\w-])')
MARKER = re.compile(r'\[NEEDS CLARIFICATION[^\]]*\]?')
SEVERAL = re.compile(r',|;|(?<![-\w])(?:and|và)(?![-\w])|&')      # `billing-and-invoices` is one name


def features(specs):
    return [e for e in sorted(specs.iterdir()) if e.is_dir() and not e.is_symlink() and kit_spec.FEATURE_DIR.match(e.name)]


def requirement_sections(body):
    """The text under each heading that names requirements, up to the next heading of its level."""
    out, covered = [], 0
    for m in SECTION.finditer(body):
        if m.start() < covered:
            continue                # `### Functional Requirements` under `## Requirements`: already read
        stop = re.compile(rf'^#{{1,{len(m.group(1))}}}[ \t]', re.M).search(body, m.end())
        covered = stop.start() if stop else len(body)
        out.append(body[m.end():covered])
    return '\n'.join(out)


def lint(feature, declared_by):
    """Return (errors, warnings, notes, judged) for one feature directory."""
    errors, warnings, notes = [], [], []
    spec = kit_spec.read(feature / 'spec.md')
    if spec is not None:
        status = kit_spec.status(spec)
        if status is None:
            errors.append('no single valid Status line, so nothing else in the spec could be judged (S07)')
        declared = requirement_sections(kit_spec.REMOVED.sub('', kit_spec.body(spec)))
        raw = DECLARED.findall(declared)
        rows = [(ident, unicodedata.normalize('NFC', ' '.join(MARKER.sub(' ', text).split()))) for ident, text in raw]
        blocked = sorted({ident for ident, text in raw if ident.startswith('FR-') and MARKER.search(text)})
        # Where requirements are headings (`### FR-001 - ...`), a bullet under one is a note, not a declaration.
        headed = HEADED.findall(declared)
        ids = headed or [ident for ident, _ in rows]
        if status in EARLY:
            twice = sorted({i for i in ids if ids.count(i) > 1})
            if twice:
                errors.append(f'declared twice: {", ".join(twice)}')
        open_questions = kit_spec.prose(spec).count('[NEEDS CLARIFICATION')
        if status not in (None, 'Draft') and open_questions:
            errors.append(f'{status} with `[NEEDS CLARIFICATION` still in the spec')
        elif status == 'Draft' and open_questions:
            notes.append(f'{open_questions} open question(s): cannot be approved yet')
        if status == 'Draft' and blocked and 2 * len(blocked) > len({i for i in ids if i.startswith('FR-')}):
            warnings.append(f'{len(blocked)} of the requirements still hold an open question: '
                            f'what a test would prove is not written yet')
        if status in EARLY:
            count = len({i for i in kit_spec.requirements(spec) if i.startswith('FR-')})
            if count > LIMIT:
                warnings.append(f'{count} requirements, more than {LIMIT}: split it (STANDARD, "Three lanes")')
            capability = [MARKER.sub('', c).strip() for c in kit_spec.fields('Capability', spec)]
            capability = [c for c in capability if c]
            if not capability:
                warnings.append('no `**Capability**:` line: name the one capability this feature changes')
            elif len(capability) > 1 or SEVERAL.search(capability[0]):
                warnings.append(f'more than one capability ({"; ".join(capability)}): one feature, one capability')
            vague = sorted({i for i, text in rows if i.startswith('FR-') and not VERB.search(text)})
            if vague:
                warnings.append(f'no MUST, SHOULD or MAY in: {", ".join(vague)}')
        if status in EARLY:
            # Words a requirement quotes in backticks are its subject, not a second behaviour.
            # Emphasis is taken off after the code spans, so `**KHÔNG** PHẢI` reads as `KHÔNG PHẢI`.
            plain = [(i, EMPHASIS.sub('', kit_spec.CODE_SPAN.sub('', text))) for i, text in rows if i.startswith('FR-')]
            double = sorted({i for i, text in plain if len(OBLIGATION.findall(text)) > 1 or JOINED.search(text)})
            if double:
                warnings.append(f'two behaviours under one id (a second MUST, SHOULD, MAY, PHẢI, KHÔNG ĐƯỢC or NÊN, '
                                f'or "and also", '
                                f'"as well as", "và cũng"): {", ".join(double)}: one requirement, one behaviour')
    tasks = kit_spec.read(feature / 'tasks.md')
    if tasks is not None:
        # Code spans stay: a citation is often written in backticks.
        for section in FIXES.findall(kit_spec.COMMENT.sub('', kit_spec.FENCE.sub('', tasks))):
            for mark, text in BOX.findall(section):
                short = text.strip()[:60]
                cites = CITE.findall(text)
                if mark not in ('x', 'X'):
                    errors.append(f'fix not ticked: {short}')
                if not cites:
                    errors.append(f'fix cites no requirement as NNN/FR-001: {short}')
                for number, ident in cites:
                    if ident not in declared_by.get(number, set()):
                        errors.append(f'fix cites {number}/{ident}, which no feature declares: {short}')
    return errors, warnings, notes, spec is not None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--root', type=Path, default=Path('.'), help='project root (default: .)')
    ap.add_argument('features', nargs='*')
    ap.add_argument('--strict', action='store_true', help='warnings fail too')
    args = ap.parse_args(argv)
    specs = args.root.resolve() / 'specs'
    if not specs.is_dir():
        print(f'{specs} is missing', file=sys.stderr)
        return 2
    every = features(specs)
    asked = [n.zfill(3) if n.isdigit() else n for n in args.features]     # `2` is feature 002
    wanted = [f for f in every if not asked or f.name in asked or f.name[:3] in asked]
    missing = [n for n in asked if not any(n in (f.name, f.name[:3]) for f in every)]
    if missing or not wanted:
        print('no such feature: ' + ', '.join(missing) if missing else 'no feature under specs/', file=sys.stderr)
        return 2
    declared_by = {}
    for f in every:
        declared_by.setdefault(f.name[:3], set()).update(kit_spec.requirements(kit_spec.read(f / 'spec.md') or ''))
    failed = warned = read = 0
    for feature in wanted:
        errors, warnings, notes, judged = lint(feature, declared_by)
        read += judged
        for line in errors:
            print(f'ERROR {feature.name}: {line}')
        for line in warnings:
            print(f'WARN  {feature.name}: {line}')
        for line in notes:
            print(f'NOTE  {feature.name}: {line}')
        failed += bool(errors)
        warned += bool(warnings)
    if not read and not failed:
        print('no spec.md could be read: nothing was judged', file=sys.stderr)
        return 2
    print(f'spec_lint: {read} spec(s), {failed} with errors, {warned} with warnings')
    return 1 if failed or (args.strict and warned) else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:      # a crash is "nothing was checked", never "a spec is wrong"
        print(f'spec_lint.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
