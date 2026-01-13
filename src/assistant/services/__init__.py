"""Second Brain services module.

This module provides core services for message processing, entity extraction,
confidence scoring, and more. Imports are lazy to avoid heavyweight dependencies
at module import time.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    # Briefing
    "BriefingGenerator": ("assistant.services.briefing", "BriefingGenerator"),
    "generate_briefing": ("assistant.services.briefing", "generate_briefing"),
    # Clarification
    "ClarificationService": ("assistant.services.clarification", "ClarificationService"),
    # Confidence
    "ConfidenceScorer": ("assistant.services.confidence", "ConfidenceScorer"),
    # Offline Queue (T-114)
    "OfflineQueue": ("assistant.services.offline_queue", "OfflineQueue"),
    "QueuedAction": ("assistant.services.offline_queue", "QueuedAction"),
    "QueuedActionType": ("assistant.services.offline_queue", "QueuedActionType"),
    "QueueProcessResult": ("assistant.services.offline_queue", "QueueProcessResult"),
    "get_offline_queue": ("assistant.services.offline_queue", "get_offline_queue"),
    "get_offline_response": ("assistant.services.offline_queue", "get_offline_response"),
    "process_offline_queue": ("assistant.services.offline_queue", "process_offline_queue"),
    "queue_for_offline_sync": ("assistant.services.offline_queue", "queue_for_offline_sync"),
    # Corrections
    "CorrectionHandler": ("assistant.services.corrections", "CorrectionHandler"),
    "CorrectionResult": ("assistant.services.corrections", "CorrectionResult"),
    "get_correction_handler": ("assistant.services.corrections", "get_correction_handler"),
    "is_correction_message": ("assistant.services.corrections", "is_correction_message"),
    "process_correction": ("assistant.services.corrections", "process_correction"),
    "track_created_task": ("assistant.services.corrections", "track_created_task"),
    # Patterns (detection)
    "CorrectionRecord": ("assistant.services.patterns", "CorrectionRecord"),
    "DetectedPattern": ("assistant.services.patterns", "DetectedPattern"),
    "PatternDetector": ("assistant.services.patterns", "PatternDetector"),
    "add_correction": ("assistant.services.patterns", "add_correction"),
    "add_correction_and_store": ("assistant.services.patterns", "add_correction_and_store"),
    "get_pattern_detector": ("assistant.services.patterns", "get_pattern_detector"),
    "load_and_analyze_patterns": ("assistant.services.patterns", "load_and_analyze_patterns"),
    "store_pending_patterns": ("assistant.services.patterns", "store_pending_patterns"),
    # Patterns (application - T-093)
    "AppliedPattern": ("assistant.services.pattern_applicator", "AppliedPattern"),
    "PatternApplicator": ("assistant.services.pattern_applicator", "PatternApplicator"),
    "PatternApplicationResult": (
        "assistant.services.pattern_applicator",
        "PatternApplicationResult",
    ),
    "apply_patterns": ("assistant.services.pattern_applicator", "apply_patterns"),
    "get_pattern_applicator": ("assistant.services.pattern_applicator", "get_pattern_applicator"),
    "load_patterns": ("assistant.services.pattern_applicator", "load_patterns"),
    # Entities
    "EntityExtractor": ("assistant.services.entities", "EntityExtractor"),
    "ExtractedDate": ("assistant.services.entities", "ExtractedDate"),
    "ExtractedEntities": ("assistant.services.entities", "ExtractedEntities"),
    # Timezone (T-116)
    "ParsedTimezone": ("assistant.services.timezone", "ParsedTimezone"),
    "TIMEZONE_ABBREVIATIONS": ("assistant.services.timezone", "TIMEZONE_ABBREVIATIONS"),
    "TimezoneAwareDateTime": ("assistant.services.timezone", "TimezoneAwareDateTime"),
    "TimezoneService": ("assistant.services.timezone", "TimezoneService"),
    "get_timezone_service": ("assistant.services.timezone", "get_timezone_service"),
    "localize": ("assistant.services.timezone", "localize"),
    "now": ("assistant.services.timezone", "now"),
    "parse_time_with_timezone": ("assistant.services.timezone", "parse_time_with_timezone"),
    "reset_timezone_service": ("assistant.services.timezone", "reset_timezone_service"),
    "today": ("assistant.services.timezone", "today"),
    # Parser
    "ParsedIntent": ("assistant.services.intent", "ParsedIntent"),
    "Parser": ("assistant.services.parser", "Parser"),
    "LLMIntentParser": ("assistant.services.llm_parser", "LLMIntentParser"),
    "get_intent_parser": ("assistant.services.llm_parser", "get_intent_parser"),
    # People
    "PeopleService": ("assistant.services.people", "PeopleService"),
    # Places
    "PlacesService": ("assistant.services.places", "PlacesService"),
    # Processor
    "MessageProcessor": ("assistant.services.processor", "MessageProcessor"),
    # Projects
    "ProjectsService": ("assistant.services.projects", "ProjectsService"),
    # Relations
    "LinkedRelations": ("assistant.services.relations", "LinkedRelations"),
    "RelationLinker": ("assistant.services.relations", "RelationLinker"),
    # Router
    "ClassificationRouter": ("assistant.services.router", "ClassificationRouter"),
    "RoutingDecision": ("assistant.services.router", "RoutingDecision"),
    # Whisper
    "WhisperTranscriber": ("assistant.services.whisper", "WhisperTranscriber"),
    # Research (T-103)
    "ResearchResult": ("assistant.services.research", "ResearchResult"),
    "ResearchSource": ("assistant.services.research", "ResearchSource"),
    "WebResearcher": ("assistant.services.research", "WebResearcher"),
    "close_researcher": ("assistant.services.research", "close_researcher"),
    "get_web_researcher": ("assistant.services.research", "get_web_researcher"),
    "is_research_available": ("assistant.services.research", "is_research_available"),
    "research": ("assistant.services.research", "research"),
    "research_cinema": ("assistant.services.research", "research_cinema"),
    # Research Formatter (T-104)
    "FormattedResearch": ("assistant.services.research_formatter", "FormattedResearch"),
    "ResearchFormatter": ("assistant.services.research_formatter", "ResearchFormatter"),
    "format_research_for_notion": (
        "assistant.services.research_formatter",
        "format_research_for_notion",
    ),
    "format_research_for_telegram": (
        "assistant.services.research_formatter",
        "format_research_for_telegram",
    ),
    "get_research_formatter": (
        "assistant.services.research_formatter",
        "get_research_formatter",
    ),
    "log_research_result": ("assistant.services.research_formatter", "log_research_result"),
    # Soft Delete (T-115)
    "DeletedAction": ("assistant.services.soft_delete", "DeletedAction"),
    "DeleteResult": ("assistant.services.soft_delete", "DeleteResult"),
    "SoftDeleteService": ("assistant.services.soft_delete", "SoftDeleteService"),
    "UndoResult": ("assistant.services.soft_delete", "UndoResult"),
    "get_soft_delete_service": ("assistant.services.soft_delete", "get_soft_delete_service"),
    "is_delete_command": ("assistant.services.soft_delete", "is_delete_command"),
    "is_undo_command": ("assistant.services.soft_delete", "is_undo_command"),
    "restore_by_id": ("assistant.services.soft_delete", "restore_by_id"),
    "soft_delete": ("assistant.services.soft_delete", "soft_delete"),
    "undo_last_delete": ("assistant.services.soft_delete", "undo_last_delete"),
    # Nudges (T-130)
    "NudgeCandidate": ("assistant.services.nudges", "NudgeCandidate"),
    "NudgeReport": ("assistant.services.nudges", "NudgeReport"),
    "NudgeResult": ("assistant.services.nudges", "NudgeResult"),
    "NudgeService": ("assistant.services.nudges", "NudgeService"),
    "NudgeType": ("assistant.services.nudges", "NudgeType"),
    "format_nudge_message": ("assistant.services.nudges", "format_nudge_message"),
    "get_nudge_service": ("assistant.services.nudges", "get_nudge_service"),
    "get_pending_nudges": ("assistant.services.nudges", "get_pending_nudges"),
    "run_nudges": ("assistant.services.nudges", "run_nudges"),
    # Email Auto-Reply (T-122)
    "AutoReplyResult": ("assistant.services.email_auto_reply", "AutoReplyResult"),
    "EmailAutoReplyService": ("assistant.services.email_auto_reply", "EmailAutoReplyService"),
    "SenderPattern": ("assistant.services.email_auto_reply", "SenderPattern"),
    "analyze_sender_pattern": ("assistant.services.email_auto_reply", "analyze_sender_pattern"),
    "create_reply_draft": ("assistant.services.email_auto_reply", "create_reply_draft"),
    "get_auto_reply_service": ("assistant.services.email_auto_reply", "get_auto_reply_service"),
    "process_auto_reply": ("assistant.services.email_auto_reply", "process_auto_reply"),
    "should_auto_reply": ("assistant.services.email_auto_reply", "should_auto_reply"),
    # Heartbeat/UptimeRobot Monitoring (T-211)
    "HeartbeatResult": ("assistant.services.heartbeat", "HeartbeatResult"),
    "HeartbeatService": ("assistant.services.heartbeat", "HeartbeatService"),
    "get_heartbeat_service": ("assistant.services.heartbeat", "get_heartbeat_service"),
    "is_heartbeat_configured": ("assistant.services.heartbeat", "is_heartbeat_configured"),
    "send_heartbeat": ("assistant.services.heartbeat", "send_heartbeat"),
    "start_heartbeat": ("assistant.services.heartbeat", "start_heartbeat"),
    "stop_heartbeat": ("assistant.services.heartbeat", "stop_heartbeat"),
    # Always-On Listening (T-131 - Future Phase 3)
    "AlwaysOnListener": ("assistant.services.always_on", "AlwaysOnListener"),
    "AlwaysOnListenerNotAvailable": (
        "assistant.services.always_on",
        "AlwaysOnListenerNotAvailable",
    ),
    "CaptureResult": ("assistant.services.always_on", "CaptureResult"),
    "ListenerConfig": ("assistant.services.always_on", "ListenerConfig"),
    "ListenerState": ("assistant.services.always_on", "ListenerState"),
    "get_always_on_listener": ("assistant.services.always_on", "get_always_on_listener"),
    "get_always_on_status": ("assistant.services.always_on", "get_always_on_status"),
    "is_always_on_available": ("assistant.services.always_on", "is_always_on_available"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_EXPORTS.keys()))
