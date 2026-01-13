# Fix Plan

Prioritized task checklist from TASKS.json. Tasks are ordered by priority (P0 > P1 > P2 > P3).

## Pending Tasks

### P3 - Code Quality

- [ ] **T-300**: Fix linting issues (line length, imports)
  - Line too long (>100 chars) in notion/client.py lines 134, 136
  - Import sorting (I001) in briefing.py
  - Import from collections.abc instead of typing for Callable in always_on.py (UP035)
  - Rename AlwaysOnListenerNotAvailable to AlwaysOnListenerNotAvailableError (N818)

- [ ] **T-301**: Fix mypy type errors in llm_client.py
  - Line 78: Dict entry has incompatible type str: tuple[float, float] expected str: dict[str, tuple[float, float]]
  - Line 88: Unsupported operand types for / (str and int)
  - Line 468: Incompatible types in assignment (None vs LLMProvider)

- [ ] **T-302**: Fix mypy type errors in comparison_sheet.py
  - Lines 303-305: Incompatible argument types for Task constructor
  - status, priority, and source arguments are str but expect enum types

- [ ] **T-303**: Fix mypy type errors in email_auto_reply.py
  - Lines 287-288: Argument key to max has incompatible type
  - Line 510: Unexpected keyword arguments for create_pattern
  - Line 528: Unexpected keyword argument pattern_type for query_patterns
  - Lines 536, 544: dict[str, Any] has no attribute trigger/confidence

- [ ] **T-304**: Fix mypy type errors in whatsapp/handlers.py
  - Line 164: CorrectionHandler has no attribute handle_correction
  - Lines 174, 277, 295, 336: Unexpected keyword argument source for process()
  - Lines 187, 309: ProcessResult has no attribute task_title
  - Line 240: Argument 1 to transcribe has incompatible type BytesIO

- [ ] **T-305**: Fix mypy type error in telegram/handlers.py
  - Line 417: Incompatible types in assignment (BinaryIO vs bytes)

- [ ] **T-306**: Remove redundant casts in notion/client.py
  - Lines 618 and 1064 have redundant cast to dict[str, Any]

- [ ] **T-307**: Replace deprecated datetime.utcnow() calls
  - Use datetime.datetime.now(datetime.UTC) instead
  - Affected: patterns.py:510, notion/client.py:992, soft_delete.py:42, test files

## Verification

After completing each task:
1. Run `ruff check src tests` for linting
2. Run `mypy src --ignore-missing-imports` for type checking
3. Run `pytest` to ensure tests still pass
4. Commit and push changes
