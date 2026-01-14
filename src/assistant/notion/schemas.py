import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    INBOX = "inbox"
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class TaskPriority(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SOMEDAY = "someday"


class TaskSource(str, Enum):
    TELEGRAM = "telegram"
    VOICE = "voice"
    MANUAL = "manual"
    AI_CREATED = "ai_created"
    EMAIL = "email"


class InboxSource(str, Enum):
    TELEGRAM_TEXT = "telegram_text"
    TELEGRAM_VOICE = "telegram_voice"
    MANUAL = "manual"


class Relationship(str, Enum):
    PARTNER = "partner"
    FAMILY = "family"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    ACQUAINTANCE = "acquaintance"


class EmailUrgency(str, Enum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ActionType(str, Enum):
    CAPTURE = "capture"
    CLASSIFY = "classify"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SEND = "send"
    RESEARCH = "research"
    EMAIL_READ = "email_read"
    EMAIL_SEND = "email_send"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_UPDATE = "calendar_update"
    ERROR = "error"
    RETRY = "retry"


def generate_id() -> str:
    return str(uuid.uuid4())


class InboxItem(BaseModel):
    id: str = Field(default_factory=generate_id)
    raw_input: str
    source: InboxSource
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processed: bool = False
    confidence: int = 0
    needs_clarification: bool = False
    interpretation: str | None = None
    telegram_chat_id: str | None = None
    telegram_message_id: str | None = None
    voice_file_id: str | None = None
    transcript_confidence: int | None = None
    language: str | None = None
    processing_error: str | None = None
    retry_count: int = 0
    dedupe_key: str | None = None


class Task(BaseModel):
    id: str = Field(default_factory=generate_id)
    title: str
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: datetime | None = None
    due_timezone: str | None = None
    people_ids: list[str] = Field(default_factory=list)
    place_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    source: TaskSource = TaskSource.TELEGRAM
    source_inbox_item_id: str | None = None
    confidence: int = 100
    created_by: str = "user"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_modified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    deleted_at: datetime | None = None
    calendar_event_id: str | None = None
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    estimated_duration: int | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class Person(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    aliases: list[str] = Field(default_factory=list)
    unique_key: str | None = None
    relationship: Relationship | None = None
    company: str | None = None
    email: str | None = None
    phone: str | None = None
    telegram_handle: str | None = None
    preferences: str | None = None
    quirks: str | None = None
    communication_style: str | None = None
    last_contact: datetime | None = None
    archived: bool = False
    deleted_at: datetime | None = None
    notes: str | None = None


class Project(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    status: str = "active"
    project_type: str = "personal"
    people_ids: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    next_action: str | None = None
    context: str | None = None
    archived: bool = False
    deleted_at: datetime | None = None


class Place(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    place_type: str = "other"
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    google_place_id: str | None = None
    phone: str | None = None
    website: str | None = None
    your_preference: str | None = None
    last_visit: datetime | None = None
    rating: int | None = None
    archived: bool = False
    deleted_at: datetime | None = None
    notes: str | None = None

    @property
    def coordinates(self) -> tuple[float, float] | None:
        """Return (lat, lng) tuple if both coordinates are set."""
        if self.lat is not None and self.lng is not None:
            return (self.lat, self.lng)
        return None

    @property
    def is_geocoded(self) -> bool:
        """Check if this place has been geocoded."""
        return self.lat is not None and self.lng is not None


class Preference(BaseModel):
    id: str = Field(default_factory=generate_id)
    category: str
    preference: str
    details: str | None = None
    learned_from: str | None = None
    learned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: int = 50
    times_applied: int = 0


class Pattern(BaseModel):
    id: str = Field(default_factory=generate_id)
    trigger: str
    meaning: str
    confidence: int = 50
    times_confirmed: int = 0
    times_wrong: int = 0
    last_used: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Email(BaseModel):
    """Email stored in Notion with LLM-analyzed intelligence."""

    id: str = Field(default_factory=generate_id)
    gmail_id: str
    thread_id: str
    subject: str
    from_address: str
    to_address: str | None = None
    snippet: str | None = None
    body_preview: str | None = None  # First ~500 chars of body for context
    received_at: datetime
    has_attachments: bool = False
    labels: list[str] = Field(default_factory=list)

    # Intelligence fields (populated by LLM analysis)
    importance_score: int | None = None  # 0-100
    urgency: str = "normal"  # urgent/high/normal/low
    action_items: list[str] = Field(default_factory=list)
    people_mentioned: list[str] = Field(default_factory=list)
    suggested_response: str | None = None
    category: str | None = None  # work, personal, newsletter, etc.
    analyzed_at: datetime | None = None

    # Processing state
    processed: bool = False
    needs_response: bool = False
    response_draft: str | None = None
    response_sent: bool = False
    response_sent_at: datetime | None = None
    linked_task_id: str | None = None  # If a task was created from this email


class LogEntry(BaseModel):
    id: str = Field(default_factory=generate_id)
    request_id: str = Field(default_factory=generate_id)
    idempotency_key: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action_type: ActionType
    input_text: str | None = None
    interpretation: str | None = None
    action_taken: str | None = None
    confidence: int | None = None
    entities_affected: list[str] = Field(default_factory=list)
    external_api: str | None = None
    external_resource_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    correction: str | None = None
    corrected_at: datetime | None = None
    undo_available_until: datetime | None = None
    undone: bool = False
