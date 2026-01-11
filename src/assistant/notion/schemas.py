from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    processed: bool = False
    confidence: int = 0
    needs_clarification: bool = False
    interpretation: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_message_id: Optional[str] = None
    voice_file_id: Optional[str] = None
    transcript_confidence: Optional[int] = None
    language: Optional[str] = None
    processing_error: Optional[str] = None
    retry_count: int = 0
    dedupe_key: Optional[str] = None


class Task(BaseModel):
    id: str = Field(default_factory=generate_id)
    title: str
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: Optional[datetime] = None
    due_timezone: Optional[str] = None
    people_ids: list[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    source: TaskSource = TaskSource.TELEGRAM
    source_inbox_item_id: Optional[str] = None
    confidence: int = 100
    created_by: str = "user"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_modified_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    calendar_event_id: Optional[str] = None
    estimated_duration: Optional[int] = None
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class Person(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    aliases: list[str] = Field(default_factory=list)
    unique_key: Optional[str] = None
    relationship: Optional[Relationship] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    telegram_handle: Optional[str] = None
    preferences: Optional[str] = None
    quirks: Optional[str] = None
    communication_style: Optional[str] = None
    last_contact: Optional[datetime] = None
    archived: bool = False
    deleted_at: Optional[datetime] = None
    notes: Optional[str] = None


class Project(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    status: str = "active"
    project_type: str = "personal"
    people_ids: list[str] = Field(default_factory=list)
    deadline: Optional[datetime] = None
    next_action: Optional[str] = None
    context: Optional[str] = None
    archived: bool = False
    deleted_at: Optional[datetime] = None


class Place(BaseModel):
    id: str = Field(default_factory=generate_id)
    name: str
    place_type: str = "other"
    address: Optional[str] = None
    your_preference: Optional[str] = None
    last_visit: Optional[datetime] = None
    rating: Optional[int] = None
    archived: bool = False
    deleted_at: Optional[datetime] = None
    notes: Optional[str] = None


class Preference(BaseModel):
    id: str = Field(default_factory=generate_id)
    category: str
    preference: str
    details: Optional[str] = None
    learned_from: Optional[str] = None
    learned_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: int = 50
    times_applied: int = 0


class Pattern(BaseModel):
    id: str = Field(default_factory=generate_id)
    trigger: str
    meaning: str
    confidence: int = 50
    times_confirmed: int = 0
    times_wrong: int = 0
    last_used: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Email(BaseModel):
    id: str = Field(default_factory=generate_id)
    gmail_id: str
    thread_id: str
    from_person_id: Optional[str] = None
    subject: str
    snippet: Optional[str] = None
    received_at: datetime
    is_read: bool = False
    needs_response: bool = False
    priority: str = "normal"
    extracted_task_ids: list[str] = Field(default_factory=list)
    response_draft: Optional[str] = None
    response_sent: bool = False
    response_sent_at: Optional[datetime] = None


class LogEntry(BaseModel):
    id: str = Field(default_factory=generate_id)
    request_id: str = Field(default_factory=generate_id)
    idempotency_key: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action_type: ActionType
    input_text: Optional[str] = None
    interpretation: Optional[str] = None
    action_taken: Optional[str] = None
    confidence: Optional[int] = None
    entities_affected: list[str] = Field(default_factory=list)
    external_api: Optional[str] = None
    external_resource_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    correction: Optional[str] = None
    corrected_at: Optional[datetime] = None
    undo_available_until: Optional[datetime] = None
    undone: bool = False
