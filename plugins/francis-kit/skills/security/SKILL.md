---
name: security
description: What to check when a change touches input from outside, permissions, secrets, files, queries, or adds a package - and how to add a dependency without installing one that does not exist. Use when writing or reviewing an endpoint, a form, an upload, a query, auth or session code, anything that reads environment or secrets, a test of code that calls an outside service, and before adding or upgrading any dependency.
---

# Security

Three layers, each doing what the others cannot. The short rules in `flow` are in front of every task. This skill loads when the work touches a risky surface. The machines (dependency audit, secret scan) catch what a reader misses. A long security text pasted into every prompt is not a layer: it is read once and then skimmed.

A project's own security skill, where it has one, names its surfaces and wins on the same question.

## When the change takes input from outside

1. Every value from a request, a file, a queue or another service is validated at the boundary: type, length, range, allowed values. Reject; do not repair.
2. Queries are parameterised. No string is built into SQL, a shell command, a path, a template or HTML.
3. A path from outside is resolved and checked to be inside the directory it should be in before the file is opened.
4. Output is encoded for where it lands. Raw HTML from a user is not rendered.

## When the change touches who may do what

5. The check is on the server, on every request, for the object asked for: "may this user read *this* invoice", not "is this user logged in".
6. Deny is the default. A new route, job or tool with no rule is closed, not open.
7. A test proves the refusal: the wrong user gets the refusal status, and the data did not change.

## Secrets and personal data

8. No secret in code, in a test, in a fixture, in a commit message or in a log line. Read it from the environment; fail at start when it is missing.
9. Logs and error messages carry ids, not passwords, tokens, identity numbers or full payloads. An error shown to a user says what to do, not what the server is.
10. A user's file is stored outside the web root and served only after the permission check.
11. A test reaches no real service: no live API, no message sent, no configured database, no broker or payment provider. It runs on a fake or a mock, with fake credentials, and a test that would reach one unfaked fails instead of passing. A command that pushes, sends, writes or deletes in production is run by hand, never by the suite.

## Adding or upgrading a package

An assistant can name a package that does not exist; someone can register that name with code of their own. So a new dependency is checked before it is installed, not after.

12. Open the package's page on its registry. It exists, the name is spelled as the project you meant spells it, and it has a history: releases over time, a source repository, real use. A package published last week with one release is not installed without the user saying so.
13. Ask first whether it is needed: what the standard library or a dependency the project already has would cost instead (`code-shape`, rule 6).
14. Pin it the way the project pins (the lockfile is committed, the version bounded). Never `latest`, never an unpinned URL or a git branch.
15. Run the manifest's `audit` commands after the change and paste the output. A known vulnerability with a fixed version is upgraded in this pull request; one without a fix is named in the description.
16. The pull request says: the package, the version, what it replaces, where you checked it.

## Review questions

The clean-context review answers these with file and line when the change touches a surface above:

1. Which value from outside reaches a query, a path, a command or a page without a check?
2. Which route or tool can be called by someone who should not, and which test shows the refusal?
3. Which secret or personal field can reach a log, an error message or the repository?
4. Which dependency is new, and does it exist under exactly that name with a history?
5. Which test can reach a real service, a real message or a production database, and what fakes it?

## What the machines do

Every project names its dependency audit under `audit` in `.claude/kit.yml` (S17): one command per package manager in use. It runs in CI and before a pull request that adds or upgrades a package. A red audit is fixed or named in the pull request; it is not skipped. A secret scan over the diff is recommended next to it and is listed with `lint`.
