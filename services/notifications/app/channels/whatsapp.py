"""WhatsApp bot with state-machine conversation flow for reservations."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_MINUTES = 60


class BotState(StrEnum):
    INIT = "init"
    COLLECT_DATE = "collect_date"
    COLLECT_TIME = "collect_time"
    COLLECT_SIZE = "collect_size"
    COLLECT_NAME = "collect_name"
    COLLECT_SPECIAL = "collect_special"
    CONFIRM = "confirm"
    SUGGEST_ALTERNATIVES = "suggest_alternatives"
    CANCEL = "cancel"
    CANCEL_CONFIRM = "cancel_confirm"
    MODIFY_SELECT = "modify_select"
    MODIFY_DATE = "modify_date"
    MODIFY_TIME = "modify_time"
    MODIFY_SIZE = "modify_size"
    DONE = "done"


@dataclass
class ConversationSession:
    phone: str
    restaurant_slug: str
    state: BotState = BotState.INIT
    data: dict[str, Any] = field(default_factory=dict)
    last_active: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_expired(self) -> bool:
        return (datetime.utcnow() - self.last_active) > timedelta(minutes=SESSION_TIMEOUT_MINUTES)

    def touch(self) -> None:
        self.last_active = datetime.utcnow()


@dataclass
class NLPResult:
    intent: str
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


# In-memory session store (use Redis in production for multi-instance)
_sessions: dict[str, ConversationSession] = {}


def get_or_create_session(phone: str, restaurant_slug: str) -> ConversationSession:
    key = f"{phone}:{restaurant_slug}"
    session = _sessions.get(key)
    if session and not session.is_expired:
        session.touch()
        return session
    session = ConversationSession(phone=phone, restaurant_slug=restaurant_slug)
    _sessions[key] = session
    return session


def clear_session(phone: str, restaurant_slug: str) -> None:
    _sessions.pop(f"{phone}:{restaurant_slug}", None)


async def analyze_message(text: str) -> NLPResult:
    """Analyze user message with OpenAI, fall back to regex."""
    if settings.OPENAI_API_KEY:
        try:
            return await _analyze_with_openai(text)
        except Exception as exc:
            logger.warning("OpenAI analysis failed, falling back to regex: %s", exc)
    return _analyze_with_regex(text)


async def _analyze_with_openai(text: str) -> NLPResult:
    import httpx

    system_prompt = (
        "Du bist ein NLP-Analyser fuer einen Restaurant-Reservierungsbot. "
        "Extrahiere intent und entities aus der Nachricht. "
        "Antworte NUR mit JSON: {\"intent\": \"...\", \"entities\": {...}, \"confidence\": 0.0-1.0}. "
        "Moegliche intents: reserve, cancel, modify, check_availability, greeting, help, yes, no, unknown. "
        "Moegliche entities: date (YYYY-MM-DD), time (HH:MM), party_size (int), name (str), "
        "confirmation_code (str), special_requests (str)."
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": settings.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.1,
                "max_tokens": 200,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return NLPResult(
            intent=parsed.get("intent", "unknown"),
            entities=parsed.get("entities", {}),
            confidence=parsed.get("confidence", 0.5),
        )


def _analyze_with_regex(text: str) -> NLPResult:
    text_lower = text.lower().strip()
    entities: dict[str, Any] = {}

    # Date patterns
    date_match = re.search(r"(\d{1,2})[./](\d{1,2})[./]?(\d{2,4})?", text)
    if date_match:
        day, month = int(date_match.group(1)), int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else datetime.utcnow().year
        if year < 100:
            year += 2000
        try:
            entities["date"] = f"{year}-{month:02d}-{day:02d}"
        except ValueError:
            pass

    # Time patterns
    time_match = re.search(r"(\d{1,2})[:\.](\d{2})\s*(?:uhr)?", text_lower)
    if time_match:
        entities["time"] = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"

    # Party size
    size_match = re.search(r"(\d+)\s*(?:person|pers|leute|gaeste|platz|plaetze)", text_lower)
    if size_match:
        entities["party_size"] = int(size_match.group(1))

    # Confirmation code
    code_match = re.search(r"[A-Z0-9]{6,8}", text)
    if code_match:
        entities["confirmation_code"] = code_match.group(0)

    # Intent detection
    if any(w in text_lower for w in ("reservier", "tisch", "buchen", "platz")):
        intent = "reserve"
    elif any(w in text_lower for w in ("stornieren", "absagen", "cancel", "storno")):
        intent = "cancel"
    elif any(w in text_lower for w in ("aendern", "verschieben", "umbuchen", "modify")):
        intent = "modify"
    elif any(w in text_lower for w in ("frei", "verfuegbar", "availability", "offen")):
        intent = "check_availability"
    elif any(w in text_lower for w in ("ja", "yes", "genau", "richtig", "stimmt", "ok", "korrekt")):
        intent = "yes"
    elif any(w in text_lower for w in ("nein", "no", "falsch", "nicht")):
        intent = "no"
    elif any(w in text_lower for w in ("hallo", "hi", "guten", "moin", "servus")):
        intent = "greeting"
    elif any(w in text_lower for w in ("hilfe", "help", "was kannst")):
        intent = "help"
    else:
        intent = "unknown"

    return NLPResult(intent=intent, entities=entities, confidence=0.6)


async def process_message(phone: str, restaurant_slug: str, text: str) -> str:
    """Main entry: process incoming WhatsApp message and return response text."""
    session = get_or_create_session(phone, restaurant_slug)
    nlp = await analyze_message(text)

    # Merge entities into session data
    for key, val in nlp.entities.items():
        if val is not None:
            session.data[key] = val

    response = await _handle_state(session, nlp, text)
    return response


async def _handle_state(session: ConversationSession, nlp: NLPResult, text: str) -> str:
    state = session.state

    if state == BotState.INIT:
        return await _handle_init(session, nlp)
    elif state == BotState.COLLECT_DATE:
        return _handle_collect_date(session, nlp)
    elif state == BotState.COLLECT_TIME:
        return _handle_collect_time(session, nlp)
    elif state == BotState.COLLECT_SIZE:
        return _handle_collect_size(session, nlp)
    elif state == BotState.COLLECT_NAME:
        return _handle_collect_name(session, nlp, text)
    elif state == BotState.COLLECT_SPECIAL:
        return _handle_collect_special(session, nlp, text)
    elif state == BotState.CONFIRM:
        return _handle_confirm(session, nlp)
    elif state == BotState.CANCEL:
        return _handle_cancel(session, nlp, text)
    elif state == BotState.CANCEL_CONFIRM:
        return _handle_cancel_confirm(session, nlp)
    else:
        session.state = BotState.INIT
        return await _handle_init(session, nlp)


async def _handle_init(session: ConversationSession, nlp: NLPResult) -> str:
    intent = nlp.intent

    if intent == "reserve":
        # Check if we already have enough data for one-shot
        d = session.data
        if d.get("date") and d.get("time") and d.get("party_size"):
            if d.get("name"):
                session.state = BotState.CONFIRM
                return _build_confirmation_prompt(session)
            session.state = BotState.COLLECT_NAME
            return "Auf welchen Namen soll die Reservierung laufen?"
        if not d.get("date"):
            session.state = BotState.COLLECT_DATE
            return "Fuer welches Datum moechten Sie reservieren? (z.B. 15.03.2026)"
        if not d.get("time"):
            session.state = BotState.COLLECT_TIME
            return "Um wie viel Uhr moechten Sie kommen? (z.B. 19:00)"
        if not d.get("party_size"):
            session.state = BotState.COLLECT_SIZE
            return "Fuer wie viele Personen?"
        session.state = BotState.COLLECT_NAME
        return "Auf welchen Namen soll die Reservierung laufen?"

    elif intent == "cancel":
        session.state = BotState.CANCEL
        return "Bitte nennen Sie Ihren Bestaetigungscode, um die Reservierung zu stornieren."

    elif intent == "modify":
        session.state = BotState.CANCEL
        return "Bitte nennen Sie Ihren Bestaetigungscode, um die Reservierung zu aendern."

    elif intent == "greeting":
        return (
            "Hallo! Willkommen beim Reservierungsservice. "
            "Ich kann Ihnen helfen eine Reservierung zu erstellen, zu aendern oder zu stornieren. "
            "Was moechten Sie tun?"
        )

    elif intent == "help":
        return (
            "Ich kann Ihnen bei Folgendem helfen:\n"
            "- Reservierung erstellen\n"
            "- Reservierung stornieren\n"
            "- Reservierung aendern\n\n"
            "Schreiben Sie einfach, was Sie moechten!"
        )

    else:
        return (
            "Willkommen! Moechten Sie eine Reservierung erstellen, aendern oder stornieren? "
            "Schreiben Sie z.B. 'Tisch fuer 4 Personen am 15.03. um 19 Uhr'."
        )


def _handle_collect_date(session: ConversationSession, nlp: NLPResult) -> str:
    if session.data.get("date"):
        session.state = BotState.COLLECT_TIME if not session.data.get("time") else BotState.COLLECT_SIZE
        if session.state == BotState.COLLECT_TIME:
            return f"Datum: {session.data['date']}. Um wie viel Uhr moechten Sie kommen?"
        return f"Datum: {session.data['date']}. Fuer wie viele Personen?"
    return "Bitte geben Sie ein gueltiges Datum an (z.B. 15.03.2026)."


def _handle_collect_time(session: ConversationSession, nlp: NLPResult) -> str:
    if session.data.get("time"):
        if not session.data.get("party_size"):
            session.state = BotState.COLLECT_SIZE
            return f"Uhrzeit: {session.data['time']} Uhr. Fuer wie viele Personen?"
        session.state = BotState.COLLECT_NAME
        return "Auf welchen Namen soll die Reservierung laufen?"
    return "Bitte geben Sie eine gueltige Uhrzeit an (z.B. 19:00)."


def _handle_collect_size(session: ConversationSession, nlp: NLPResult) -> str:
    # Try to parse a number from entity or raw text
    if session.data.get("party_size"):
        session.state = BotState.COLLECT_NAME
        return f"{session.data['party_size']} Personen. Auf welchen Namen soll reserviert werden?"
    return "Bitte geben Sie die Anzahl der Personen an (z.B. '4 Personen')."


def _handle_collect_name(session: ConversationSession, nlp: NLPResult, text: str) -> str:
    if not session.data.get("name"):
        # Use the raw text as name if no entity extracted
        name = text.strip()
        if len(name) >= 2:
            session.data["name"] = name
    if session.data.get("name"):
        session.state = BotState.COLLECT_SPECIAL
        return f"Name: {session.data['name']}. Haben Sie besondere Wuensche? (z.B. Terrasse, Kinderstuhl — oder 'nein')"
    return "Bitte nennen Sie Ihren Namen."


def _handle_collect_special(session: ConversationSession, nlp: NLPResult, text: str) -> str:
    text_lower = text.lower().strip()
    if text_lower not in ("nein", "no", "keine", "-", ""):
        session.data["special_requests"] = text.strip()
    session.state = BotState.CONFIRM
    return _build_confirmation_prompt(session)


def _handle_confirm(session: ConversationSession, nlp: NLPResult) -> str:
    if nlp.intent == "yes":
        # Signal to webhook handler that reservation should be created
        session.data["confirmed"] = True
        session.state = BotState.DONE
        clear_session(session.phone, session.restaurant_slug)
        return (
            "Ihre Reservierung wurde erstellt! "
            "Sie erhalten in Kuerze eine Bestaetigung per E-Mail/SMS. "
            "Vielen Dank!"
        )
    elif nlp.intent == "no":
        session.state = BotState.INIT
        session.data.clear()
        return "Reservierung abgebrochen. Moechten Sie eine neue Reservierung erstellen?"
    return "Bitte antworten Sie mit 'Ja' oder 'Nein'."


def _handle_cancel(session: ConversationSession, nlp: NLPResult, text: str) -> str:
    code = session.data.get("confirmation_code")
    if not code:
        # Try to extract from text directly
        match = re.search(r"[A-Z0-9]{6,8}", text.upper())
        if match:
            code = match.group(0)
            session.data["confirmation_code"] = code

    if code:
        session.state = BotState.CANCEL_CONFIRM
        return f"Moechten Sie die Reservierung mit Code {code} wirklich stornieren? (Ja/Nein)"
    return "Bitte geben Sie Ihren Bestaetigungscode ein."


def _handle_cancel_confirm(session: ConversationSession, nlp: NLPResult) -> str:
    if nlp.intent == "yes":
        session.data["cancel_confirmed"] = True
        session.state = BotState.DONE
        code = session.data.get("confirmation_code", "")
        clear_session(session.phone, session.restaurant_slug)
        return f"Reservierung {code} wurde storniert. Auf Wiedersehen!"
    elif nlp.intent == "no":
        session.state = BotState.INIT
        session.data.clear()
        return "Stornierung abgebrochen. Kann ich Ihnen sonst helfen?"
    return "Bitte antworten Sie mit 'Ja' oder 'Nein'."


def _build_confirmation_prompt(session: ConversationSession) -> str:
    d = session.data
    lines = [
        "Bitte bestaetigen Sie Ihre Reservierung:",
        f"  Datum: {d.get('date', '?')}",
        f"  Uhrzeit: {d.get('time', '?')} Uhr",
        f"  Personen: {d.get('party_size', '?')}",
        f"  Name: {d.get('name', '?')}",
    ]
    if d.get("special_requests"):
        lines.append(f"  Wuensche: {d['special_requests']}")
    lines.append("\nStimmt das so? (Ja/Nein)")
    return "\n".join(lines)
