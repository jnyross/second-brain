"""Second Brain services module.

This module provides core services for message processing, entity extraction,
confidence scoring, and more.
"""

from assistant.services.briefing import BriefingGenerator, generate_briefing
from assistant.services.clarification import ClarificationService
from assistant.services.confidence import ConfidenceScorer
from assistant.services.offline_queue import (
    OfflineQueue,
    QueuedAction,
    QueuedActionType,
    QueueProcessResult,
    get_offline_queue,
    get_offline_response,
    process_offline_queue,
    queue_for_offline_sync,
)
from assistant.services.corrections import (
    CorrectionHandler,
    CorrectionResult,
    get_correction_handler,
    is_correction_message,
    process_correction,
    track_created_task,
)
from assistant.services.patterns import (
    CorrectionRecord,
    DetectedPattern,
    PatternDetector,
    add_correction,
    add_correction_and_store,
    get_pattern_detector,
    load_and_analyze_patterns,
    store_pending_patterns,
)
from assistant.services.pattern_applicator import (
    AppliedPattern,
    PatternApplicator,
    PatternApplicationResult,
    apply_patterns,
    get_pattern_applicator,
    load_patterns,
)
from assistant.services.entities import EntityExtractor, ExtractedDate, ExtractedEntities
from assistant.services.timezone import (
    ParsedTimezone,
    TIMEZONE_ABBREVIATIONS,
    TimezoneAwareDateTime,
    TimezoneService,
    get_timezone_service,
    localize,
    now,
    parse_time_with_timezone,
    reset_timezone_service,
    today,
)
from assistant.services.parser import ParsedIntent, Parser
from assistant.services.people import PeopleService
from assistant.services.places import PlacesService
from assistant.services.processor import MessageProcessor
from assistant.services.projects import ProjectsService
from assistant.services.relations import LinkedRelations, RelationLinker
from assistant.services.router import ClassificationRouter, RoutingDecision
from assistant.services.soft_delete import (
    DeletedAction,
    DeleteResult,
    SoftDeleteService,
    UndoResult,
    get_soft_delete_service,
    is_delete_command,
    is_undo_command,
    restore_by_id,
    soft_delete,
    undo_last_delete,
)
from assistant.services.whisper import WhisperTranscriber

__all__ = [
    # Briefing
    "BriefingGenerator",
    "generate_briefing",
    # Clarification
    "ClarificationService",
    # Confidence
    "ConfidenceScorer",
    # Offline Queue (T-114)
    "OfflineQueue",
    "QueuedAction",
    "QueuedActionType",
    "QueueProcessResult",
    "get_offline_queue",
    "get_offline_response",
    "process_offline_queue",
    "queue_for_offline_sync",
    # Corrections
    "CorrectionHandler",
    "CorrectionResult",
    "get_correction_handler",
    "is_correction_message",
    "process_correction",
    "track_created_task",
    # Patterns (detection)
    "CorrectionRecord",
    "DetectedPattern",
    "PatternDetector",
    "add_correction",
    "add_correction_and_store",
    "get_pattern_detector",
    "load_and_analyze_patterns",
    "store_pending_patterns",
    # Patterns (application - T-093)
    "AppliedPattern",
    "PatternApplicator",
    "PatternApplicationResult",
    "apply_patterns",
    "get_pattern_applicator",
    "load_patterns",
    # Entities
    "EntityExtractor",
    "ExtractedDate",
    "ExtractedEntities",
    # Timezone (T-116)
    "ParsedTimezone",
    "TIMEZONE_ABBREVIATIONS",
    "TimezoneAwareDateTime",
    "TimezoneService",
    "get_timezone_service",
    "localize",
    "now",
    "parse_time_with_timezone",
    "reset_timezone_service",
    "today",
    # Parser
    "ParsedIntent",
    "Parser",
    # People
    "PeopleService",
    # Places
    "PlacesService",
    # Processor
    "MessageProcessor",
    # Projects
    "ProjectsService",
    # Relations
    "LinkedRelations",
    "RelationLinker",
    # Router
    "ClassificationRouter",
    "RoutingDecision",
    # Whisper
    "WhisperTranscriber",
    # Soft Delete (T-115)
    "DeletedAction",
    "DeleteResult",
    "SoftDeleteService",
    "UndoResult",
    "get_soft_delete_service",
    "is_delete_command",
    "is_undo_command",
    "restore_by_id",
    "soft_delete",
    "undo_last_delete",
]
