# @fix_plan.md — Priority Task List

**Last updated:** 2026-01-12
**Source:** .ralph/TASKS.json

This file tracks the prioritized work items for Ralph autonomous loops. Update as tasks complete.

---

## High Priority (P0 - Must Complete)

### Core NLP Pipeline
- [x] T-052: Create entity extraction service
- [x] T-053: Implement confidence scoring
- [x] T-054: Build classification router

### Voice Processing
- [x] T-062: Integrate Whisper transcription
- [x] T-063: Implement voice message handler

### Entity Management
- [x] T-070: Implement People lookup/create
- [x] T-071: Implement Places lookup/create
- [x] T-072: Implement Projects lookup
- [x] T-073: Build relation linker

### Response Handling
- [x] T-065: Implement low-confidence flagging

---

## Medium Priority (P1 - Should Complete)

- [x] T-080: Implement morning briefing generator
- [x] T-081: Create scheduled briefing sender
- [x] T-082: Implement /debrief command
- [x] T-083: Build interactive clarification flow
- [x] T-090: Implement correction handler
- [x] T-091: Build pattern detection
- [x] T-092: Implement pattern storage
- [x] T-093: Apply patterns to new inputs
- [x] T-100: Implement Google Calendar OAuth
- [x] T-101: Create calendar event creator
- [x] T-102: Implement calendar reading
- [x] T-110: Implement comprehensive audit logging
- [x] T-114: Implement offline queue and recovery
- [x] T-115: Implement soft delete and undo
- [x] T-116: Implement timezone handling

---

## Lower Priority (P2 - Nice to Have)

- [ ] T-120: Gmail read integration
- [ ] T-121: Gmail draft creation
- [ ] T-130: Proactive nudges

---

## Completed

- [x] T-000: Initialize loop state + runbook
- [x] T-001: Design knowledge base schema
- [x] T-002: Implement task data structure
- [x] T-003: Create conversation logging system
- [x] T-005: Implement no-progress stuck detection
- [x] T-006: Implement same-error stuck detection
- [x] T-007: Implement cost tracking
- [x] T-008: Implement sandbox enforcement
- [x] T-009: Implement learning database
- [x] T-010: Implement task execution engine
- [x] T-011: Implement knowledge base retrieval
- [x] T-012: Implement Claude Code CLI integration
- [x] T-013: Create bootstrap script
- [x] T-014: Create verify script
- [x] T-015: Create run script
- [x] T-016: Create smoke test script
- [x] T-050: Create Notion workspace structure
- [x] T-051: Implement Notion API client
- [x] T-060: Create Telegram bot
- [x] T-061: Implement text message handler
- [x] T-064: Build response generator

---

## Notes

- Start with minimal viable implementations
- Maintain thorough testing for all changes
- Update this file as milestones are reached
- Refer to PRD.md for detailed acceptance criteria
- Task dependencies are tracked in .ralph/TASKS.json
