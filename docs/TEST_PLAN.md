# Second Brain Bot - Comprehensive Test Plan

## Overview

This document defines the complete test plan for the Second Brain Telegram bot, covering all functional areas with expected results.

**Test Execution**: `python scripts/comprehensive_bot_test.py`

---

## Test Categories

| Category | Tests | Description |
|----------|-------|-------------|
| commands | 6 | Slash command handlers (/start, /help, etc.) |
| tasks | 5 | Task creation with various attributes |
| ambiguous | 3 | Low confidence / unclear messages |
| reminders | 2 | Reminder creation with times |
| people | 2 | Person name extraction and linking |
| dates | 4 | Date/time parsing scenarios |
| places | 2 | Place name recognition |
| email | 1 | Email integration queries |
| notion | 1 | Notion connectivity verification |
| edge_cases | 4 | Unicode, long messages, special chars |

**Total: 30 test cases**

---

## Detailed Test Cases

### 1. Command Handlers

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| CMD-001 | start_command | `/start` | Welcome message with intro | Contains "welcome" or "hello", lists commands |
| CMD-002 | help_command | `/help` | Help text with commands | Contains command list (/today, /debrief, etc.) |
| CMD-003 | today_command | `/today` | Today's schedule | Shows calendar events OR "nothing scheduled" |
| CMD-004 | status_command | `/status` | Task status overview | Shows pending/progress tasks or "no tasks" |
| CMD-005 | debrief_command | `/debrief` | Starts review or "all clear" | Begins debrief session or confirms nothing pending |
| CMD-006 | setup_google_command | `/setup_google` | OAuth status/link | Shows Google connection status or OAuth URL |

### 2. Task Creation

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| TASK-001 | simple_task | "Buy groceries tomorrow" | Task confirmation | "got it" + task created, NOT offline/queued |
| TASK-002 | task_with_time | "Call dentist at 3pm" | Task with time | Acknowledges task with time parsed |
| TASK-003 | task_with_person | "Meet with Sarah about the project" | Task + person link | Mentions Sarah, task created |
| TASK-004 | task_with_place | "Dinner at Olive Garden on Friday" | Task + place | Recognizes Olive Garden as place |
| TASK-005 | urgent_task | "URGENT: Submit tax forms by end of day" | High priority task | Marked urgent/high priority |

### 3. Ambiguous / Low Confidence

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| AMB-001 | ambiguous_message | "hmm maybe later" | Inbox or clarification | Goes to inbox OR asks for clarification |
| AMB-002 | single_word | "interesting" | Acknowledgment | Noted or asks what to do with it |
| AMB-003 | question_message | "Should I go to the meeting?" | Question handling | Doesn't create task, handles appropriately |

### 4. Reminders

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| REM-001 | reminder_tomorrow | "Remind me to water plants tomorrow morning" | Reminder created | Tomorrow + morning parsed, task created |
| REM-002 | reminder_specific_time | "Remind me at 9am to take medication" | Reminder with time | 9am parsed correctly |

### 5. People Mentions

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| PPL-001 | mention_person_task | "Ask John about the report" | Person extracted | John recognized, linked to task |
| PPL-002 | multiple_people | "Schedule meeting with Alice and Bob" | Multiple people | Both Alice and Bob recognized |

### 6. Dates and Times

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| DATE-001 | relative_date_tomorrow | "Finish report tomorrow" | Tomorrow parsed | Correct date assigned |
| DATE-002 | relative_date_next_week | "Review budget next Monday" | Next Monday parsed | Correct Monday date |
| DATE-003 | specific_date | "Conference on January 25th" | Specific date parsed | January 25 recognized |
| DATE-004 | time_with_timezone | "Call at 2pm EST" | Time + timezone | 2pm EST handled |

### 7. Places

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| PLC-001 | task_with_restaurant | "Lunch at Chipotle tomorrow" | Restaurant recognized | Chipotle as place |
| PLC-002 | task_with_office | "Meeting at the downtown office at 10am" | Office location | Downtown office recognized |

### 8. Email Queries

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| EMAIL-001 | email_status_query | "Do I have any important emails?" | Email status | Shows emails OR suggests Gmail setup |

### 9. Notion Connectivity

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| NOTION-001 | notion_connectivity | "Test task for Notion sync check" | Task synced | Created in Notion, NOT "offline" or "queued locally" |

### 10. Edge Cases

| ID | Test Name | Message | Expected Response | Pass Criteria |
|----|-----------|---------|-------------------|---------------|
| EDGE-001 | empty_after_command | "/help extra text here" | Help response | Help shown despite extra text |
| EDGE-002 | unicode_message | "Meet café owner José tomorrow 🎉" | Unicode handled | Names/emojis preserved |
| EDGE-003 | long_message | "(long 200+ char message)" | Handled without truncation | Full message processed |
| EDGE-004 | special_characters | "Fix bug #123 in app v2.0 (critical)" | Special chars handled | #, parentheses don't break parsing |

---

## Dependencies

| Dependency | Required For | How to Verify |
|------------|--------------|---------------|
| Notion | Task creation, status, debrief | Task creates without "offline" message |
| Google Calendar | /today command, calendar events | Events shown or "nothing scheduled" |
| Gmail | Email queries | Shows emails or suggests setup |
| OpenAI Whisper | Voice messages | (Not tested in this plan) |

---

## Running Tests

```bash
# Run all tests
python scripts/comprehensive_bot_test.py

# Run specific test
python scripts/comprehensive_bot_test.py --test TASK-001

# Run category
python scripts/comprehensive_bot_test.py --category commands

# List all tests
python scripts/comprehensive_bot_test.py --list

# Stop on first failure
python scripts/comprehensive_bot_test.py --stop-on-fail
```

---

## Test Results Log

*Results will be logged to `/tmp/bot_test_results/test_report.json`*

### Latest Run

| Date | Total | Passed | Failed | Notes |
|------|-------|--------|--------|-------|
| (pending) | 30 | - | - | Initial run |

---

## Known Issues

*Issues discovered during testing will be logged here:*

| Issue ID | Test | Description | Status |
|----------|------|-------------|--------|
| - | - | - | - |

---

## Change Log

- 2024-01-14: Initial test plan created with 30 test cases
