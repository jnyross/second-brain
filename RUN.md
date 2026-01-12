# RUN.md — Ralph Loop Task Directive

Execute one iteration of the Ralph Loop Contract (Prompt.md).

## Your Task NOW

1. **Read** `@fix_plan.md` to find the next incomplete task (marked `[ ]`)
2. **Read** `.ralph/TASKS.json` for task details and dependencies
3. **Implement** the task with tests that would fail without the implementation
4. **Run** `scripts/verify.sh` (or equivalent) to validate
5. **Update** `.ralph/TASKS.json` (mark task complete with evidence)
6. **Append** to `.ralph/PROGRESS.md` with iteration entry
7. **Commit** changes with descriptive message

## Rules

- Do NOT ask questions or seek clarification - derive intent from PRD.md
- Do NOT summarize or explain the contract - EXECUTE it
- Do NOT skip the commit step
- Make exactly ONE task's worth of progress per iteration

## Required Output

End your response with the status block:

```
---RALPH_STATUS---
STATUS: IN_PROGRESS
TASKS_COMPLETED_THIS_LOOP: <0 or 1>
FILES_MODIFIED: <count>
TESTS_STATUS: PASSING | FAILING | NOT_RUN
WORK_TYPE: IMPLEMENTATION | TESTING | DOCUMENTATION | REFACTORING
EXIT_SIGNAL: false
RECOMMENDATION: <next task ID>
---END_RALPH_STATUS---
```

Set `EXIT_SIGNAL: true` ONLY when ALL tasks in @fix_plan.md are complete.

**GO.**
