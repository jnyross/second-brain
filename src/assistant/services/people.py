"""People service for lookup, creation, and disambiguation.

This service handles:
- Looking up existing people by name or alias
- Creating new people when they don't exist
- Disambiguating between people with similar names
- Ranking matches by recency and relationship type
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from assistant.notion.schemas import Person, Relationship

if TYPE_CHECKING:
    from assistant.notion.client import NotionClient


@dataclass
class PersonMatch:
    """A potential match from the People database."""

    person_id: str
    name: str
    confidence: float  # 0.0 to 1.0
    relationship: str | None = None
    last_contact: datetime | None = None
    aliases: list[str] = field(default_factory=list)
    matched_by: str = "name"  # "name", "alias", "email"

    def __lt__(self, other: "PersonMatch") -> bool:
        """Sort by confidence descending, then recency."""
        if self.confidence != other.confidence:
            return self.confidence > other.confidence
        # If both have last_contact, more recent first
        if self.last_contact and other.last_contact:
            return self.last_contact > other.last_contact
        # Having last_contact is better than not
        if self.last_contact and not other.last_contact:
            return True
        return False


@dataclass
class LookupResult:
    """Result of a person lookup operation."""

    found: bool
    person_id: str | None = None
    person: Person | None = None
    matches: list[PersonMatch] = field(default_factory=list)
    needs_disambiguation: bool = False
    is_new: bool = False

    @property
    def has_single_match(self) -> bool:
        return self.found and len(self.matches) == 1


# Relationship priority for disambiguation (higher = prefer)
RELATIONSHIP_PRIORITY = {
    Relationship.PARTNER: 100,
    Relationship.FAMILY: 90,
    Relationship.FRIEND: 70,
    Relationship.COLLEAGUE: 50,
    Relationship.ACQUAINTANCE: 30,
}


class PeopleService:
    """Service for managing people entities."""

    def __init__(self, notion_client: "NotionClient | None" = None):
        self.notion = notion_client

    async def lookup(self, name: str) -> LookupResult:
        """Look up a person by name or alias.

        Args:
            name: The name to search for

        Returns:
            LookupResult with matches and disambiguation info
        """
        if not self.notion:
            return LookupResult(found=False)

        # Query Notion for people matching name
        results = await self.notion.query_people(name=name)

        if not results:
            return LookupResult(found=False)

        matches = self._parse_results(results, name)

        if len(matches) == 0:
            return LookupResult(found=False)

        if len(matches) == 1:
            match = matches[0]
            return LookupResult(
                found=True,
                person_id=match.person_id,
                matches=matches,
                needs_disambiguation=False,
            )

        # Multiple matches - check if one is clearly better
        sorted_matches = sorted(matches)  # Uses __lt__ for sorting
        best = sorted_matches[0]

        # If best match has much higher confidence, use it
        if best.confidence >= 0.9:
            return LookupResult(
                found=True,
                person_id=best.person_id,
                matches=sorted_matches,
                needs_disambiguation=False,
            )

        # Check if one is a close relationship (partner/family)
        for match in sorted_matches:
            if match.relationship in ("partner", "family"):
                return LookupResult(
                    found=True,
                    person_id=match.person_id,
                    matches=sorted_matches,
                    needs_disambiguation=False,
                )

        # Multiple similar matches - needs disambiguation
        return LookupResult(
            found=True,
            person_id=best.person_id,  # Use best match as default
            matches=sorted_matches,
            needs_disambiguation=True,
        )

    async def lookup_or_create(
        self,
        name: str,
        relationship: Relationship | None = None,
        context: str | None = None,
    ) -> LookupResult:
        """Look up a person, creating them if not found.

        Args:
            name: The name to search for
            relationship: Optional relationship type for new person
            context: Optional context about where this person was mentioned

        Returns:
            LookupResult with person info (found=True always)
        """
        result = await self.lookup(name)

        if result.found:
            return result

        # Create new person
        person = await self.create(name, relationship, context)

        return LookupResult(
            found=True,
            person_id=person.id if hasattr(person, 'id') else None,
            person=person if isinstance(person, Person) else None,
            matches=[
                PersonMatch(
                    person_id=person.id if hasattr(person, 'id') else "",
                    name=name,
                    confidence=1.0,
                    matched_by="created",
                )
            ],
            is_new=True,
        )

    async def create(
        self,
        name: str,
        relationship: Relationship | None = None,
        context: str | None = None,
    ) -> Person:
        """Create a new person.

        Args:
            name: Person's name
            relationship: Optional relationship type
            context: Optional context for notes field

        Returns:
            Created Person object with ID from Notion
        """
        person = Person(
            name=name,
            relationship=relationship,
            notes=context,
        )

        if self.notion:
            person_id = await self.notion.create_person(person)
            # Update the person object with the Notion-assigned ID
            person.id = person_id

        return person

    async def lookup_multiple(
        self,
        names: list[str],
    ) -> dict[str, LookupResult]:
        """Look up multiple people.

        Args:
            names: List of names to search for

        Returns:
            Dict mapping name to LookupResult
        """
        results = {}
        for name in names:
            results[name] = await self.lookup(name)
        return results

    async def get_by_id(self, person_id: str) -> Person | None:
        """Get a person by their Notion page ID.

        Args:
            person_id: Notion page ID

        Returns:
            Person object or None if not found
        """
        if not self.notion:
            return None

        # TODO: Implement direct page fetch in NotionClient
        return None

    async def update_last_contact(self, person_id: str) -> None:
        """Update the last_contact timestamp for a person.

        Args:
            person_id: Notion page ID of the person
        """
        if not self.notion:
            return

        # TODO: Implement page update in NotionClient
        pass

    def _parse_results(
        self,
        results: list[dict],
        search_name: str,
    ) -> list[PersonMatch]:
        """Parse Notion query results into PersonMatch objects.

        Args:
            results: Raw Notion API results
            search_name: Original search term

        Returns:
            List of PersonMatch objects
        """
        matches = []
        search_lower = search_name.lower()

        for result in results:
            props = result.get("properties", {})

            # Extract name
            name_prop = props.get("name", {})
            title_list = name_prop.get("title", [])
            name = title_list[0]["text"]["content"] if title_list else ""

            # Extract aliases
            aliases_prop = props.get("aliases", {})
            aliases_text = aliases_prop.get("rich_text", [])
            aliases_str = aliases_text[0]["text"]["content"] if aliases_text else ""
            aliases = [a.strip() for a in aliases_str.split(",") if a.strip()]

            # Extract relationship
            rel_prop = props.get("relationship", {})
            rel_select = rel_prop.get("select")
            relationship = rel_select["name"] if rel_select else None

            # Extract last_contact
            last_contact_prop = props.get("last_contact", {})
            last_contact_date = last_contact_prop.get("date")
            last_contact = None
            if last_contact_date and last_contact_date.get("start"):
                try:
                    last_contact = datetime.fromisoformat(
                        last_contact_date["start"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Calculate confidence
            confidence, matched_by = self._calculate_match_confidence(
                search_lower, name, aliases, relationship
            )

            matches.append(PersonMatch(
                person_id=result["id"],
                name=name,
                confidence=confidence,
                relationship=relationship,
                last_contact=last_contact,
                aliases=aliases,
                matched_by=matched_by,
            ))

        return matches

    def _calculate_match_confidence(
        self,
        search: str,
        name: str,
        aliases: list[str],
        relationship: str | None,
    ) -> tuple[float, str]:
        """Calculate match confidence score.

        Args:
            search: Lowercase search term
            name: Person's name
            aliases: List of aliases
            relationship: Relationship type

        Returns:
            Tuple of (confidence score, matched_by field)
        """
        name_lower = name.lower()

        # Exact name match
        if search == name_lower:
            confidence = 1.0
            matched_by = "name"
        # Name starts with search
        elif name_lower.startswith(search):
            confidence = 0.9
            matched_by = "name"
        # Search is part of name
        elif search in name_lower:
            confidence = 0.7
            matched_by = "name"
        # Check aliases
        else:
            alias_confidence = 0.0
            for alias in aliases:
                alias_lower = alias.lower()
                if search == alias_lower:
                    alias_confidence = 0.95
                    break
                elif alias_lower.startswith(search):
                    alias_confidence = max(alias_confidence, 0.85)
                elif search in alias_lower:
                    alias_confidence = max(alias_confidence, 0.6)

            if alias_confidence > 0:
                confidence = alias_confidence
                matched_by = "alias"
            else:
                # Fuzzy match - name contains search word
                confidence = 0.5
                matched_by = "partial"

        # Boost for close relationships
        if relationship:
            rel_enum = Relationship(relationship) if relationship in [r.value for r in Relationship] else None
            if rel_enum and rel_enum in RELATIONSHIP_PRIORITY:
                boost = RELATIONSHIP_PRIORITY[rel_enum] / 1000  # Small boost
                confidence = min(1.0, confidence + boost)

        return confidence, matched_by


# Convenience functions for module-level access
_service: PeopleService | None = None


def get_people_service(notion_client: "NotionClient | None" = None) -> PeopleService:
    """Get or create a PeopleService instance."""
    global _service
    if _service is None or notion_client is not None:
        _service = PeopleService(notion_client)
    return _service


async def lookup_person(name: str) -> LookupResult:
    """Look up a person by name."""
    return await get_people_service().lookup(name)


async def lookup_or_create_person(
    name: str,
    relationship: Relationship | None = None,
    context: str | None = None,
) -> LookupResult:
    """Look up a person, creating them if not found."""
    return await get_people_service().lookup_or_create(name, relationship, context)


async def create_person(
    name: str,
    relationship: Relationship | None = None,
    context: str | None = None,
) -> Person:
    """Create a new person."""
    return await get_people_service().create(name, relationship, context)
