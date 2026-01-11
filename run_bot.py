#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import openai

sys.path.insert(0, str(Path(__file__).parent / "src"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_KEY = os.getenv("NOTION_API_KEY")
TASKS_DB = os.getenv("NOTION_TASKS_DB_ID")
INBOX_DB = os.getenv("NOTION_INBOX_DB_ID")
LOG_DB = os.getenv("NOTION_LOG_DB_ID")
PLACES_DB = os.getenv("NOTION_PLACES_DB_ID")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
USER_HOME_ADDRESS = os.getenv("USER_HOME_ADDRESS", "")

if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
openai_client = openai.OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

maps_client = None
drive_client = None

try:
    from assistant.google.maps import MapsClient, PlaceDetails
    from assistant.google.drive import DriveClient
    from assistant.google.auth import google_auth
    
    if GOOGLE_MAPS_KEY:
        maps_client = MapsClient(api_key=GOOGLE_MAPS_KEY)
        logger.info("Google Maps client initialized")
    
    drive_client = DriveClient()
except ImportError as e:
    logger.warning(f"Google integration not available: {e}")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

PARSE_PROMPT = """You are a personal assistant that parses user messages into structured tasks.

Given a user message, extract:
1. title: A clean, actionable task title (fix any transcription errors if obvious)
2. due_date: ISO format datetime if mentioned, null otherwise
3. people: List of people mentioned
4. places: List of places mentioned  
5. confidence: 0-100 how confident you are this is a clear, actionable task
6. needs_clarification: true if the message is unclear or you're unsure

Rules:
- Fix obvious speech-to-text errors (e.g., "Bye the kids" → "Buy the kids")
- "tomorrow" = next day at 9am, "Friday 3pm" = next Friday at 15:00
- Confidence < 80 means it should go to inbox for review
- Keep titles concise but complete

Respond ONLY with valid JSON, no markdown, no explanation.

Example input: "Bye the kids a present when I'm in san Francisco"
Example output: {"title": "Buy the kids a present in San Francisco", "due_date": null, "people": [], "places": ["San Francisco"], "confidence": 85, "needs_clarification": false}

Example input: "uhh that thing for the project"
Example output: {"title": "that thing for the project", "due_date": null, "people": [], "places": [], "confidence": 30, "needs_clarification": true}
"""

async def parse_with_ai(text: str) -> dict:
    if not openai_client:
        return {"title": text, "confidence": 50, "needs_clarification": True}
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PARSE_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=500,
        )
        result = json.loads(response.choices[0].message.content)
        logger.info(f"AI parsed: {result}")
        return result
    except Exception as e:
        logger.error(f"AI parsing failed: {e}")
        return {"title": text, "confidence": 50, "needs_clarification": True}


async def enrich_places(places: list[str]) -> list[dict]:
    if not maps_client or not places:
        return []
    
    enriched = []
    for place_name in places:
        try:
            place = await maps_client.enrich_place(place_name)
            if place:
                enriched.append({
                    "name": place.name,
                    "address": place.address,
                    "lat": place.lat,
                    "lng": place.lng,
                    "place_id": place.place_id,
                    "place_type": place.place_type,
                })
        except Exception as e:
            logger.error(f"Place enrichment failed for '{place_name}': {e}")
    return enriched


async def get_travel_time(destination: str) -> str | None:
    if not maps_client or not USER_HOME_ADDRESS:
        return None
    
    try:
        travel = await maps_client.get_travel_time(USER_HOME_ADDRESS, destination)
        if travel:
            return travel.format_duration()
    except Exception as e:
        logger.error(f"Travel time calculation failed: {e}")
    return None


async def create_place_in_notion(place: dict) -> str | None:
    if not NOTION_KEY or not PLACES_DB:
        return None
    
    props = {
        "name": {"title": [{"text": {"content": place["name"]}}]},
        "address": {"rich_text": [{"text": {"content": place.get("address", "")}}]},
    }
    
    if place.get("lat") and place.get("lng"):
        props["coordinates"] = {"rich_text": [{"text": {"content": f"{place['lat']},{place['lng']}"}}]}
    if place.get("place_id"):
        props["google_place_id"] = {"rich_text": [{"text": {"content": place["place_id"]}}]}
    if place.get("place_type"):
        props["place_type"] = {"select": {"name": place["place_type"]}}
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.notion.com/v1/pages",
                headers=NOTION_HEADERS,
                json={"parent": {"database_id": PLACES_DB}, "properties": props},
                timeout=30,
            )
            if r.status_code == 200:
                logger.info(f"Created place: {place['name']}")
                return r.json()["id"]
            logger.error(f"Notion error creating place: {r.text}")
            return None
    except Exception as e:
        logger.error(f"Notion request failed for place: {e}")
        return None

async def transcribe_voice(file_path: str) -> str | None:
    if not openai_client:
        return None
    try:
        with open(file_path, "rb") as f:
            transcript = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en",
            )
        return transcript.text
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return None

async def create_task(title: str, due_date: str | None = None, confidence: int = 100, 
                      places: list[str] | None = None, people: list[str] | None = None,
                      enriched_places: list[dict] | None = None, travel_time: str | None = None) -> str | None:
    if not NOTION_KEY or not TASKS_DB:
        return None
    
    notes_parts = []
    if enriched_places:
        for ep in enriched_places:
            notes_parts.append(f"Location: {ep['name']}")
            if ep.get("address"):
                notes_parts.append(f"  Address: {ep['address']}")
        if travel_time:
            notes_parts.append(f"  Travel: {travel_time} from home")
    elif places:
        notes_parts.append(f"Location: {', '.join(places)}")
    if people:
        notes_parts.append(f"People: {', '.join(people)}")
    notes = "\n".join(notes_parts) if notes_parts else None
        
    props = {
        "title": {"title": [{"text": {"content": title}}]},
        "status": {"select": {"name": "todo"}},
        "priority": {"select": {"name": "medium"}},
        "confidence": {"number": confidence},
    }
    if due_date:
        props["due_date"] = {"date": {"start": due_date}}
    if notes:
        props["notes"] = {"rich_text": [{"text": {"content": notes}}]}
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.notion.com/v1/pages",
                headers=NOTION_HEADERS,
                json={"parent": {"database_id": TASKS_DB}, "properties": props},
                timeout=30,
            )
            if r.status_code == 200:
                logger.info(f"Created task: {title}")
                return r.json()["id"]
            logger.error(f"Notion error: {r.text}")
            return None
    except Exception as e:
        logger.error(f"Notion request failed: {e}")
        return None

async def create_inbox_item(raw_input: str, interpretation: str, confidence: int) -> str | None:
    if not NOTION_KEY or not INBOX_DB:
        return None
    
    props = {
        "raw_input": {"title": [{"text": {"content": raw_input}}]},
        "confidence": {"number": confidence},
        "needs_clarification": {"checkbox": True},
        "processed": {"checkbox": False},
    }
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.notion.com/v1/pages",
                headers=NOTION_HEADERS,
                json={"parent": {"database_id": INBOX_DB}, "properties": props},
                timeout=30,
            )
            if r.status_code == 200:
                logger.info(f"Created inbox item: {raw_input[:50]}")
                return r.json()["id"]
            logger.error(f"Notion error: {r.text}")
            return None
    except Exception as e:
        logger.error(f"Notion request failed: {e}")
        return None

async def log_action(action: str) -> None:
    if not NOTION_KEY or not LOG_DB:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.notion.com/v1/pages",
                headers=NOTION_HEADERS,
                json={
                    "parent": {"database_id": LOG_DB},
                    "properties": {
                        "action_taken": {"title": [{"text": {"content": action}}]},
                        "timestamp": {"date": {"start": datetime.utcnow().isoformat()}},
                        "action_type": {"select": {"name": "create"}},
                    }
                },
                timeout=30,
            )
    except Exception as e:
        logger.error(f"Log failed: {e}")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Hello! I'm your Second Brain assistant.\n\n"
        "Send me anything - text or voice - and I'll organize it.\n\n"
        "I use AI to understand what you mean, even if you mumble!\n\n"
        "Commands: /today /status /help"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "**Second Brain**\n\n"
        "Send me messages like:\n"
        "- 'Buy milk tomorrow'\n"
        "- 'Meeting with Sarah Friday 3pm'\n"
        "- 'Meet Dave at Blue Bottle Coffee'\n"
        "- Voice messages work too!\n\n"
        "**Commands:**\n"
        "/today - Today's tasks\n"
        "/research TOPIC - Create research doc\n"
        "/meeting_notes TITLE - Create meeting notes\n"
        "/compare TITLE: opt1, opt2 - Comparison sheet\n"
        "/setup_google - Connect Google services"
    )

@dp.message(Command("today"))
async def cmd_today(message: Message):
    await message.answer("Today's tasks - coming soon!")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    await message.answer("Status check - coming soon!")

@dp.message(Command("setup_google"))
async def cmd_setup_google(message: Message):
    try:
        if google_auth.load_saved_credentials():
            await message.answer("Google already authenticated!")
            return
        
        auth_url = google_auth.get_auth_url()
        if auth_url:
            await message.answer(
                f"Click to authenticate Google:\n\n{auth_url}\n\n"
                "After authenticating, send me the code with:\n"
                "/google_code YOUR_CODE"
            )
        else:
            await message.answer("Google credentials file not found. Add google_credentials.json to the project.")
    except Exception as e:
        await message.answer(f"Setup failed: {e}")

@dp.message(Command("google_code"))
async def cmd_google_code(message: Message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Usage: /google_code YOUR_CODE")
            return
        
        code = parts[1].strip()
        if google_auth.complete_auth_with_code(code):
            await message.answer("Google authenticated successfully!")
        else:
            await message.answer("Authentication failed. Try /setup_google again.")
    except Exception as e:
        await message.answer(f"Authentication failed: {e}")

@dp.message(Command("research"))
async def cmd_research(message: Message):
    if not drive_client:
        await message.answer("Google Drive not configured.")
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /research TOPIC\n\nExample: /research best CRM for small business")
        return
    
    topic = parts[1].strip()
    processing_msg = await message.answer(f"Creating research document for: {topic}...")
    
    try:
        doc = await drive_client.create_research_document(topic)
        await processing_msg.edit_text(
            f"Created research document:\n\n"
            f"**{doc.name}**\n\n"
            f"[Open in Google Docs]({doc.web_view_link})"
        )
    except Exception as e:
        await processing_msg.edit_text(f"Failed to create document: {e}")

@dp.message(Command("meeting_notes"))
async def cmd_meeting_notes(message: Message):
    if not drive_client:
        await message.answer("Google Drive not configured.")
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /meeting_notes TITLE\n\nExample: /meeting_notes Call with Sarah about Project X")
        return
    
    title = parts[1].strip()
    processing_msg = await message.answer(f"Creating meeting notes: {title}...")
    
    try:
        doc = await drive_client.create_meeting_notes(title)
        await processing_msg.edit_text(
            f"Created meeting notes:\n\n"
            f"**{doc.name}**\n\n"
            f"[Open in Google Docs]({doc.web_view_link})"
        )
    except Exception as e:
        await processing_msg.edit_text(f"Failed to create document: {e}")

@dp.message(Command("compare"))
async def cmd_compare(message: Message):
    if not drive_client:
        await message.answer("Google Drive not configured.")
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Usage: /compare TITLE: option1, option2, option3\n\n"
            "Example: /compare CRM Tools: HubSpot, Salesforce, Pipedrive"
        )
        return
    
    content = parts[1].strip()
    if ":" not in content:
        await message.answer("Format: /compare TITLE: option1, option2, ...")
        return
    
    title, options_str = content.split(":", 1)
    options = [o.strip() for o in options_str.split(",") if o.strip()]
    
    if len(options) < 2:
        await message.answer("Please provide at least 2 options to compare.")
        return
    
    processing_msg = await message.answer(f"Creating comparison sheet for: {title}...")
    
    try:
        sheet = await drive_client.create_comparison_sheet(title.strip(), options)
        await processing_msg.edit_text(
            f"Created comparison sheet:\n\n"
            f"**{sheet.name}**\n\n"
            f"[Open in Google Sheets]({sheet.web_view_link})"
        )
    except Exception as e:
        await processing_msg.edit_text(f"Failed to create sheet: {e}")

@dp.message(F.voice)
async def handle_voice(message: Message):
    if not openai_client:
        await message.answer("Voice not configured. Please send text.")
        return
    
    processing_msg = await message.answer("Listening...")
    
    file = await bot.get_file(message.voice.file_id)
    file_path = f"/tmp/voice_{message.message_id}.ogg"
    await bot.download_file(file.file_path, file_path)
    
    transcript = await transcribe_voice(file_path)
    os.remove(file_path)
    
    if not transcript:
        await processing_msg.edit_text("Couldn't hear that. Please try again.")
        return
    
    logger.info(f"Transcribed: {transcript}")
    await processing_msg.edit_text(f"I heard: \"{transcript}\"\n\nProcessing...")
    
    parsed = await parse_with_ai(transcript)
    
    if parsed.get("needs_clarification") or parsed.get("confidence", 0) < 80:
        await create_inbox_item(transcript, parsed.get("title", transcript), parsed.get("confidence", 50))
        await log_action(f"Inbox: {transcript[:50]}")
        await processing_msg.edit_text(
            f"I heard: \"{transcript}\"\n\n"
            f"I'm not sure what you meant. Added to inbox for review.\n\n"
            f"_Confidence: {parsed.get('confidence', 50)}%_"
        )
    else:
        enriched_places = await enrich_places(parsed.get("places", []))
        travel_time = None
        if enriched_places:
            for ep in enriched_places:
                await create_place_in_notion(ep)
            if enriched_places[0].get("address"):
                travel_time = await get_travel_time(enriched_places[0]["address"])
        
        task_id = await create_task(
            parsed.get("title", transcript),
            parsed.get("due_date"),
            parsed.get("confidence", 85),
            parsed.get("places"),
            parsed.get("people"),
            enriched_places,
            travel_time,
        )
        await log_action(f"Task: {parsed.get('title', transcript)[:50]}")
        
        response = f"I heard: \"{transcript}\"\n\n"
        response += f"Created: **{parsed.get('title')}**"
        if parsed.get("due_date"):
            response += f"\nDue: {parsed.get('due_date')}"
        if enriched_places:
            ep = enriched_places[0]
            response += f"\nLocation: {ep['name']}"
            if ep.get("address") and ep["address"] != ep["name"]:
                response += f"\n  _{ep['address']}_"
            if travel_time:
                response += f"\n  Travel: {travel_time}"
        elif parsed.get("places"):
            response += f"\nLocation: {', '.join(parsed.get('places'))}"
        if parsed.get("people"):
            response += f"\nPeople: {', '.join(parsed.get('people'))}"
        response += f"\n\n_Saved to Notion_"
        await processing_msg.edit_text(response)

@dp.message(F.text)
async def handle_text(message: Message):
    text = message.text
    logger.info(f"Received: {text}")
    
    parsed = await parse_with_ai(text)
    
    if parsed.get("needs_clarification") or parsed.get("confidence", 0) < 80:
        await create_inbox_item(text, parsed.get("title", text), parsed.get("confidence", 50))
        await log_action(f"Inbox: {text[:50]}")
        await message.answer(
            f"Got it, but I'm not sure what you mean.\n\n"
            f"Added to inbox for review.\n\n"
            f"_Confidence: {parsed.get('confidence', 50)}%_"
        )
    else:
        enriched_places = await enrich_places(parsed.get("places", []))
        travel_time = None
        if enriched_places:
            for ep in enriched_places:
                await create_place_in_notion(ep)
            if enriched_places[0].get("address"):
                travel_time = await get_travel_time(enriched_places[0]["address"])
        
        task_id = await create_task(
            parsed.get("title", text),
            parsed.get("due_date"),
            parsed.get("confidence", 85),
            parsed.get("places"),
            parsed.get("people"),
            enriched_places,
            travel_time,
        )
        await log_action(f"Task: {parsed.get('title', text)[:50]}")
        
        response = f"Got it. **{parsed.get('title')}**"
        if parsed.get("due_date"):
            response += f"\nDue: {parsed.get('due_date')}"
        if enriched_places:
            ep = enriched_places[0]
            response += f"\nLocation: {ep['name']}"
            if ep.get("address") and ep["address"] != ep["name"]:
                response += f"\n  _{ep['address']}_"
            if travel_time:
                response += f"\n  Travel: {travel_time}"
        elif parsed.get("places"):
            response += f"\nLocation: {', '.join(parsed.get('places'))}"
        if parsed.get("people"):
            response += f"\nPeople: {', '.join(parsed.get('people'))}"
        response += f"\n\n_Saved to Notion_"
        await message.answer(response)

async def main():
    logger.info("=" * 50)
    logger.info("Starting Second Brain bot (with AI parsing)...")
    logger.info(f"Notion: {'OK' if NOTION_KEY else 'MISSING'}")
    logger.info(f"OpenAI: {'OK' if OPENAI_KEY else 'MISSING'}")
    logger.info(f"Google Maps: {'OK' if maps_client else 'NOT CONFIGURED'}")
    logger.info(f"Google Drive: {'OK' if drive_client else 'NOT CONFIGURED'}")
    logger.info("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
