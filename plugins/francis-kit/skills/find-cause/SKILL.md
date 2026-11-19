---
name: find-cause
description: How to find why something fails before changing it - show the failure, state the cause with its evidence, test one hypothesis at a time, and stop when the fixes keep failing. Use on a bug, a failing test, a finding of a code review or behaviour nobody expected, before a fix is proposed - and when the failure is not known yet: asked to check the logs, whether everything is running, or whether today's job, upload or email went out.
---

# Find the cause

A change that makes a test pass without saying why it failed is not a fix: the next review finds what it broke. After repeated fixes of the same thing, the approach is wrong, not the last patch.

This skill is entered from wherever a failure shows: the Fix lane, a failing test while building, a finding of a code review. It relies on rules that live elsewhere and changes none: where a fix is recorded (`STANDARD.md`, "A fix belongs to a feature"), how small it is (`code-shape`, rule 7), what counts as done (`flow`, rule 2), and where a correction from the user goes (`flow`, rule 4).

## Rules

1. **Show the failure first.** Before changing anything but a test that shows it, show the failure: the command you ran with the output it gave, or, for a failure that happens only on a runner, the lines of that run's log. When a system people use is down, restoring it (a rollback, a switch turned off) may come first; the change that broke it is not put back before its cause is stated (rule 3).
2. **Not reproduced is a result.** A failure you could not make happen, or one that passes on some runs with no change made, is reported as not reproduced, with what was tried and how many runs. Report nothing as fixed.
3. **State the cause before the fix.** Before proposing a fix, state the cause in one sentence that names where it is (a line, an input, a setting, a version, an order of events), followed by the evidence that shows it. A sentence the evidence does not show is called a hypothesis.
4. **One hypothesis at a time.** Test one stated hypothesis at a time, by the smallest change that can show it true or false.
5. **Undo what did not work.** A change that did not remove the failure is undone before the next one is made.
6. **A fix comes with a test that fails without it.** Paste both runs: without the fix and with it. Where the code has no test to add one to, the command of rule 1 run before and after stands for it.
7. **Stop after 3 failed fixes of the same failure.** List each with its result, say that the approach is in question, and ask the owner. The same failure is the command of rule 1 still failing. A failed fix is a change proposed as the fix after which it still fails. A change made to test a hypothesis (rule 4) is not counted.
8. **Stop the same way after 3 review reports in a row** that each found a defect in the same function, or in the same named pattern where the code is a pattern. In a row means with no review between them that found nothing in that function.
9. **No test is weakened to pass.** No test is deleted, skipped or made to assert less so that a run passes. A test that is itself wrong is fixed like anything else, with its cause stated (rule 3).

The counts of rules 7 and 8 are read from what was written down: the pull request, the commits and the lines under `## Fixes`.

## Review questions

A reviewer of a fix answers these, and sends the fix back by the number of the question it does not answer:

1. Where is the command that shows the failure, or the runner's log, with the output it gave before anything changed?
2. Which sentence names the cause and where it is, and what evidence shows it?
3. Which test fails without the fix, and are both runs pasted?
4. Was a test deleted, skipped or made to assert less so that the run passes?
