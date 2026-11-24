---
name: code-shape
description: Rules that keep code simple and each part responsible for one thing (SOLID, KISS, no over-engineering), written so a reviewer can check them. Use when writing or reviewing code, when planning a feature's structure, and before opening a pull request.
---

# Code shape

Build the simplest thing that meets the spec, in the shape the project already uses. "Simple" and "clean" are not checkable; the rules below are.

A project's own skills and constitution add rules for its stack (where business logic lives, how modules talk). On the same question, the project's rule is the one to follow.

## Rules

1. **Follow the pattern that is there.** Before adding a class, a folder or a helper, find how the project already does the same kind of thing and do it that way. A new pattern needs a sentence in the pull request saying why the existing one does not fit.
2. **No abstraction before the second use.** No interface, base class, factory, strategy or generic helper for one caller. Write the direct code; extract when a second real caller arrives. Exception: the project's convention already requires the seam (for example a repository protocol per table).
3. **Nothing the spec did not ask for.** No option, flag, config key, hook or "future" parameter without a requirement behind it. Unused is deleted, not kept "just in case".
4. **One reason to change.** A class or module does one job. Business rules do not live in controllers, routes, UI components or migrations; they live where the project keeps them. If describing a function needs "and", split it.
5. **Depend on what is stable.** High-level rules do not import low-level detail directly when the project has a seam for it. Do not reach into another module's internals: use what it exposes.
6. **A new dependency is a decision.** Adding a library needs one line in the pull request: what it replaces and why writing it is worse. Before installing, open its registry page and check the name and its history; pin it in the lockfile (`security`, rules 11 to 15).
7. **Small change, small diff.** A fix touches the lines that are wrong. Renames, reformatting and "while I was here" go in their own commit or stay out.
8. **Errors are handled where something can be done about them.** No `catch` that swallows, no default that hides a missing value. If nothing can be done, let it fail loudly.

## Before opening a pull request

State these in the description. They are counts, not opinions:

- New files, new classes or modules, and new dependencies, next to the number of requirements the change implements.
- Every new abstraction (interface, base class, generic helper) and its callers today. One caller: say which convention requires it, or remove it.
- Anything added that no requirement names.

## Review questions

The clean-context review (stage 5 of the loop) answers these with file and line, in addition to "the 3 places most likely wrong":

1. What can be deleted while every test still passes? Try the two most likely candidates in a scratch copy, never in the working tree, and report the result.
2. Which new abstraction has one caller?
3. Where does a business rule sit in a controller, a view or a migration?
4. Which existing pattern in this repository does the change ignore?
5. Which option, parameter or branch is not required by the spec?

A finding of excess is fixed by removing code, not by adding a comment that explains it. More new abstractions than requirements implemented is a finding by itself.

A fix of a finding that changes what the code does in a case a term or a requirement of `spec.md` describes (narrower, wider or new) changes that text in the same pull request, with the owner's answer under Decisions. Left for later, the gap is found only at close, where the owner has to choose a side for code already released.
