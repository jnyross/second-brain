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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NOTION_KEY = os.getenv("NOTION_API_KEY")
TASKS_DB = os.getenv("NOTION_TASKS_DB_ID")
INBOX_DB = os.getenv("NOTION_INBOX_DB_ID")
LOG_DB = os.getenv("NOTION_LOG_DB_ID")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
openai_client = openai.OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

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
                      places: list[str] | None = None, people: list[str] | None = None) -> str | None:
    if not NOTION_KEY or not TASKS_DB:
        return None
    
    notes_parts = []
    if places:
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
        "- Voice messages work too!\n\n"
        "I'll understand and save to Notion."
    )

@dp.message(Command("today"))
async def cmd_today(message: Message):
    await message.answer("Today's tasks - coming soon!")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    await message.answer("Status check - coming soon!")

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
        task_id = await create_task(
            parsed.get("title", transcript),
            parsed.get("due_date"),
            parsed.get("confidence", 85),
            parsed.get("places"),
            parsed.get("people"),
        )
        await log_action(f"Task: {parsed.get('title', transcript)[:50]}")
        
        response = f"I heard: \"{transcript}\"\n\n"
        response += f"Created: **{parsed.get('title')}**"
        if parsed.get("due_date"):
            response += f"\nDue: {parsed.get('due_date')}"
        if parsed.get("places"):
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
        task_id = await create_task(
            parsed.get("title", text),
            parsed.get("due_date"),
            parsed.get("confidence", 85),
            parsed.get("places"),
            parsed.get("people"),
        )
        await log_action(f"Task: {parsed.get('title', text)[:50]}")
        
        response = f"Got it. **{parsed.get('title')}**"
        if parsed.get("due_date"):
            response += f"\nDue: {parsed.get('due_date')}"
        if parsed.get("places"):
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
    logger.info("=" * 50)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
