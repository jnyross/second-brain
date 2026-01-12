"""Second Brain services module.

This module provides core services for message processing, entity extraction,
confidence scoring, and more.
"""

from assistant.services.briefing import BriefingGenerator, generate_briefing
from assistant.services.clarification import ClarificationService
from assistant.services.confidence import ConfidenceScorer
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
    get_pattern_detector,
    load_and_analyze_patterns,
    store_pending_patterns,
)
from assistant.services.entities import EntityExtractor, ExtractedEntities
from assistant.services.parser import ParsedIntent, Parser
from assistant.services.people import PeopleService
from assistant.services.places import PlacesService
from assistant.services.processor import MessageProcessor
from assistant.services.projects import ProjectsService
from assistant.services.relations import LinkedRelations, RelationLinker
from assistant.services.router import ClassificationRouter, RoutingDecision
from assistant.services.whisper import WhisperTranscriber

__all__ = [
    # Briefing
    "BriefingGenerator",
    "generate_briefing",
    # Clarification
    "ClarificationService",
    # Confidence
    "ConfidenceScorer",
    # Corrections
    "CorrectionHandler",
    "CorrectionResult",
    "get_correction_handler",
    "is_correction_message",
    "process_correction",
    "track_created_task",
    # Patterns
    "CorrectionRecord",
    "DetectedPattern",
    "PatternDetector",
    "add_correction",
    "get_pattern_detector",
    "load_and_analyze_patterns",
    "store_pending_patterns",
    # Entities
    "EntityExtractor",
    "ExtractedEntities",
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
]
