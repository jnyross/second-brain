#!/usr/bin/env python3
"""Comprehensive Telegram Bot Test Suite.

Tests all bot functionality via browser automation, logging results
for debugging and fixing issues.

Usage:
    python scripts/comprehensive_bot_test.py                    # Run all tests
    python scripts/comprehensive_bot_test.py --test task        # Run single test
    python scripts/comprehensive_bot_test.py --category commands # Run category
    python scripts/comprehensive_bot_test.py --list             # List all tests
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Test results directory
RESULTS_DIR = Path("/tmp/bot_test_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TestCase:
    """Individual test case definition."""

    id: str
    name: str
    category: str
    message: str
    expected_patterns: list[str]
    negative_patterns: list[str] = field(default_factory=list)
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    timeout: int = 60


@dataclass
class TestResult:
    """Result of a single test execution."""

    test_id: str
    test_name: str
    category: str
    passed: bool
    message_sent: str
    response_received: str
    expected_patterns: list[str]
    matched_patterns: list[str]
    missing_patterns: list[str]
    negative_matched: list[str]
    screenshot_path: str | None
    error: str | None
    timestamp: str
    duration_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# TEST DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

TESTS: list[TestCase] = [
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: COMMANDS
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="CMD-001",
        name="start_command",
        category="commands",
        message="/start",
        expected_patterns=[
            r"(welcome|hello|hi|hey|second brain)",
            r"(help|command|start)",
        ],
        negative_patterns=[r"(error|fail|exception)", r"added to inbox"],
        description="Bot should respond with welcome message",
    ),
    TestCase(
        id="CMD-002",
        name="help_command",
        category="commands",
        message="/help",
        expected_patterns=[
            r"(help|command|available)",
            r"(/today|/debrief|/status)",
        ],
        negative_patterns=[r"added to inbox", r"I'll track"],
        description="Bot should show help with available commands",
    ),
    TestCase(
        id="CMD-003",
        name="today_command",
        category="commands",
        message="/today",
        expected_patterns=[
            r"(today|schedule|calendar|nothing scheduled|due today)",
        ],
        negative_patterns=[r"added to inbox", r"error"],
        description="Bot should show today's schedule or 'nothing scheduled'",
        dependencies=["google_calendar"],
    ),
    TestCase(
        id="CMD-004",
        name="status_command",
        category="commands",
        message="/status",
        expected_patterns=[
            r"(status|progress|pending|task|inbox|clarification|no tasks)",
        ],
        negative_patterns=[r"added to inbox"],
        description="Bot should show task status overview",
        dependencies=["notion"],
    ),
    TestCase(
        id="CMD-005",
        name="debrief_command",
        category="commands",
        message="/debrief",
        expected_patterns=[
            r"(debrief|review|inbox|clarif|all clear|item|nothing)",
        ],
        negative_patterns=[r"error", r"exception"],
        description="Bot should start debrief or show 'all clear'",
        dependencies=["notion"],
    ),
    TestCase(
        id="CMD-006",
        name="setup_google_command",
        category="commands",
        message="/setup_google",
        expected_patterns=[
            r"(google|oauth|connect|already connected|click|link|credentials)",
        ],
        negative_patterns=[r"added to inbox"],
        description="Bot should show Google OAuth status/link",
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: TASK CREATION
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="TASK-001",
        name="simple_task",
        category="tasks",
        message="Buy groceries tomorrow",
        expected_patterns=[
            r"(got it|task|groceries|tomorrow|created|noted)",
        ],
        negative_patterns=[r"(offline|queue|locally)", r"clarification"],
        description="Simple task should be created in Notion",
        dependencies=["notion"],
    ),
    TestCase(
        id="TASK-002",
        name="task_with_time",
        category="tasks",
        message="Call dentist at 3pm",
        expected_patterns=[
            r"(got it|task|dentist|3|pm|created|noted)",
        ],
        negative_patterns=[r"offline", r"clarification"],
        description="Task with specific time should parse correctly",
        dependencies=["notion"],
    ),
    TestCase(
        id="TASK-003",
        name="task_with_person",
        category="tasks",
        message="Meet with Sarah about the project",
        expected_patterns=[
            r"(got it|task|sarah|meet|project|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Task mentioning a person should link them",
        dependencies=["notion"],
    ),
    TestCase(
        id="TASK-004",
        name="task_with_place",
        category="tasks",
        message="Dinner at Olive Garden on Friday",
        expected_patterns=[
            r"(got it|task|dinner|olive garden|friday|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Task with place should be recognized",
        dependencies=["notion"],
    ),
    TestCase(
        id="TASK-005",
        name="urgent_task",
        category="tasks",
        message="URGENT: Submit tax forms by end of day",
        expected_patterns=[
            r"(got it|urgent|tax|submit|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Urgent task should be marked high priority",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: AMBIGUOUS/LOW CONFIDENCE
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="AMB-001",
        name="ambiguous_message",
        category="ambiguous",
        message="hmm maybe later",
        expected_patterns=[
            r"(inbox|review|clarif|what|mean|understand|got it)",
        ],
        description="Vague message should go to inbox for review",
        dependencies=["notion"],
    ),
    TestCase(
        id="AMB-002",
        name="single_word",
        category="ambiguous",
        message="interesting",
        expected_patterns=[
            r"(inbox|review|clarif|noted|got it)",
        ],
        description="Single word should be flagged or acknowledged",
        dependencies=["notion"],
    ),
    TestCase(
        id="AMB-003",
        name="question_message",
        category="ambiguous",
        message="Should I go to the meeting?",
        expected_patterns=[
            r"(inbox|review|clarif|question|decide|got it)",
        ],
        description="Questions should be handled appropriately",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: REMINDERS
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="REM-001",
        name="reminder_tomorrow",
        category="reminders",
        message="Remind me to water plants tomorrow morning",
        expected_patterns=[
            r"(got it|remind|water|plants|tomorrow|morning|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Reminder should be created with correct time",
        dependencies=["notion"],
    ),
    TestCase(
        id="REM-002",
        name="reminder_specific_time",
        category="reminders",
        message="Remind me at 9am to take medication",
        expected_patterns=[
            r"(got it|remind|9|am|medication|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Reminder with specific time should parse correctly",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: PEOPLE MENTIONS
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="PPL-001",
        name="mention_person_task",
        category="people",
        message="Ask John about the report",
        expected_patterns=[
            r"(got it|task|john|report|ask|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Person name should be extracted and linked",
        dependencies=["notion"],
    ),
    TestCase(
        id="PPL-002",
        name="multiple_people",
        category="people",
        message="Schedule meeting with Alice and Bob",
        expected_patterns=[
            r"(got it|meeting|alice|bob|schedule|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Multiple people should be recognized",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: DATES AND TIMES
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="DATE-001",
        name="relative_date_tomorrow",
        category="dates",
        message="Finish report tomorrow",
        expected_patterns=[
            r"(got it|report|tomorrow|finish|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="'Tomorrow' should parse to correct date",
        dependencies=["notion"],
    ),
    TestCase(
        id="DATE-002",
        name="relative_date_next_week",
        category="dates",
        message="Review budget next Monday",
        expected_patterns=[
            r"(got it|review|budget|monday|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="'Next Monday' should parse correctly",
        dependencies=["notion"],
    ),
    TestCase(
        id="DATE-003",
        name="specific_date",
        category="dates",
        message="Conference on January 25th",
        expected_patterns=[
            r"(got it|conference|january|25|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Specific date should parse correctly",
        dependencies=["notion"],
    ),
    TestCase(
        id="DATE-004",
        name="time_with_timezone",
        category="dates",
        message="Call at 2pm EST",
        expected_patterns=[
            r"(got it|call|2|pm|est|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Time with timezone should be handled",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: PLACES
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="PLC-001",
        name="task_with_restaurant",
        category="places",
        message="Lunch at Chipotle tomorrow",
        expected_patterns=[
            r"(got it|lunch|chipotle|tomorrow|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Restaurant name should be recognized as place",
        dependencies=["notion"],
    ),
    TestCase(
        id="PLC-002",
        name="task_with_office",
        category="places",
        message="Meeting at the downtown office at 10am",
        expected_patterns=[
            r"(got it|meeting|downtown|office|10|am|created|noted)",
        ],
        negative_patterns=[r"offline"],
        description="Office location should be recognized",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: EMAIL QUERIES
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="EMAIL-001",
        name="email_status_query",
        category="email",
        message="Do I have any important emails?",
        expected_patterns=[
            r"(email|inbox|message|important|no email|gmail|connect)",
        ],
        description="Email query should check Gmail or suggest setup",
        dependencies=["gmail"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: NOTION CONNECTIVITY
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="NOTION-001",
        name="notion_connectivity",
        category="notion",
        message="Test task for Notion sync check",
        expected_patterns=[
            r"(got it|task|created|noted)",
        ],
        negative_patterns=[
            r"(offline|queue|locally|unavailable|connection)",
        ],
        description="Task creation should sync to Notion, not queue locally",
        dependencies=["notion"],
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # CATEGORY: EDGE CASES
    # ═══════════════════════════════════════════════════════════════════════
    TestCase(
        id="EDGE-001",
        name="empty_after_command",
        category="edge_cases",
        message="/help extra text here",
        expected_patterns=[
            r"(help|command|available)",
        ],
        negative_patterns=[r"added to inbox"],
        description="Command with extra text should still work",
    ),
    TestCase(
        id="EDGE-002",
        name="unicode_message",
        category="edge_cases",
        message="Meet café owner José tomorrow 🎉",
        expected_patterns=[
            r"(got it|meet|café|josé|tomorrow|created|noted)",
        ],
        description="Unicode characters should be handled",
        dependencies=["notion"],
    ),
    TestCase(
        id="EDGE-003",
        name="long_message",
        category="edge_cases",
        message="I need to prepare for the quarterly business review meeting where we will discuss the financial projections, market analysis, competitor landscape, product roadmap updates, and team capacity planning for the next fiscal year",
        expected_patterns=[
            r"(got it|task|meeting|prepare|review|created|noted|inbox)",
        ],
        description="Long messages should be handled without truncation issues",
        dependencies=["notion"],
    ),
    TestCase(
        id="EDGE-004",
        name="special_characters",
        category="edge_cases",
        message="Fix bug #123 in app v2.0 (critical)",
        expected_patterns=[
            r"(got it|fix|bug|123|critical|created|noted)",
        ],
        description="Special characters (#, parentheses) should be handled",
        dependencies=["notion"],
    ),
]

# Group tests by category for reporting
TEST_CATEGORIES = {
    "commands": "Command Handlers",
    "tasks": "Task Creation",
    "ambiguous": "Ambiguous/Low Confidence",
    "reminders": "Reminders",
    "people": "People Mentions",
    "dates": "Dates and Times",
    "places": "Places",
    "email": "Email Queries",
    "notion": "Notion Connectivity",
    "edge_cases": "Edge Cases",
}


def run_agent_browser_command(message: str, timeout: int = 60) -> tuple[str, str | None]:
    """Send message via agent-browser and capture response.

    Returns:
        Tuple of (response_text, screenshot_path)
    """
    timestamp = datetime.now().strftime("%H%M%S")
    screenshot_path = str(RESULTS_DIR / f"test_{timestamp}.png")

    # Escape message for shell
    escaped_message = message.replace('"', '\\"').replace("'", "\\'")

    cmd = [
        "agent-browser",
        "--session", "telegram",
        f'Type in the message input field: "{escaped_message}" and press Enter. '
        f'Wait for bot response (up to {timeout} seconds). '
        f'Return the EXACT text of the bot\'s response message(s). '
        f'If no response after {timeout} seconds, say "NO_RESPONSE".',
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        response = result.stdout.strip()

        # Try to take screenshot
        try:
            screenshot_cmd = [
                "agent-browser",
                "--session", "telegram",
                f"Take a screenshot and save to {screenshot_path}",
            ]
            subprocess.run(screenshot_cmd, capture_output=True, timeout=15)
        except Exception:
            screenshot_path = None

        return response, screenshot_path

    except subprocess.TimeoutExpired:
        return "TIMEOUT", None
    except Exception as e:
        return f"ERROR: {e}", None


def check_patterns(text: str, patterns: list[str]) -> tuple[list[str], list[str]]:
    """Check which patterns match in text.

    Returns:
        Tuple of (matched_patterns, missing_patterns)
    """
    text_lower = text.lower()
    matched = []
    missing = []

    for pattern in patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            matched.append(pattern)
        else:
            missing.append(pattern)

    return matched, missing


def run_test(test: TestCase) -> TestResult:
    """Execute a single test case."""
    start_time = datetime.now()

    print(f"\n  Running: [{test.id}] {test.name}...")
    print(f"    Message: {test.message[:50]}{'...' if len(test.message) > 50 else ''}")

    # Send message and get response
    response, screenshot = run_agent_browser_command(test.message, test.timeout)

    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    # Check expected patterns
    matched, missing = check_patterns(response, test.expected_patterns)

    # Check negative patterns (should NOT match)
    neg_matched, _ = check_patterns(response, test.negative_patterns)

    # Determine pass/fail
    passed = len(missing) == 0 and len(neg_matched) == 0

    # Check for obvious failures
    if "NO_RESPONSE" in response or "TIMEOUT" in response:
        passed = False

    if "Log in to Telegram" in response or "QR Code" in response:
        passed = False
        response = "SESSION_EXPIRED: Need to re-login"

    result = TestResult(
        test_id=test.id,
        test_name=test.name,
        category=test.category,
        passed=passed,
        message_sent=test.message,
        response_received=response[:500] if response else "",
        expected_patterns=test.expected_patterns,
        matched_patterns=matched,
        missing_patterns=missing,
        negative_matched=neg_matched,
        screenshot_path=screenshot,
        error=None if passed else f"Missing: {missing}, Negative matched: {neg_matched}",
        timestamp=start_time.isoformat(),
        duration_ms=duration_ms,
    )

    status = "PASS" if passed else "FAIL"
    print(f"    [{status}] Response: {response[:80]}{'...' if len(response) > 80 else ''}")

    return result


def run_tests(
    tests: list[TestCase],
    stop_on_fail: bool = False,
) -> list[TestResult]:
    """Run multiple tests and collect results."""
    results = []

    for test in tests:
        result = run_test(test)
        results.append(result)

        if not result.passed and stop_on_fail:
            print("\n  Stopping on first failure (--stop-on-fail)")
            break

        # Brief pause between tests
        import time
        time.sleep(2)

    return results


def generate_report(results: list[TestResult]) -> dict[str, Any]:
    """Generate comprehensive test report."""
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    # Group by category
    by_category: dict[str, list[TestResult]] = {}
    for r in results:
        if r.category not in by_category:
            by_category[r.category] = []
        by_category[r.category].append(r)

    report = {
        "summary": {
            "total": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "pass_rate": f"{100 * len(passed) / len(results):.1f}%" if results else "N/A",
            "timestamp": datetime.now().isoformat(),
        },
        "by_category": {},
        "failures": [],
        "all_results": [],
    }

    for cat, cat_results in by_category.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        report["by_category"][cat] = {
            "name": TEST_CATEGORIES.get(cat, cat),
            "total": len(cat_results),
            "passed": cat_passed,
            "failed": len(cat_results) - cat_passed,
        }

    for r in failed:
        report["failures"].append({
            "test_id": r.test_id,
            "test_name": r.test_name,
            "category": r.category,
            "message_sent": r.message_sent,
            "response": r.response_received[:200],
            "missing_patterns": r.missing_patterns,
            "negative_matched": r.negative_matched,
            "error": r.error,
        })

    for r in results:
        report["all_results"].append({
            "test_id": r.test_id,
            "test_name": r.test_name,
            "category": r.category,
            "passed": r.passed,
            "duration_ms": r.duration_ms,
            "response_preview": r.response_received[:100],
        })

    return report


def print_report(report: dict[str, Any]) -> None:
    """Print formatted test report."""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE BOT TEST REPORT")
    print("=" * 70)

    s = report["summary"]
    print(f"\nSUMMARY: {s['passed']}/{s['total']} passed ({s['pass_rate']})")
    print(f"Timestamp: {s['timestamp']}")

    print("\nRESULTS BY CATEGORY:")
    print("-" * 50)
    for cat, data in report["by_category"].items():
        status = "✓" if data["failed"] == 0 else "✗"
        print(f"  {status} {data['name']}: {data['passed']}/{data['total']}")

    if report["failures"]:
        print("\n" + "=" * 70)
        print("FAILURES (need fixing):")
        print("=" * 70)
        for f in report["failures"]:
            print(f"\n[{f['test_id']}] {f['test_name']}")
            print(f"  Category: {f['category']}")
            print(f"  Message: {f['message_sent'][:60]}...")
            print(f"  Response: {f['response'][:100]}...")
            if f["missing_patterns"]:
                print(f"  Missing patterns: {f['missing_patterns']}")
            if f["negative_matched"]:
                print(f"  Unwanted patterns matched: {f['negative_matched']}")

    print("\n" + "=" * 70)


def save_report(report: dict[str, Any], path: Path) -> None:
    """Save report to JSON file."""
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nDetailed report saved to: {path}")


def list_tests() -> None:
    """List all available tests."""
    print("\nAvailable Tests:")
    print("=" * 70)

    for cat, cat_name in TEST_CATEGORIES.items():
        cat_tests = [t for t in TESTS if t.category == cat]
        if cat_tests:
            print(f"\n{cat_name} ({cat}):")
            for t in cat_tests:
                deps = f" [requires: {', '.join(t.dependencies)}]" if t.dependencies else ""
                print(f"  [{t.id}] {t.name}{deps}")
                print(f"        {t.description}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Comprehensive Bot Test Suite")
    parser.add_argument("--test", help="Run specific test by ID or name")
    parser.add_argument("--category", help="Run tests in specific category")
    parser.add_argument("--list", action="store_true", help="List all available tests")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop on first failure")
    parser.add_argument("--output", default=str(RESULTS_DIR / "test_report.json"),
                       help="Output path for JSON report")
    args = parser.parse_args()

    if args.list:
        list_tests()
        return 0

    # Filter tests
    tests_to_run = TESTS

    if args.test:
        tests_to_run = [
            t for t in TESTS
            if t.id.lower() == args.test.lower() or t.name.lower() == args.test.lower()
        ]
        if not tests_to_run:
            print(f"Unknown test: {args.test}")
            print("Use --list to see available tests")
            return 1

    if args.category:
        tests_to_run = [t for t in tests_to_run if t.category == args.category]
        if not tests_to_run:
            print(f"No tests in category: {args.category}")
            print(f"Available categories: {', '.join(TEST_CATEGORIES.keys())}")
            return 1

    print(f"\nRunning {len(tests_to_run)} tests...")
    print("=" * 70)

    # Run tests
    results = run_tests(tests_to_run, stop_on_fail=args.stop_on_fail)

    # Generate and display report
    report = generate_report(results)
    print_report(report)

    # Save detailed report
    save_report(report, Path(args.output))

    # Return exit code based on failures
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
