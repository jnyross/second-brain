from datetime import datetime

from assistant.services.llm_parser import LLMIntentParser
from assistant.services.parser import ParsedIntent


class DummyParser:
    def __init__(self, result: ParsedIntent) -> None:
        self.result = result
        self.calls: list[str] = []

    def parse(self, text: str) -> ParsedIntent:
        self.calls.append(text)
        return self.result


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[tuple[str, dict, dict]] = []

    def post(self, url: str, params: dict, json: dict) -> FakeResponse:
        self.requests.append((url, params, json))
        return FakeResponse(self.payload)


def test_llm_parser_falls_back_without_key():
    base_result = ParsedIntent(
        intent_type="task",
        title="Buy milk",
        confidence=55,
        raw_text="Buy milk",
    )
    dummy = DummyParser(base_result)
    parser = LLMIntentParser(api_key="", base_parser=dummy, client=FakeClient({}))

    result = parser.parse("Buy milk")

    assert result is base_result
    assert dummy.calls == ["Buy milk"]


def test_llm_parser_parses_valid_response():
    base_result = ParsedIntent(
        intent_type="note",
        title="Fallback",
        confidence=40,
        raw_text="Schedule flight",
    )
    dummy = DummyParser(base_result)
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "{\"intent_type\": \"task\", "
                                "\"title\": \"Book flight\", "
                                "\"confidence\": 92, "
                                "\"due_date\": \"2026-01-15T09:00:00-08:00\", "
                                "\"due_timezone\": \"America/Los_Angeles\", "
                                "\"people\": [\"Alex\"], "
                                "\"places\": [\"LAX\"]}"
                            )
                        }
                    ]
                }
            }
        ]
    }
    parser = LLMIntentParser(api_key="test-key", base_parser=dummy, client=FakeClient(payload))

    result = parser.parse("Schedule flight")

    assert result.intent_type == "task"
    assert result.title == "Book flight"
    assert result.confidence == 92
    assert result.people == ["Alex"]
    assert result.places == ["LAX"]
    assert result.due_date == datetime.fromisoformat("2026-01-15T09:00:00-08:00")
    assert result.due_timezone == "America/Los_Angeles"


def test_llm_parser_falls_back_on_invalid_payload():
    base_result = ParsedIntent(
        intent_type="task",
        title="Call mom",
        confidence=70,
        raw_text="Call mom",
    )
    dummy = DummyParser(base_result)
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "not json"},
                    ]
                }
            }
        ]
    }
    parser = LLMIntentParser(api_key="test-key", base_parser=dummy, client=FakeClient(payload))

    result = parser.parse("Call mom")

    assert result is base_result
    assert dummy.calls == ["Call mom"]
