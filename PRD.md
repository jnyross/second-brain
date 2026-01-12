# PRD.md — Product Requirements Document (Project-Specific)

**PRD version:** 0.6.1
**Status:** Draft
**Last updated:** 2026-01-12
**Completion promise (must match Prompt.md):** `<promise>COMPLETE</promise>`

> Rule: if a requirement cannot be verified by an automated test/check with an indisputable pass/fail result, rewrite it until it can.

---

## 0. One-paragraph brief

**Project name:** Second Brain - Personal AI Assistant

**Problem statement:** Human brains are designed for thinking, not storage. Forcing your brain to remember every task, idea, commitment, and piece of context creates a "cognitive tax" that causes anxiety and missed opportunities. Current tools (calendars, task managers, notes) require manual organization and don't learn your patterns, preferences, or relationships.

**Desired end state (outcome):** A trusted AI assistant that captures thoughts instantly (voice or text via Telegram), organizes them automatically into a knowledge graph (stored in Notion), learns your preferences/people/patterns over time, and increasingly acts autonomously on low-risk tasks (calendar invites, research). The system provides daily briefings (morning outlook, on-demand review) and builds a persistent knowledge base that becomes more valuable as AI models improve.

**Core philosophy:** 
- Capture must be frictionless (5 seconds max)
- System never blocks on user response
- Everything is logged and auditable
- Corrections improve future behavior
- Low-risk autonomy today, full autonomy when models are ready

---

## 1. Tech Stack & Deployment

### 1.1 Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Language** | Python 3.12 | Async I/O, quick iteration, good date parsing, mature ecosystem |
| **Telegram** | aiogram 3.x | Async-first, well-maintained, good typing |
| **Notion** | Direct REST via httpx | Minimal dependencies, clearer control |
| **Voice** | OpenAI Whisper API | Best accuracy, simple API |
| **Calendar** | Google Calendar API | Standard, well-documented |
| **Email** | Gmail API | Same OAuth as Calendar |
| **Browser** | Playwright | Reliable automation, good Python support |
| **Scheduling** | systemd timer | Reliable 7am delivery even if bot crashes |

### 1.2 Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         VPS (Ubuntu)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  systemd service: second-brain.service                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Docker Container                                           │ │
│  │  ┌────────────────────────────────────────────────────────┐│ │
│  │  │  Python 3.12                                           ││ │
│  │  │  • Telegram long-polling (aiogram)                     ││ │
│  │  │  • Message handlers                                    ││ │
│  │  │  • Notion client                                       ││ │
│  │  │  • Google OAuth client                                 ││ │
│  │  └────────────────────────────────────────────────────────┘│ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  systemd timer: second-brain-briefing.timer                     │
│  └─► Runs at 07:00 local time                                   │
│      └─► docker exec second-brain python -m assistant briefing  │
│                                                                  │
│  /etc/second-brain.env (chmod 600)                              │
│  └─► TELEGRAM_BOT_TOKEN, NOTION_API_KEY, etc.                   │
│                                                                  │
│  /var/lib/second-brain/                                         │
│  └─► tokens/ (OAuth refresh tokens, encrypted)                  │
│  └─► cache/ (optional local cache)                              │
│  └─► logs/ (application logs)                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Why this architecture:**
- **Long-polling** avoids TLS/domain/webhook complexity for personal use
- **systemd timer** guarantees 7am briefing even if main process is down
- **Docker** provides isolation and reproducibility
- **Restart=always** ensures auto-recovery from crashes

### 1.3 Secrets Management

| Secret | Storage | Rotation |
|--------|---------|----------|
| Telegram Bot Token | Environment file | Manual (rare) |
| Notion API Key | Environment file | Manual (rare) |
| OpenAI API Key | Environment file | Manual |
| Google OAuth Client ID/Secret | Environment file | Manual (rare) |
| Google OAuth Refresh Token | Encrypted file in /var/lib | Auto-refresh |

**Security rules:**
- Never log secrets
- Never store secrets in Notion
- Environment file permissions: 600 (owner read/write only)
- Refresh tokens encrypted at rest with machine key
- Development uses `.env` (gitignored); production uses systemd EnvironmentFile

### 1.4 Cost Estimate (Monthly)

| Service | Expected Usage | Cost |
|---------|---------------|------|
| Whisper | ~200 min/mo (20 voice notes/day × 20s) | $1.20 |
| Notion | Within free tier | $0 |
| Google Calendar/Gmail | Within free tier | $0 |
| Telegram | Free | $0 |
| VPS (small) | 1 vCPU, 1GB RAM | $5-10 |
| **Total** | | **~$7-12/mo** |

---

## 2. System Architecture

### 2.1 High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SECOND BRAIN                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUTS                           KNOWLEDGE LAYER (Notion)                   │
│  ──────                           ────────────────────────                   │
│  ┌────────────┐                  ┌─────────────────────────────────────────┐│
│  │  Telegram  │                  │  📥 Inbox (raw captures)                ││
│  │  (text)    │───┐              │  ✅ Tasks (actions to take)             ││
│  └────────────┘   │              │  👤 People (relationships, prefs)       ││
│  ┌────────────┐   │              │  📁 Projects (grouped work)             ││
│  │  Telegram  │───┼──────────►   │  📍 Places (locations, venues)          ││
│  │  (voice)   │   │              │  🧠 Preferences (your settings)         ││
│  └────────────┘   │              │  📖 Patterns (learned behaviors)        ││
│  ┌────────────┐   │              │  📜 Log (full audit trail)              ││
│  │  On-demand │───┘              └─────────────────────────────────────────┘│
│  │  debrief   │                                    │                         │
│  └────────────┘                                    ▼                         │
│                                  ┌─────────────────────────────────────────┐│
│  OUTPUTS                         │         REASONING ENGINE                 ││
│  ───────                         │  • Parse intent from input               ││
│  ┌────────────┐                  │  • Extract entities (people, dates)     ││
│  │  Telegram  │◄─────────────────│  • Confidence scoring (clear/unclear)   ││
│  │  response  │                  │  • Decide: act / ask / flag for review  ││
│  └────────────┘                  │  • Learn from corrections               ││
│  ┌────────────┐                  └─────────────────────────────────────────┘│
│  │  Morning   │                                    │                         │
│  │  briefing  │◄───────────────────────────────────┤                         │
│  │  (7am)     │                                    │                         │
│  └────────────┘                                    ▼                         │
│  ┌────────────┐                  ┌─────────────────────────────────────────┐│
│  │  Google    │◄─────────────────│            ACTIONS                       ││
│  │  Calendar  │                  │  • Create/update tasks                   ││
│  └────────────┘                  │  • Calendar invites (Google)             ││
│  ┌────────────┐                  │  • Web research (Playwright)             ││
│  │  Gmail     │◄─────────────────│  • Future: email, purchases              ││
│  │  (future)  │                  └─────────────────────────────────────────┘│
│  └────────────┘                                                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 The 8 Components (Second Brain Framework)

| # | Component | Name | Implementation | Purpose |
|---|-----------|------|----------------|---------|
| 1 | **Dropbox** | Capture Point | Telegram Bot | Frictionless input (text + voice) |
| 2 | **Sorter** | Classifier | AI + Notion API | Auto-categorize into correct database |
| 3 | **Form** | Schema | Notion Databases | Consistent structure for each entity type |
| 4 | **Filing Cabinet** | Memory Store | Notion Workspace | Persistent, queryable knowledge graph |
| 5 | **Receipt** | Audit Trail | Notion Log DB | Every action recorded with timestamp |
| 6 | **Bouncer** | Confidence Filter | AI Scoring | Hold unclear items for human review |
| 7 | **Tap on Shoulder** | Proactive Surfacing | Morning Brief + Debrief | Push relevant info at right time |
| 8 | **Fix Button** | Correction Mechanism | "Wrong" reply + Notion edit | Simple error correction that improves AI |

### 2.3 Data Flow

```
User sends message (Telegram)
         │
         ▼
┌─────────────────────────────────┐
│ If voice: Whisper transcription │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ AI parses intent + entities     │
│ • What type? (task/idea/person) │
│ • Who mentioned? (link People)  │
│ • When? (extract dates)         │
│ • Confidence score (0-100%)     │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ Confidence check                │
│ • >= 80%: Act + log             │
│ • < 80%: Flag for review        │
└─────────────────────────────────┘
         │
         ├──► High confidence: Execute action
         │    • Create task in Notion
         │    • Create calendar invite
         │    • Store new person/preference
         │    • Log action taken
         │
         └──► Low confidence: Flag
              • Add to Inbox with "needs_clarification"
              • Include in next debrief
         │
         ▼
┌─────────────────────────────────┐
│ Always respond (never blocks)   │
│ • "Got it. Created task X"      │
│ • "Added to inbox - will        │
│    clarify in our next review"  │
└─────────────────────────────────┘
```

---

## 3. Knowledge Graph (Notion Structure)

### 3.1 Database Schema

#### 📥 Inbox
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| raw_input | Text | Exact user input (text or transcription) |
| source | Select | telegram_text / telegram_voice / manual |
| timestamp | DateTime | When received |
| processed | Checkbox | Has been sorted |
| confidence | Number | AI confidence in understanding (0-100) |
| needs_clarification | Checkbox | Flagged for human review |
| interpretation | Text | What AI thinks it means |
| telegram_chat_id | Text | Telegram chat ID (for replies) |
| telegram_message_id | Text | Telegram message ID (idempotency key) |
| voice_file_id | Text | Telegram voice file ID (if voice) |
| transcript_confidence | Number | Whisper confidence (0-100) |
| language | Text | Detected language |
| processing_error | Text | Error message if processing failed |
| retry_count | Number | Number of processing retries |
| dedupe_key | Text | Hash of raw_input + chat_id + timestamp for deduplication |

#### ✅ Tasks
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier (T-XXX format) |
| title | Title | Task description |
| status | Select | inbox / todo / doing / done / cancelled / deleted |
| priority | Select | urgent / high / medium / low / someday |
| due_date | DateTime | When due (optional) |
| due_timezone | Text | Timezone for due_date interpretation |
| people | Relation → People | Who is this about/with (supports multiple) |
| project | Relation → Projects | Which project (optional) |
| source | Select | telegram / voice / manual / ai_created / email |
| source_inbox_item | Relation → Inbox | Original inbox item that created this |
| confidence | Number | AI confidence when created |
| created_by | Select | user / ai | Who created this |
| created_at | DateTime | When created |
| last_modified_at | DateTime | Last modification time |
| completed_at | DateTime | When completed |
| deleted_at | DateTime | Soft delete timestamp (null = not deleted) |
| calendar_event_id | Text | Google Calendar event ID if linked |
| estimated_duration | Number | Estimated minutes to complete |
| tags | MultiSelect | User-defined tags |
| notes | Text | Additional context |

#### 👤 People
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| name | Title | Person's name |
| aliases | Text | Alternative names, nicknames (comma-separated) |
| unique_key | Text | Normalized identifier for deduplication (e.g., lowercase email) |
| relationship | Select | partner / family / friend / colleague / acquaintance |
| company | Text | Where they work (if relevant) |
| email | Email | Primary email address |
| phone | Phone | Primary phone number |
| telegram_handle | Text | Telegram username if known |
| preferences | Text | What they like/dislike |
| quirks | Text | Things to remember |
| communication_style | Text | How to communicate with them |
| last_contact | DateTime | Last interaction |
| tasks | Relation → Tasks | Related tasks |
| archived | Checkbox | Hidden from active lists |
| deleted_at | DateTime | Soft delete timestamp |
| notes | Text | Anything else |

#### 📁 Projects
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| name | Title | Project name |
| status | Select | active / paused / completed / cancelled |
| type | Select | work / personal |
| people | Relation → People | Who's involved |
| deadline | DateTime | When due |
| next_action | Text | Very next step |
| context | Text | Background info, decisions made |
| tasks | Relation → Tasks | Related tasks |

#### 📍 Places
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| name | Title | Place name |
| type | Select | restaurant / cinema / office / home / venue / other |
| address | Text | Physical address |
| your_preference | Text | "My usual X" or notes |
| last_visit | DateTime | Last time you went |
| rating | Number | Your rating (1-5) |
| notes | Text | Anything to remember |

#### 🧠 Preferences
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| category | Select | meetings / food / travel / communication / schedule / other |
| preference | Title | The preference itself |
| details | Text | More context |
| learned_from | Text | Which interaction taught this |
| learned_at | DateTime | When learned |
| confidence | Number | How certain (increases with confirmation) |
| times_applied | Number | How often used |

#### 📖 Patterns
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| trigger | Title | What input triggers this (e.g., "Friday night") |
| meaning | Text | What it usually means (e.g., "plans with Jess") |
| confidence | Number | How certain (0-100) |
| times_confirmed | Number | How often this held true |
| times_wrong | Number | How often corrected |
| last_used | DateTime | Last time applied |
| created_at | DateTime | When first learned |

#### 📧 Emails (Cached/Tracked)
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| gmail_id | Text | Gmail message ID |
| thread_id | Text | Gmail thread ID |
| from | Relation → People | Sender (linked) |
| subject | Title | Email subject |
| snippet | Text | Preview text |
| received_at | DateTime | When received |
| is_read | Checkbox | Read status |
| needs_response | Checkbox | AI detected action needed |
| priority | Select | high / normal / low |
| extracted_tasks | Relation → Tasks | Tasks created from this email |
| response_draft | Text | Draft response if created |
| response_sent | Checkbox | Whether we replied |
| response_sent_at | DateTime | When replied |

#### 📜 Log (Audit Trail)
| Field | Type | Purpose |
|-------|------|---------|
| id | UUID | Unique identifier |
| request_id | Text | Unique ID for this request (for correlation) |
| idempotency_key | Text | Key for deduplication (telegram_message_id, etc.) |
| timestamp | DateTime | When action occurred |
| action_type | Select | capture / classify / create / update / delete / send / research / email_read / email_send / calendar_create / calendar_update / error / retry |
| input | Text | What triggered this (redacted if sensitive) |
| interpretation | Text | How AI understood it |
| action_taken | Text | What was done |
| confidence | Number | AI confidence |
| entities_affected | Text | Which records changed (Notion page IDs) |
| external_api | Text | Which external API was called (notion / google / telegram / whisper) |
| external_resource_id | Text | ID in external system (event ID, message ID, etc.) |
| error_code | Text | Error code if failed |
| error_message | Text | Error details if failed |
| retry_count | Number | Number of retries attempted |
| correction | Text | If corrected, what was wrong |
| corrected_at | DateTime | When corrected |
| undo_available_until | DateTime | When undo window expires |
| undone | Checkbox | Whether this action was undone |

---

## 4. Integration Specifications

### 4.1 Telegram Bot

**Purpose:** Primary input channel for capture

**Capabilities:**
- Receive text messages
- Receive voice messages (audio files)
- Send text responses
- Send morning briefings
- Handle commands (/debrief, /status, /help)

**Behavior:**
- Every message gets a response (never silent)
- Voice messages transcribed via Whisper before processing
- Responses are brief and actionable
- Never asks follow-up questions that block on response
- Unclear items flagged for debrief, not immediate clarification

**Commands:**
| Command | Action |
|---------|--------|
| /debrief | Start interactive review session |
| /status | Show pending tasks and flagged items |
| /today | Show today's schedule and tasks |
| /help | Show available commands |

### 4.2 Whisper API (Voice Transcription)

**Purpose:** Convert voice memos to text

**Configuration:**
- Model: whisper-1
- Response format: text
- Language: auto-detect (primarily English)

**Behavior:**
- Transcription happens immediately on voice message receipt
- Original audio stored in Notion (or reference)
- Both transcription and audio preserved for audit

### 4.3 Notion API

**Purpose:** Persistent knowledge storage

**Operations:**
- Create pages in any database
- Update existing pages
- Query databases with filters
- Create relations between pages

**Sync Strategy:**
- All writes go to Notion immediately
- Notion is source of truth
- Local cache for performance (optional, later)

### 4.4 Google Calendar API

**Purpose:** Create and read calendar events

**Capabilities:**
- Create events with title, time, attendees
- Read upcoming events for briefings
- Check availability for scheduling

**Behavior:**
- Calendar invites created autonomously (low-risk action)
- All created events logged
- Corrections handled: "wrong" removes/modifies event

### 4.5 Gmail API

**Purpose:** Read emails for context, send emails on your behalf

**Capabilities:**

*Read (Low-risk, autonomous):*
- Fetch recent emails for morning briefing
- Search emails by sender, subject, date
- Extract action items from emails
- Identify emails needing response
- Link email threads to People and Projects

*Write (Medium-risk, tiered autonomy):*
- Draft emails for review
- Send emails with confirmation
- Reply to threads (with learned patterns)
- Forward emails

**Behavior:**

*Reading:*
- Morning briefing includes "Emails needing attention" section
- Extracts tasks like "John asked you to send the report"
- Links senders to People database automatically
- Flags high-priority senders (learned over time)

*Sending (Autonomy Levels):*

| Level | Trigger | Action |
|-------|---------|--------|
| Draft only | Default | Creates draft, notifies you "Draft ready: Re: Project X" |
| Send with confirmation | You say "email Mike about X" | Drafts, shows preview, waits for "send it" |
| Auto-send simple | Pattern established (3+ similar sent) | Sends, logs, shows in debrief |
| Auto-send complex | Future (high confidence + pattern) | Full autonomy with audit |

**Email Intelligence:**
- Learns your writing style from sent folder
- Knows who you reply to quickly vs slowly
- Understands thread context
- Detects urgency from sender patterns

**Example Interactions:**

```
Morning Briefing:
📧 EMAIL (5 need attention)
• Mike (Project X) - "Can you send the Q4 numbers?" - 2 hours ago
• Sarah (urgent) - "Client meeting moved to Thursday" - 5 hours ago  
• Newsletter from TechCrunch - skipped (low priority pattern)

User: "Reply to Mike, say I'll send them today"

AI: "Draft created:
'Hi Mike, I'll send the Q4 numbers over today. John'

Send it? Or edit?"

User: "Send it"

AI: "Sent. Logged."
```

```
User: "What did Sarah say about the client meeting?"

AI: "Sarah emailed 5 hours ago: 'The client meeting has been moved 
from Tuesday to Thursday at 2pm. Same location. Can you update 
the deck with the new projections?'

Want me to:
1. Update your calendar (Tuesday → Thursday)
2. Create task: Update deck with new projections
3. Both?"
```

**Security:**
- OAuth scopes: gmail.readonly + gmail.send + gmail.compose
- No access to delete emails
- All sent emails logged in audit trail
- Drafts visible in Gmail drafts folder

### 4.6 Google Maps API

**Purpose:** Enrich places with structured data, provide travel context, validate locations

**Capabilities:**

*Place Enrichment:*
- Validate extracted place names (fuzzy "SF" → "San Francisco, CA")
- Geocode places to coordinates (lat/lng)
- Get place details (address, phone, hours, type)
- Resolve ambiguous places ("that coffee shop" → recent places near you)

*Travel Intelligence:*
- Calculate travel time between locations (with real-time traffic)
- Estimate arrival times for tasks with places
- Morning briefing: "Meeting in Palo Alto at 2pm - leave by 1:15pm (45 min with traffic)"
- Detect unrealistic schedules: "You have meetings in SF at 10am and LA at 11am"

*Proximity Features:*
- "What tasks can I do near here?" (location-aware task suggestions)
- Group errands by area: "You have 3 tasks in downtown"
- Trigger reminders by location (future): "You're near the hardware store - buy lightbulbs?"

**Behavior:**

| Trigger | Action |
|---------|--------|
| Place extracted from message | Geocode and enrich, store in Places DB |
| Task has place + time | Calculate travel time from home/previous location |
| Morning briefing | Include travel estimates for today's location-based tasks |
| User asks "how far is X" | Real-time distance/duration |

**Example Interactions:**

```
User: "Meet Dave at Blue Bottle Coffee tomorrow at 3pm"

AI: "✅ Task: Meet Dave at Blue Bottle Coffee
📍 Blue Bottle Coffee, 315 Linden St, San Francisco, CA 94102
📅 Tomorrow 3:00 PM
🚗 25 min from home (with typical traffic)

Saved to Notion"
```

```
Morning Briefing:
🗓️ TODAY'S SCHEDULE
• 10:00 AM - Dentist appointment (Dr. Smith, 123 Main St)
  └─ Leave by 9:40 AM (20 min drive)
• 2:00 PM - Meet Sarah at Ferry Building
  └─ Leave by 1:30 PM (25 min from dentist)
• 5:00 PM - Pick up dry cleaning (on your way home)
```

**Places Database Integration:**

When a place is mentioned:
1. Search existing Places DB for match (by name, address, or coordinates)
2. If found: link to existing record
3. If new: create Places record with Maps API data
4. Store: name, address, lat/lng, place_id, category, notes

**API Usage:**

| API | Purpose | Cost |
|-----|---------|------|
| Geocoding API | Address → coordinates | $5/1000 requests |
| Places API | Place details, search | $17/1000 requests |
| Distance Matrix API | Travel times | $5/1000 elements |
| Directions API | Route details | $5/1000 requests |

**Security:**
- API key restricted to specific APIs (not all Google services)
- Key restricted by IP/referrer where possible
- No user location tracking without explicit consent
- All place queries logged

### 4.7 Google Drive API

**Purpose:** Workspace for longer-form content, research storage, project documentation

**Capabilities:**

*Document Creation:*
- Create Google Docs for research reports, meeting notes, project plans
- Create Sheets for data analysis, tracking, comparisons
- Create Slides for presentations (future)
- Organize into project folders automatically

*Research Storage:*
- Save web research to Drive (summarized articles, scraped data)
- Store AI-generated reports and analyses
- Keep drafts and iterations for review
- Link Drive files to Notion Projects/Tasks

*Collaboration Ready:*
- Documents can be shared with others
- Real-time collaboration on AI-generated drafts
- Export to PDF, Word, etc.

**Folder Structure:**

```
Second Brain/
├── Research/
│   ├── {Project Name}/
│   │   ├── Research Notes - {Topic}.gdoc
│   │   └── Data Analysis.gsheet
│   └── General/
├── Meeting Notes/
│   └── {Date} - {Meeting Title}.gdoc
├── Reports/
│   └── {Report Name} - {Date}.gdoc
└── Drafts/
    └── Email Draft - {Subject}.gdoc
```

**Behavior:**

| Trigger | Action |
|---------|--------|
| User: "Research X and write a report" | Create Doc in Research/{Project}/, populate with findings |
| User: "Take notes for my meeting with Y" | Create Doc in Meeting Notes/, link to People |
| User: "Compare options for Z" | Create Sheet with comparison matrix |
| User: "Draft a proposal for X" | Create Doc in Drafts/, iterate with feedback |
| Task completed with research | Attach Drive link to Notion task |

**Example Interactions:**

```
User: "Research the best CRM options for a small business and create a comparison"

AI: "I'll research CRM options and create a comparison document.

🔍 Researching: HubSpot, Salesforce, Pipedrive, Zoho, Freshsales...

📄 Created: 'CRM Comparison - Small Business.gsheet'
📁 Location: Second Brain/Research/General/

Summary:
| CRM | Price | Best For |
|-----|-------|----------|
| HubSpot | Free-$50/mo | Startups, marketing focus |
| Pipedrive | $15/mo | Sales teams |
| Zoho | $14/mo | Budget-conscious |

Full comparison with 12 criteria in the sheet. Want me to add anything?"
```

```
User: "Write up the meeting notes from my call with Sarah about Project X"

AI: "I'll create meeting notes. What were the key points discussed?

Or I can check:
- Recent tasks mentioning Sarah + Project X
- Emails from Sarah today
- Your calendar event details

Want me to draft from context, or will you dictate the notes?"
```

**Integration with Notion:**

| Notion Entity | Drive Integration |
|---------------|-------------------|
| Project | Folder in Research/{Project Name}/ |
| Task | drive_file_id field links to relevant doc |
| People | Meeting notes reference people involved |
| Inbox | Research items can spawn Drive docs |

**Document Types:**

| Type | Format | Use Case |
|------|--------|----------|
| Research Report | Google Doc | In-depth analysis, citations, narrative |
| Comparison Matrix | Google Sheet | Feature comparisons, pros/cons, scoring |
| Meeting Notes | Google Doc | Structured notes, action items, attendees |
| Data Export | Google Sheet | Notion data exports, tracking over time |
| Draft Content | Google Doc | Emails, proposals, documents for review |

**Autonomy Levels:**

| Action | Autonomy | Confirmation |
|--------|----------|--------------|
| Create Doc (private) | Full | No - just notify |
| Create in shared folder | Medium | Yes - "Create in Team folder?" |
| Share with others | Low | Yes - show sharing preview |
| Delete document | Low | Yes - confirm deletion |

**Security:**
- OAuth scopes: drive.file (only files created by app)
- Cannot access existing Drive files unless explicitly shared
- All file operations logged
- No permanent deletion (trash first, then permanent after 30 days)

### 4.8 Failure Handling

**Design principle:** The system must NEVER silently fail. User always gets feedback.

#### Notion Unavailable
| Scenario | Behavior |
|----------|----------|
| Notion API returns 5xx | Retry 3x with exponential backoff (1s, 2s, 4s) |
| Notion API returns 429 | Respect Retry-After header, queue request |
| Notion down > 30s | Reply to user: "Saved locally, will sync when Notion is back" |
| | Write to local queue file: `~/.second-brain/queue/pending.jsonl` |
| Notion recovers | Process queue in order, dedupe by idempotency_key |

#### Telegram Unavailable
| Scenario | Behavior |
|----------|----------|
| Send fails | Retry 3x with backoff |
| Send fails after retries | Log error, continue processing |
| Long-polling disconnects | Auto-reconnect (aiogram handles this) |

#### Whisper Unavailable
| Scenario | Behavior |
|----------|----------|
| Whisper API error | Reply: "Couldn't transcribe voice message. Try sending as text?" |
| | Store voice file reference, mark needs_clarification |
| Low confidence transcript | Store both audio ref and transcript |
| | Add to Inbox with transcript_confidence field |
| | Include in debrief: "I heard '[transcript]' - is that right?" |

#### Google Calendar Unavailable
| Scenario | Behavior |
|----------|----------|
| API error | Retry 3x with backoff |
| After retries | Create task in Notion with note: "Calendar sync pending" |
| | Queue calendar action for retry |
| Token expired | Refresh using stored refresh_token |
| Refresh fails | Reply: "Need to re-authenticate Google. Run /setup_google" |

#### Rate Limiting Strategy
| API | Limit | Strategy |
|-----|-------|----------|
| Notion | ~3 req/s | Token bucket, queue excess |
| Telegram | 30 msg/s (to same chat) | Unlikely to hit for personal use |
| Whisper | Based on tier | Queue if limited |
| Google | 1M queries/day | No concern for personal use |

### 4.9 Idempotency

**Problem:** Network retries can cause duplicate actions.

**Solution:** Every action has an idempotency key stored in Log.

| Action | Idempotency Key |
|--------|-----------------|
| Process Telegram message | `telegram:{chat_id}:{message_id}` |
| Create calendar event | `calendar:{task_notion_id}:{date}` |
| Send email | `email:{thread_id}:{response_hash}` |
| Morning briefing | `briefing:{date}:{chat_id}` |

**Deduplication process:**
1. Before action, check Log for existing idempotency_key
2. If found and not error, skip action
3. If found with error, may retry based on error type
4. If not found, proceed and log with key

### 4.10 Playwright (Web Research)

**Purpose:** Research tasks that require web browsing

**Capabilities:**
- Navigate to websites
- Extract information
- Take screenshots for evidence

**Example Uses:**
- Check cinema showtimes
- Look up restaurant menus
- Research products
- Verify business hours

**Behavior:**
- All research logged with sources
- Screenshots stored as evidence
- Results summarized and stored in relevant task/note

---

## 5. Interaction Patterns

### 5.1 Capture Flow

**User sends text:**
```
User: "Cinema with Jess Friday 8pm everyman"

AI Processing:
- Type: Task
- Title: "Cinema with Jess"
- Due: Friday 8pm
- Person: Jess (lookup or create)
- Place: Everyman (lookup or create)
- Confidence: 95%

AI Response:
"Got it. Cinema with Jess, Friday 8pm at Everyman. Want me to check what's showing?"

Actions taken:
- Task created in Notion
- Linked to Jess (People)
- Linked to Everyman (Places)
- Logged in audit trail
```

**User sends unclear voice memo:**
```
User: [voice memo] "uhh that thing... need to do that thing for the project, you know the one Mike mentioned..."

Transcription: "uhh that thing need to do that thing for the project you know the one Mike mentioned"

AI Processing:
- Type: Unclear
- Possible: Task related to a project involving Mike
- Confidence: 35%

AI Response:
"Got it, something about Mike's project. I've added this to your inbox - we'll clarify in your next review."

Actions taken:
- Added to Inbox with needs_clarification=true
- Linked tentatively to Mike (People) if exists
- Logged with low confidence
```

### 5.2 Morning Briefing (7am)

```
Good morning! Here's your day:

📅 TODAY
• 9:00 - Standup with Mike
• 14:00 - Dentist appointment
• 20:00 - Cinema with Jess (Everyman)

📧 EMAIL (3 need attention)
• Mike - "Q4 numbers?" - needs response
• Sarah (urgent) - "Client meeting moved" - has action item
• Boss - "Friday all-hands" - FYI

✅ DUE TODAY
• Review proposal for Project X
• Call mom back

⚠️ NEEDS CLARIFICATION (2 items)
• "that thing for Mike's project" - what specifically?
• "remember to check the thing" - which thing?

📊 THIS WEEK
• Friday: Jess's birthday
• 3 tasks due by Thursday

Reply /debrief anytime to review together.
```

### 5.3 On-Demand Debrief

**User invokes:** /debrief

```
AI: Let's review. I have 2 items that need clarification:

1. Yesterday you said "that thing for Mike's project" - what did you mean?

User: Oh, I need to send him the Q4 numbers

AI: Got it. Created task: "Send Mike Q4 numbers" linked to Project X. When is it due?

User: Tomorrow

AI: Set for tomorrow. Next item:

2. "Remember to check the thing" - what thing?

User: Cancel that, I already did it

AI: Removed from inbox.

Review complete. 
• 1 task created
• 1 item cancelled
• You have 5 tasks for this week

Anything else?
```

### 5.4 Timezone Handling

**Source of truth:** User-configured timezone stored in Preferences database.

| Input | Interpretation |
|-------|----------------|
| "tomorrow 2pm" | 2pm in user's configured timezone |
| "Friday 8pm" | 8pm in user's timezone on next Friday |
| "in 2 hours" | Current time + 2 hours |
| "9am EST" | Explicit timezone respected |

**Configuration:**
- On first use, ask user for timezone (or detect from Telegram if possible)
- Store in Preferences: `category=schedule, preference=timezone, details=America/Los_Angeles`
- 7am briefing uses this timezone
- All due_dates stored in ISO 8601 with timezone

### 5.5 Disambiguation

**Problem:** User says "Sarah" but there are multiple Sarahs.

**Immediate behavior (high confidence):**
- If one Sarah has `relationship=partner/family`, assume that one
- If one Sarah was mentioned in last 7 days, assume that one
- If confidence > 80%, proceed and log assumption

**Low confidence behavior:**
- Create task/item linked to most likely Sarah
- Add to debrief: "I assumed you meant Sarah Chen. Correct?"
- On correction, update task and boost confidence for next time

**Pattern learning:**
- Track which Sarah is selected in which context
- Store pattern: `trigger="work meeting Sarah", meaning="Sarah Jones (colleague)"`
- Apply pattern automatically after 3 confirmations

### 5.6 Deletion Semantics

**Soft delete (default):**
- Set `deleted_at` timestamp
- Record hidden from normal queries
- Recoverable via Notion or "undo"
- Cleaned up after 30 days

**Hard delete:**
- Requires explicit confirmation
- Used for: PII removal, duplicate cleanup
- Logged but not recoverable

**User commands:**
- "delete that" → soft delete last created item
- "remove [item]" → soft delete
- "permanently delete" → hard delete with confirmation
- Edit in Notion → immediate effect, logged

### 5.7 Corrections

**Immediate correction:**
```
AI: Got it. Created task: "Call Jess" for tomorrow.

User: Wrong, I said Tess not Jess

AI: Fixed. Changed to "Call Tess". I've noted Tess as a new contact - who is Tess?

User: Colleague from marketing

AI: Added Tess to People (colleague, marketing).
```

**Pattern correction:**
```
User: You keep setting shopping tasks as high priority, they should be low

AI: Got it. I've updated my pattern: shopping-related tasks will now default to low priority. I'll update the 3 existing shopping tasks too.

Pattern stored:
- trigger: "shopping" / "buy" / "groceries"
- correction: priority = low
- confidence: 80% (will increase with confirmation)
```

---

## 6. Autonomy Levels

### 6.1 Current (Phase 1): Low-Risk Autonomy

Actions the AI can take without confirmation:

| Action | Risk Level | Reversible | Audit |
|--------|------------|------------|-------|
| Create task in Notion | Low | Yes | Logged |
| Create calendar event | Low | Yes | Logged |
| Add person to People | Low | Yes | Logged |
| Store preference | Low | Yes | Logged |
| Web research | Low | N/A | Logged with sources |
| Send morning briefing | Low | N/A | Logged |

All actions appear in daily debrief for review.

### 6.2 Undo & Rollback Semantics

| Action | Undo Window | Undo Method | Notification |
|--------|-------------|-------------|--------------|
| Task created | Unlimited | Set status=deleted | None |
| Calendar event (no attendees) | Unlimited | Delete event | None |
| Calendar event (with attendees) | 5 minutes | Delete event + notify | Attendees notified of cancellation |
| Person created | Unlimited | Set deleted_at | None |
| Email sent | Cannot undo | N/A | Log only |
| Research completed | N/A | Not reversible but harmless | None |

**Undo triggers:**
- User replies "wrong" or "undo" within window
- User edits/deletes in Notion directly
- User says "cancel that" or "delete that"

**Rollback process:**
1. Log entry created with `undone=true`
2. External resources cleaned up (calendar event deleted, etc.)
3. Notion records soft-deleted (deleted_at set)
4. User notified: "Undone. [details]"

### 6.3 Confirmation Requirements

| Action | Requires Confirmation |
|--------|----------------------|
| Create task | No |
| Create calendar event (self only) | No |
| Create calendar event (with attendees) | Yes - show preview first |
| Send email | Yes - show draft first |
| Delete task | No (soft delete, recoverable) |
| Delete person | No (soft delete, recoverable) |
| Hard delete anything | Yes |

### 6.4 Future (Phase 2): Medium-Risk Autonomy

Actions that require confirmation OR high confidence pattern:

| Action | Condition for Auto |
|--------|-------------------|
| Send email draft | User says "send it" or confidence > 95% from pattern |
| Book restaurant | Pattern established + confirmation last 3 times |
| Purchase < $50 | Explicit "buy it" or established pattern |
| Modify calendar | Unless confidence > 90% |

### 6.5 Future (Phase 3): Full Autonomy

When models are more capable:
- Email replies based on learned style
- Proactive scheduling optimization
- Purchase decisions within budget
- Travel booking
- Always-on listening mode

---

## 7. Loop Configuration

- **Mode:** Autonomous
- **Max iterations:** 100
- **Stuck thresholds:**
  - No-progress iterations: 5
  - Same-error repeats: 3
- **Daily cost limit:** $5.00 (configurable)

---

## 8. Acceptance Tests

### AT-101 — Telegram Text Capture
- **Given:** Telegram bot is running
- **When:** User sends "Buy milk tomorrow"
- **Then:** Task created in Notion Tasks database with title "Buy milk", due tomorrow
- **And:** Response sent to Telegram within 5 seconds
- **Pass condition:** Notion API query returns task AND Telegram message delivered

### AT-102 — Telegram Voice Capture
- **Given:** Telegram bot is running
- **When:** User sends voice memo "Call dentist to reschedule"
- **Then:** Voice transcribed via Whisper
- **And:** Task created in Notion with title "Call dentist to reschedule"
- **Pass condition:** Transcription logged AND task exists in Notion

### AT-103 — Low Confidence Flagging
- **Given:** User sends unclear message "do the thing"
- **When:** AI confidence < 80%
- **Then:** Item added to Inbox with needs_clarification=true
- **And:** Response indicates item flagged for review
- **Pass condition:** Inbox item exists with needs_clarification=true

### AT-104 — Person Extraction and Linking
- **Given:** User sends "Lunch with Sarah Friday"
- **When:** Sarah exists in People database
- **Then:** Task created and linked to Sarah via relation
- **Pass condition:** Task.person relation points to Sarah's page

### AT-105 — Person Creation
- **Given:** User sends "Meet Bob for coffee"
- **When:** Bob does not exist in People database
- **Then:** New person "Bob" created in People
- **And:** Task linked to new Bob entry
- **Pass condition:** People database contains Bob AND task linked

### AT-106 — Morning Briefing Delivery
- **Given:** System configured for 7am briefing
- **When:** Clock reaches 7:00am
- **Then:** Telegram message sent with today's calendar, due tasks, flagged items
- **Pass condition:** Telegram message sent between 7:00-7:05am with required sections

### AT-107 — On-Demand Debrief
- **Given:** User sends /debrief command
- **When:** There are items with needs_clarification=true
- **Then:** Interactive review session starts
- **And:** Each unclear item presented for clarification
- **Pass condition:** All needs_clarification items addressed or skipped

### AT-108 — Correction Handling
- **Given:** AI created task "Call Jess"
- **When:** User replies "Wrong, I said Tess"
- **Then:** Task updated to "Call Tess"
- **And:** Correction logged in Log database
- **Pass condition:** Task.title = "Call Tess" AND Log entry with correction field populated

### AT-109 — Pattern Learning
- **Given:** User corrects priority 3 times for similar tasks
- **When:** Pattern confidence > 70%
- **Then:** Pattern stored in Patterns database
- **And:** Future similar tasks use learned pattern
- **Pass condition:** Pattern exists AND new task uses pattern

### AT-110 — Google Calendar Creation
- **Given:** User sends "Meeting with Mike tomorrow 2pm"
- **When:** Google Calendar integration enabled
- **Then:** Calendar event created for tomorrow 2pm
- **And:** Task in Notion linked to calendar event
- **Pass condition:** Google Calendar API confirms event created

### AT-111 — Audit Trail Completeness
- **Given:** Any action taken by system
- **Then:** Log entry created with timestamp, action_type, input, action_taken
- **Pass condition:** Log database query returns entry for every action

### AT-112 — Web Research
- **Given:** User asks "What's showing at Everyman this Friday?"
- **When:** Playwright browser automation available
- **Then:** Research performed and results returned
- **And:** Sources logged
- **Pass condition:** Response includes movie titles AND Log entry includes URL visited

### AT-113 — Idempotency (Duplicate Message)
- **Given:** User sends "Buy milk tomorrow"
- **When:** Same message processed twice (network retry simulation)
- **Then:** Only one task created in Notion
- **And:** Second attempt logged as "deduplicated"
- **Pass condition:** Exactly 1 task exists AND Log shows 2 entries (1 create, 1 dedupe)

### AT-114 — Notion Offline Queue
- **Given:** Notion API returns 503
- **When:** User sends "Call dentist"
- **Then:** Response sent within 5 seconds: "Saved locally, will sync when Notion is back"
- **And:** Item written to local queue file
- **Pass condition:** Local queue contains item AND user received response

### AT-115 — Notion Recovery Sync
- **Given:** Local queue has 3 pending items
- **When:** Notion becomes available
- **Then:** All 3 items synced to Notion in order
- **And:** Local queue cleared
- **Pass condition:** Notion contains all 3 items AND queue is empty

### AT-116 — Calendar Undo Window
- **Given:** AI created calendar event "Meeting with Bob 2pm"
- **When:** User says "wrong" within 5 minutes
- **Then:** Calendar event deleted
- **And:** Task updated with note "Calendar event cancelled"
- **Pass condition:** Google Calendar event no longer exists

### AT-117 — Person Disambiguation
- **Given:** Two people named "Sarah" exist (Sarah Chen, Sarah Jones)
- **When:** User sends "Lunch with Sarah Friday"
- **Then:** Task created linked to most likely Sarah (based on recency/relationship)
- **And:** Flagged for confirmation in debrief
- **Pass condition:** Task exists with person relation AND needs_clarification context stored

### AT-118 — Soft Delete Recovery
- **Given:** Task "Buy groceries" exists
- **When:** User says "delete that"
- **Then:** Task.deleted_at set to current timestamp
- **And:** Task hidden from /today and briefings
- **When:** User says "undo" within 30 days
- **Then:** Task.deleted_at cleared, task visible again
- **Pass condition:** Task recoverable via undo

### AT-119 — Timezone Parsing
- **Given:** User timezone is "America/Los_Angeles" (PST/PDT)
- **When:** User sends "Call mom at 2pm tomorrow"
- **Then:** Task due_date is tomorrow 14:00 in America/Los_Angeles
- **And:** due_timezone field set to "America/Los_Angeles"
- **Pass condition:** ISO timestamp represents correct local time

### AT-120 — Whisper Low Confidence Handling
- **Given:** User sends voice memo with background noise
- **When:** Whisper returns transcript with low confidence
- **Then:** Inbox item created with needs_clarification=true
- **And:** transcript_confidence field populated
- **And:** Voice file reference stored
- **Pass condition:** Debrief includes "I heard '[transcript]' - is that right?"

### AT-121 — Place Enrichment via Maps API
- **Given:** User sends "Meet Dave at Blue Bottle Coffee tomorrow"
- **When:** Google Maps API enabled
- **Then:** Place geocoded and enriched with address, lat/lng
- **And:** Places database record created or linked
- **And:** Task notes include formatted address
- **Pass condition:** Places DB contains "Blue Bottle Coffee" with coordinates AND task linked

### AT-122 — Travel Time in Morning Briefing
- **Given:** User has task "Dentist at 2pm" with place "123 Main St"
- **When:** Morning briefing generated
- **Then:** Briefing includes travel estimate from home
- **Pass condition:** Briefing contains "Leave by X" with calculated departure time

### AT-123 — Unrealistic Schedule Detection
- **Given:** User has meeting in San Francisco at 10am
- **When:** User sends "Meeting in Los Angeles at 11am"
- **Then:** Warning shown: "Travel time ~6 hours - schedule conflict detected"
- **And:** Task created but flagged for review
- **Pass condition:** Task exists AND warning logged AND needs_clarification=true

### AT-124 — Drive Research Document Creation
- **Given:** User sends "Research best CRM options for small business"
- **When:** Google Drive API enabled
- **Then:** Google Doc created in Second Brain/Research/ folder
- **And:** Document populated with research findings
- **And:** Task created linking to Drive document
- **Pass condition:** Drive API confirms doc exists AND task.drive_file_id populated

### AT-125 — Drive Meeting Notes
- **Given:** User sends "Create meeting notes for call with Sarah"
- **When:** Google Drive API enabled
- **Then:** Google Doc created in Second Brain/Meeting Notes/ folder
- **And:** Document titled with date and meeting description
- **And:** Linked to Sarah in People database
- **Pass condition:** Drive doc exists AND task linked to Person "Sarah"

### AT-126 — Drive Comparison Sheet
- **Given:** User sends "Compare iPhone vs Android - create a sheet"
- **When:** Google Drive API enabled
- **Then:** Google Sheet created with comparison matrix
- **And:** Sheet has structured columns (criteria, option 1, option 2, notes)
- **Pass condition:** Drive API confirms Sheet exists with correct structure

### AT-127 — Proximity Task Suggestions
- **Given:** User has 3 tasks with places in downtown SF
- **When:** User asks "What can I do near Union Square?"
- **Then:** Response lists nearby tasks with distances
- **Pass condition:** Response includes all 3 tasks with distance estimates

### AT-128 — LLM Intent Parsing with Fallback
- **Given:** LLM API key configured for intent parsing
- **When:** User sends an ambiguous message ("need to sort plans with Alex next Friday")
- **Then:** LLM parser returns structured intent with extracted people, dates, and confidence
- **And:** If the LLM API is unavailable, the regex parser is used instead
- **Pass condition:** Parsed intent includes structured fields and fallback path is exercised on API failure

---

## 9. Task Backlog (Revised)

### Phase 0: Foundation (COMPLETE)
| Task ID | Status | Title |
|---------|--------|-------|
| T-000 | ✅ | Initialize loop state + runbook |
| T-001 | ✅ | Design knowledge base schema |
| T-002 | ✅ | Implement task data structure |
| T-003 | ✅ | Create conversation logging system |
| T-005 | ✅ | Implement no-progress stuck detection |
| T-006 | ✅ | Implement same-error stuck detection |
| T-007 | ✅ | Implement cost tracking |
| T-008 | ✅ | Implement sandbox enforcement |
| T-009 | ✅ | Implement learning database |
| T-010 | ✅ | Implement task execution engine |
| T-011 | ✅ | Implement knowledge base retrieval |
| T-012 | ✅ | Implement Claude Code CLI integration |
| T-013 | ✅ | Create bootstrap script |
| T-014 | ✅ | Create verify script |
| T-015 | ✅ | Create run script |
| T-016 | ✅ | Create smoke test script |

### Phase 1: Notion Knowledge Graph
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-050 | P0 | Create Notion workspace structure | — | Databases exist with correct schema |
| T-051 | P0 | Implement Notion API client | T-050 | CRUD operations work on all databases |
| T-052 | P0 | Create entity extraction service | T-051 | Extracts people, dates, places from text |
| T-053 | P0 | Implement confidence scoring | T-052 | Returns 0-100 score for interpretations |
| T-054 | P0 | Build classification router | T-053 | Routes to correct database based on type |

### Phase 2: Telegram Capture
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-060 | P0 | Create Telegram bot | — | Bot responds to /start |
| T-061 | P0 | Implement text message handler | T-060, T-054 | AT-101 |
| T-062 | P0 | Integrate Whisper transcription | T-060 | Voice → text works |
| T-063 | P0 | Implement voice message handler | T-061, T-062 | AT-102 |
| T-064 | P0 | Build response generator | T-061 | Always responds, never blocks |
| T-065 | P0 | Implement low-confidence flagging | T-053, T-064 | AT-103 |

### Phase 3: Entity Linking
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-070 | P0 | Implement People lookup/create | T-051, T-052 | AT-104, AT-105 |
| T-071 | P0 | Implement Places lookup/create | T-051, T-052 | Places linked correctly |
| T-072 | P0 | Implement Projects lookup | T-051, T-052 | Projects linked correctly |
| T-073 | P0 | Build relation linker | T-070, T-071, T-072 | All relations populated |

### Phase 4: Briefings
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-080 | P1 | Implement morning briefing generator | T-051 | Generates correct summary |
| T-081 | P1 | Create scheduled briefing sender | T-080, T-060 | AT-106 |
| T-082 | P1 | Implement /debrief command | T-060, T-065 | AT-107 |
| T-083 | P1 | Build interactive clarification flow | T-082 | Unclear items resolved |

### Phase 5: Learning & Corrections
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-090 | P1 | Implement correction handler | T-064 | AT-108 |
| T-091 | P1 | Build pattern detection | T-090 | Detects repeated corrections |
| T-092 | P1 | Implement pattern storage | T-091, T-051 | AT-109 |
| T-093 | P1 | Apply patterns to new inputs | T-092 | Patterns affect behavior |

### Phase 6: Actions
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-100 | P1 | Implement Google Calendar OAuth | — | Auth flow works |
| T-101 | P1 | Create calendar event creator | T-100 | AT-110 |
| T-102 | P1 | Implement calendar reading | T-100 | Events retrieved for briefing |
| T-103 | P1 | Integrate Playwright for research | — | AT-112 |
| T-104 | P1 | Build research result formatter | T-103 | Results stored and summarized |

### Phase 7: Audit & Polish
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-110 | P1 | Implement comprehensive audit logging | T-051 | AT-111 |
| T-111 | P1 | Build "Today I Learned" summary | T-092 | Learnings in daily brief |
| T-112 | P1 | Create /status command | T-060 | Shows pending items |
| T-113 | P1 | Create /today command | T-060, T-102 | Shows today's schedule |

### Phase 8: Google Maps Integration
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-150 | P1 | Set up Google Maps API client | — | API calls succeed |
| T-151 | P1 | Implement place geocoding | T-150 | Address → coordinates |
| T-152 | P1 | Implement place enrichment | T-151 | Full place details retrieved |
| T-153 | P1 | Integrate with Places database | T-152, T-071 | AT-121 |
| T-154 | P1 | Implement travel time calculator | T-150 | Distance Matrix API works |
| T-155 | P1 | Add travel times to morning briefing | T-154, T-080 | AT-122 |
| T-156 | P2 | Implement schedule conflict detection | T-154 | AT-123 |
| T-157 | P2 | Implement proximity task suggestions | T-151 | AT-127 |

### Phase 9: Google Drive Integration
| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-160 | P1 | Implement Google Drive OAuth | T-100 | Shares OAuth with Calendar |
| T-161 | P1 | Create folder structure manager | T-160 | Second Brain folders created |
| T-162 | P1 | Implement Google Docs creation | T-161 | Docs created in correct folder |
| T-163 | P1 | Implement Google Sheets creation | T-161 | Sheets created with structure |
| T-164 | P1 | Build research-to-doc pipeline | T-162, T-103 | AT-124 |
| T-165 | P1 | Implement meeting notes creator | T-162, T-070 | AT-125 |
| T-166 | P2 | Implement comparison sheet generator | T-163 | AT-126 |
| T-167 | P2 | Link Drive files to Notion tasks | T-162, T-051 | drive_file_id populated |

### Future Phases
| Task ID | Pri | Title | Notes |
|---------|-----|-------|-------|
| T-120 | P2 | Gmail read integration | Read-only first |
| T-121 | P2 | Gmail draft creation | With confirmation |
| T-122 | P2 | Gmail auto-reply | Pattern-based |
| T-130 | P2 | Proactive nudges | "Don't forget X" |
| T-131 | P2 | Always-on listening | When models ready |
| T-140 | P2 | WhatsApp integration | Alternative to Telegram |
| T-170 | P3 | Location-triggered reminders | "You're near X" |
| T-171 | P3 | Google Slides integration | Presentation creation |
| T-172 | P3 | Drive file sharing automation | With confirmation |

---

## 10. API Keys Required

| Service | Purpose | How to Get |
|---------|---------|------------|
| Telegram Bot Token | Capture channel | @BotFather on Telegram |
| Notion API Key | Knowledge storage | notion.so/my-integrations |
| OpenAI API Key | Whisper transcription | platform.openai.com |
| Google OAuth Client | Calendar, Gmail, Drive | console.cloud.google.com |
| Google Maps API Key | Place enrichment, travel times | console.cloud.google.com |

**Google OAuth Scopes Required:**
- `https://www.googleapis.com/auth/calendar` - Calendar read/write
- `https://www.googleapis.com/auth/gmail.readonly` - Read emails
- `https://www.googleapis.com/auth/gmail.send` - Send emails
- `https://www.googleapis.com/auth/gmail.compose` - Create drafts
- `https://www.googleapis.com/auth/drive.file` - Create/edit files created by app

**Google Maps APIs Required:**
- Geocoding API
- Places API
- Distance Matrix API
- Directions API (optional, for detailed routes)

---

## 11. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Capture latency | < 5 seconds | Time from message to response |
| Transcription accuracy | > 95% | Manual review sample |
| Classification accuracy | > 85% | Corrections / total |
| Morning brief delivery | 100% at 7am | Logs |
| Correction response | < 1 minute | Time to update after "wrong" |
| Knowledge graph growth | +10 entities/week | Notion page count |

---

## 12. Deployment & Operations

### 12.1 Deployment Strategy

**Philosophy:** Simple, reproducible, observable. Personal project = minimal infrastructure complexity.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        DEPLOYMENT PIPELINE                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Developer                GitHub                 DigitalOcean           │
│   ─────────                ──────                 ────────────           │
│                                                                          │
│   git push ──────────►  GitHub Actions  ────────►  Docker Pull           │
│                         │                         │                      │
│                         ├─► Run tests             ├─► Stop old container │
│                         ├─► Build Docker image    ├─► Start new container│
│                         ├─► Push to GHCR          ├─► Health check       │
│                         └─► Deploy (on main)      └─► Notify on failure  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 12.2 Infrastructure Requirements

**DigitalOcean Droplet Specification:**

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 1 vCPU | 1 vCPU |
| RAM | 1 GB | 2 GB |
| Storage | 25 GB SSD | 50 GB SSD |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| Region | Any | Closest to user |

**Monthly Cost:** ~$6-12/month

**Required Software on Droplet:**
- Docker Engine 24+
- Docker Compose v2
- fail2ban (security)
- ufw (firewall)
- certbot (if webhook mode, not needed for long-polling)

### 12.3 Repository Structure for Deployment

```
├── .github/
│   └── workflows/
│       ├── ci.yml              # Run on every PR: lint, type-check, test
│       ├── cd.yml              # Run on main push: build, push, deploy
│       └── scheduled.yml       # Weekly: dependency updates, security scan
├── deploy/
│   ├── Dockerfile              # Multi-stage production image
│   ├── docker-compose.yml      # Production compose file
│   ├── docker-compose.dev.yml  # Development compose file
│   ├── .env.example            # Template for required env vars
│   ├── scripts/
│   │   ├── deploy.sh           # Remote deployment script
│   │   ├── rollback.sh         # Rollback to previous version
│   │   ├── health-check.sh     # Verify service is healthy
│   │   └── backup.sh           # Backup state files
│   └── systemd/
│       ├── second-brain.service
│       ├── second-brain-briefing.timer
│       └── second-brain-nudge.timer
└── pyproject.toml
```

### 12.4 Docker Configuration

**Dockerfile (Multi-stage):**
```dockerfile
# Stage 1: Build
FROM python:3.12-slim as builder
WORKDIR /app
COPY pyproject.toml ./
RUN pip install build && python -m build --wheel

# Stage 2: Runtime
FROM python:3.12-slim
WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 assistant
USER assistant

# Install wheel from builder
COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --user /tmp/*.whl && rm /tmp/*.whl

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import assistant; print('ok')" || exit 1

ENV PATH="/home/assistant/.local/bin:$PATH"
CMD ["assistant", "run"]
```

**docker-compose.yml:**
```yaml
version: "3.8"
services:
  bot:
    image: ghcr.io/${GITHUB_REPOSITORY}:latest
    container_name: second-brain
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/home/assistant/.second-brain
      - ./logs:/app/logs
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "python", "-c", "import assistant; print('ok')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 12.5 CI/CD Pipeline

**GitHub Actions - CI (ci.yml):**
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: mypy src
      - run: pytest --cov=assistant --cov-report=xml
      - uses: codecov/codecov-action@v4
```

**GitHub Actions - CD (cd.yml):**
```yaml
name: CD
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Build and push Docker image
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: deploy/Dockerfile
          push: true
          tags: ghcr.io/${{ github.repository }}:latest

      # Deploy to DigitalOcean
      - uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.DO_HOST }}
          username: ${{ secrets.DO_USER }}
          key: ${{ secrets.DO_SSH_KEY }}
          script: |
            cd /opt/second-brain
            docker compose pull
            docker compose up -d
            ./scripts/health-check.sh
```

### 12.6 Environment Configuration

**Production Environment Variables (.env):**

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | From @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your chat ID for briefings |
| `NOTION_API_KEY` | Yes | From notion.so/my-integrations |
| `NOTION_*_DB_ID` | Yes | Database IDs (9 total) |
| `OPENAI_API_KEY` | Yes | For Whisper |
| `GOOGLE_CLIENT_ID` | Optional | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Optional | OAuth client secret |
| `USER_TIMEZONE` | Yes | e.g., "America/Los_Angeles" |
| `LOG_LEVEL` | No | DEBUG/INFO/WARNING (default: INFO) |
| `CONFIDENCE_THRESHOLD` | No | 0-100 (default: 80) |

**GitHub Secrets Required:**

| Secret | Purpose |
|--------|---------|
| `DO_HOST` | Droplet IP address |
| `DO_USER` | SSH username (e.g., `deploy`) |
| `DO_SSH_KEY` | Private SSH key for deployment |

### 12.7 Initial Server Setup

**One-time setup script (run manually on new droplet):**

```bash
#!/bin/bash
# setup-server.sh - Run once on fresh Ubuntu 24.04 droplet

set -euo pipefail

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# Install fail2ban
apt install -y fail2ban
systemctl enable fail2ban

# Configure firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

# Create deploy user
useradd -m -s /bin/bash deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
# Add your public key to /home/deploy/.ssh/authorized_keys

# Create app directory
mkdir -p /opt/second-brain/{data,logs,scripts}
chown -R deploy:deploy /opt/second-brain

# Copy systemd timers
cp deploy/systemd/*.service /etc/systemd/system/
cp deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable second-brain-briefing.timer
systemctl enable second-brain-nudge.timer

echo "Server setup complete. Deploy from GitHub Actions."
```

### 12.8 Health Checks & Monitoring

**Health Check Script (health-check.sh):**
```bash
#!/bin/bash
# Verify bot is healthy after deployment

MAX_RETRIES=10
RETRY_INTERVAL=3

for i in $(seq 1 $MAX_RETRIES); do
    if docker exec second-brain python -c "import assistant; print('ok')" 2>/dev/null; then
        echo "✓ Health check passed"
        exit 0
    fi
    echo "Waiting for container... ($i/$MAX_RETRIES)"
    sleep $RETRY_INTERVAL
done

echo "✗ Health check failed"
exit 1
```

**Monitoring Options:**

| Tool | Purpose | Cost |
|------|---------|------|
| UptimeRobot | Ping monitoring (5 min) | Free |
| Telegram alerts | Failed deploys, errors | Free (via bot) |
| DigitalOcean Monitoring | CPU, memory, disk | Included |
| Sentry | Error tracking | Free tier |

**Self-Monitoring (via Telegram):**
- Bot sends alert to owner on startup failure
- Bot sends alert if Notion sync fails 3x
- Bot sends daily health summary (optional)

### 12.9 Backup Strategy

**What to backup:**
- `~/.second-brain/queue/` - Offline queue (critical during outages)
- `~/.second-brain/google_token.json` - OAuth tokens
- `~/.second-brain/nudges/sent.json` - Dedup state

**Backup script (backup.sh):**
```bash
#!/bin/bash
BACKUP_DIR="/opt/second-brain/backups"
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p $BACKUP_DIR
tar -czf "$BACKUP_DIR/state-$DATE.tar.gz" \
    /opt/second-brain/data/

# Keep last 7 days
find $BACKUP_DIR -name "state-*.tar.gz" -mtime +7 -delete
```

**Notion is the primary backup:**
- All data lives in Notion (externally hosted, backed up by Notion)
- Local state is ephemeral/recoverable

### 12.10 Rollback Strategy

**Automatic rollback on failed health check:**
```bash
#!/bin/bash
# rollback.sh - Revert to previous image

PREVIOUS_IMAGE=$(docker images ghcr.io/$REPO --format "{{.Tag}}" | sed -n '2p')

if [ -z "$PREVIOUS_IMAGE" ]; then
    echo "No previous image found"
    exit 1
fi

docker compose down
docker tag ghcr.io/$REPO:$PREVIOUS_IMAGE ghcr.io/$REPO:latest
docker compose up -d

echo "Rolled back to $PREVIOUS_IMAGE"
```

**Manual rollback:**
```bash
ssh deploy@droplet "cd /opt/second-brain && ./scripts/rollback.sh"
```

### 12.11 Deployment Acceptance Tests

### AT-201 — Docker Build Success
- **Given:** Code passes all tests
- **When:** Docker build runs
- **Then:** Image builds without errors
- **And:** Image size < 500MB
- **Pass condition:** `docker build` exits 0

### AT-202 — Container Starts Healthy
- **Given:** Valid .env file present
- **When:** `docker compose up -d` runs
- **Then:** Container reaches healthy state within 60s
- **Pass condition:** `docker inspect --format='{{.State.Health.Status}}'` returns "healthy"

### AT-203 — CI Pipeline Passes
- **Given:** PR opened against main
- **When:** GitHub Actions CI runs
- **Then:** All jobs pass (lint, type-check, test)
- **Pass condition:** GitHub checks show green

### AT-204 — CD Pipeline Deploys
- **Given:** Merge to main branch
- **When:** GitHub Actions CD runs
- **Then:** New image pushed to GHCR
- **And:** Droplet pulls and starts new container
- **And:** Health check passes
- **Pass condition:** Container running with new image SHA

### AT-205 — Rollback Works
- **Given:** Current deployment is broken
- **When:** `./scripts/rollback.sh` executed
- **Then:** Previous image restored
- **And:** Container healthy
- **Pass condition:** Bot responds to Telegram message

### AT-206 — Scheduled Timers Work
- **Given:** Deployed to droplet with systemd timers
- **When:** Timer triggers (briefing at 7am, nudge at 2pm)
- **Then:** Command executes successfully
- **Pass condition:** Log shows successful execution

### AT-207 — Zero-Downtime Deploy
- **Given:** Bot is running and receiving messages
- **When:** New deployment triggered
- **Then:** Messages during deploy are not lost
- **And:** Downtime < 30 seconds
- **Pass condition:** No messages lost (queue persists)

### AT-208 — Security Hardening
- **Given:** Fresh droplet with setup script run
- **Then:** SSH password auth disabled
- **And:** UFW enabled (only SSH open)
- **And:** fail2ban running
- **And:** Docker container runs as non-root
- **Pass condition:** Security audit script passes

### 12.12 Deployment Tasks

| Task ID | Pri | Title | Depends On | Acceptance Test |
|---------|-----|-------|------------|-----------------|
| T-200 | P0 | Create Dockerfile (multi-stage) | — | AT-201 |
| T-201 | P0 | Create docker-compose.yml | T-200 | AT-202 |
| T-202 | P0 | Set up GitHub Actions CI | — | AT-203 |
| T-203 | P0 | Set up GitHub Actions CD | T-200, T-202 | AT-204 |
| T-204 | P0 | Create server setup script | — | AT-208 |
| T-205 | P0 | Create health check script | T-201 | AT-202 |
| T-206 | P0 | Create rollback script | T-203 | AT-205 |
| T-207 | P1 | Configure systemd timers on server | T-204 | AT-206 |
| T-208 | P1 | Add Telegram deployment notifications | T-203 | — |
| T-209 | P1 | Create backup script | T-204 | — |
| T-210 | P2 | Add Sentry error tracking | T-201 | — |
| T-211 | P2 | Set up UptimeRobot monitoring | T-204 | — |

---

## 13. Changelog

- 0.6.1 (2026-01-12): LLM intent parsing acceptance test
  - Added AT-128 for LLM intent parsing with fallback behavior

- 0.6.0 (2026-01-12): Deployment & Operations
  - Added Section 12: Deployment & Operations (DigitalOcean, Docker, CI/CD)
  - Added Section 12.1-12.3: Deployment strategy, infrastructure requirements, repo structure
  - Added Section 12.4-12.5: Docker configuration, CI/CD pipeline (GitHub Actions)
  - Added Section 12.6-12.7: Environment configuration, server setup script
  - Added Section 12.8-12.10: Health checks, monitoring, backup, rollback strategies
  - Added acceptance tests AT-201 through AT-208 (deployment)
  - Added deployment tasks T-200 through T-211
  - Renumbered Changelog to Section 13

- 0.5.0 (2026-01-11): Google integrations expansion
  - Added Section 4.6: Google Maps API (place enrichment, travel times, proximity)
  - Added Section 4.7: Google Drive API (research docs, meeting notes, comparisons)
  - Renumbered Sections 4.8-4.10 (Failure Handling, Idempotency, Playwright)
  - Added acceptance tests AT-121 through AT-127 (Maps and Drive)
  - Added Phase 8: Google Maps Integration (T-150 to T-157)
  - Added Phase 9: Google Drive Integration (T-160 to T-167)
  - Added future tasks T-170 to T-172 (location triggers, Slides, sharing)
  - Updated API Keys section with OAuth scopes and Maps APIs required

- 0.4.0 (2026-01-11): Critical gap fixes
  - Added Section 1: Tech Stack & Deployment (Python, aiogram, systemd)
  - Added Section 1.3: Secrets Management
  - Added Section 1.4: Cost Estimate
  - Added Section 3.6: Failure Handling (offline queue, retries)
  - Added Section 3.7: Idempotency (dedupe keys, exactly-once)
  - Added Section 4.4: Timezone Handling
  - Added Section 4.5: Disambiguation (multiple people with same name)
  - Added Section 4.6: Deletion Semantics (soft vs hard delete)
  - Added Section 5.2: Undo & Rollback Semantics
  - Added Section 5.3: Confirmation Requirements
  - Enhanced Inbox schema: telegram IDs, dedupe_key, processing_error
  - Enhanced Tasks schema: people (multiple), deleted_at, calendar_event_id, timezone
  - Enhanced People schema: aliases, unique_key, email, phone, telegram_handle
  - Enhanced Log schema: request_id, idempotency_key, external_api, undo fields
  - Added acceptance tests AT-113 through AT-120

- 0.3.0 (2026-01-11): Major architecture revision - Second Brain
  - Replaced file-based storage with Notion knowledge graph
  - Added Telegram as primary input channel
  - Added Whisper voice transcription
  - Defined 8-component Second Brain framework
  - Added entity extraction, confidence scoring, pattern learning
  - Defined morning briefing and on-demand debrief flows
  - Created new acceptance tests AT-101 through AT-112
  - Reorganized task backlog into phases
  - Defined autonomy levels (current vs future)
  
- 0.2.0 (2026-01-11): Initial PRD - file-based MVP
  - Basic task management
  - Local knowledge base
  - Stuck detection and cost tracking
