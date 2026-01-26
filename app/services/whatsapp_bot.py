"""
WhatsApp Bot Service für automatische Reservierungen.

Verwendet OpenAI für natürliche Sprachverarbeitung und führt Gäste
durch den Reservierungsprozess via WhatsApp.

Features:
- One-Shot Reservierung (alle Infos aus einer Nachricht)
- Öffnungszeiten-Prüfung
- Alternative Zeiten vorschlagen
- Sonderwünsche erfassen
- Reservierung ändern (nicht nur stornieren)
- Freundlichere Nachrichten
"""
import logging
from typing import Optional, Tuple
from datetime import datetime, date, time as dt_time, timezone, timedelta
from pydantic import BaseModel
import json
import re

logger = logging.getLogger(__name__)

# Wochentage für Öffnungszeiten
WEEKDAY_NAMES = {
    0: "monday",
    1: "tuesday", 
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

WEEKDAY_NAMES_DE = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}


class ConversationState(BaseModel):
    """Zustand einer WhatsApp-Konversation."""
    phone_number: str
    restaurant_id: int
    # States: INIT, COLLECT_DATE, COLLECT_TIME, COLLECT_SIZE, COLLECT_NAME, 
    #         COLLECT_SPECIAL, CONFIRM, COMPLETE, CANCEL,
    #         MODIFY_CODE, MODIFY_SELECT, MODIFY_VALUE, CONFIRM_MODIFY,
    #         SUGGEST_ALTERNATIVES, RESUMED
    state: str = "INIT"
    guest_name: Optional[str] = None
    party_size: Optional[int] = None
    desired_date: Optional[date] = None
    desired_time: Optional[str] = None
    special_requests: Optional[str] = None
    last_message_at: datetime = None
    message_history: list[dict] = []
    # Für Änderungen
    modification_code: Optional[str] = None
    modification_field: Optional[str] = None  # date, time, party_size
    # Für Session-Resume
    was_timed_out: bool = False
    # Für Alternative-Zeiten
    suggested_alternatives: list[str] = []


class NLPResult(BaseModel):
    """Ergebnis der NLP-Analyse."""
    intent: str  # reservation, cancellation, modification, question, greeting, confirmation, rejection, special_request, other
    parsed_date: Optional[date] = None
    time: Optional[str] = None
    party_size: Optional[int] = None
    name: Optional[str] = None
    confirmation_code: Optional[str] = None
    special_request: Optional[str] = None
    modification_field: Optional[str] = None  # date, time, party_size
    raw_text: str = ""
    
    class Config:
        arbitrary_types_allowed = True


def check_opening_hours(
    opening_hours: Optional[dict],
    check_date: date,
    check_time: str,
) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """
    Prüft ob das Restaurant zu einem bestimmten Zeitpunkt geöffnet ist.
    
    Returns:
        Tuple von (is_open, message, open_time, close_time)
    """
    if not opening_hours:
        # Wenn keine Öffnungszeiten definiert, nehmen wir an es ist geöffnet
        return True, "", None, None
    
    weekday = check_date.weekday()
    weekday_name = WEEKDAY_NAMES.get(weekday, "monday")
    weekday_name_de = WEEKDAY_NAMES_DE.get(weekday, "Montag")
    
    day_hours = opening_hours.get(weekday_name)
    
    if not day_hours:
        # Restaurant an diesem Tag geschlossen
        # Finde nächsten offenen Tag
        open_days = []
        for i in range(7):
            day_name = WEEKDAY_NAMES.get(i)
            if day_name and opening_hours.get(day_name):
                open_days.append(WEEKDAY_NAMES_DE.get(i))
        
        if open_days:
            days_str = ", ".join(open_days[:-1])
            if len(open_days) > 1:
                days_str += f" und {open_days[-1]}"
            else:
                days_str = open_days[0]
            message = f"Wir haben am {weekday_name_de} leider geschlossen.\n\nUnsere Öffnungstage: {days_str}"
        else:
            message = f"Wir haben am {weekday_name_de} leider geschlossen."
        
        return False, message, None, None
    
    open_time = day_hours.get("open", "11:00")
    close_time = day_hours.get("close", "23:00")
    
    # Parse Zeiten
    try:
        check_hour, check_minute = map(int, check_time.split(":"))
        open_hour, open_minute = map(int, open_time.split(":"))
        close_hour, close_minute = map(int, close_time.split(":"))
        
        check_minutes = check_hour * 60 + check_minute
        open_minutes = open_hour * 60 + open_minute
        close_minutes = close_hour * 60 + close_minute
        
        # Handle midnight closing (z.B. 23:00 oder 00:00)
        if close_minutes < open_minutes:
            close_minutes += 24 * 60
        
        if check_minutes < open_minutes:
            message = f"Um {check_time} Uhr haben wir leider noch nicht geöffnet.\n\nWir öffnen am {weekday_name_de} um {open_time} Uhr."
            return False, message, open_time, close_time
        
        # Letzte Reservierung 1.5h vor Schluss
        last_reservation_minutes = close_minutes - 90
        if check_minutes > last_reservation_minutes:
            last_hour = last_reservation_minutes // 60
            last_minute = last_reservation_minutes % 60
            if last_hour >= 24:
                last_hour -= 24
            last_time = f"{last_hour:02d}:{last_minute:02d}"
            message = f"Um {check_time} Uhr können wir leider keine Reservierung mehr annehmen.\n\nLetzte Reservierung am {weekday_name_de}: {last_time} Uhr\n(Wir schließen um {close_time} Uhr)"
            return False, message, open_time, close_time
        
        return True, "", open_time, close_time
        
    except (ValueError, AttributeError):
        # Bei Parsing-Fehlern nehmen wir an es ist geöffnet
        return True, "", open_time, close_time


class WhatsAppBotService:
    """
    WhatsApp Bot für Restaurant-Reservierungen.
    
    Features:
    - Natürlichsprachliche Konversation
    - One-Shot Reservierung
    - Intent-Erkennung (Reservierung, Stornierung, Änderung, Fragen)
    - Entity-Extraktion (Datum, Zeit, Personenanzahl, Name)
    - Öffnungszeiten-Prüfung
    - Alternative Zeiten vorschlagen
    - Sonderwünsche erfassen
    - Geführter Reservierungsablauf
    """
    
    # Session-Timeout in Minuten
    SESSION_TIMEOUT_MINUTES = 60
    
    def __init__(self):
        self._openai_client = None
        self._conversations: dict[str, ConversationState] = {}
    
    def _get_openai_client(self):
        """Lazy-Load des OpenAI Clients."""
        if self._openai_client is None:
            from app.settings import AI_ENABLED, OPENAI_API_KEY
            
            if AI_ENABLED and OPENAI_API_KEY:
                try:
                    from openai import OpenAI
                    self._openai_client = OpenAI(api_key=OPENAI_API_KEY)
                    logger.info("WhatsApp Bot: OpenAI client initialized")
                except Exception as e:
                    logger.error(f"Failed to initialize OpenAI for WhatsApp bot: {e}")
        
        return self._openai_client
    
    def get_or_create_conversation(
        self,
        phone_number: str,
        restaurant_id: int,
    ) -> ConversationState:
        """Holt oder erstellt eine Konversation mit Session-Resume."""
        key = f"{phone_number}:{restaurant_id}"
        
        if key not in self._conversations:
            self._conversations[key] = ConversationState(
                phone_number=phone_number,
                restaurant_id=restaurant_id,
                last_message_at=datetime.now(timezone.utc),
            )
            return self._conversations[key]
        
        conv = self._conversations[key]
        
        # Prüfe ob Session abgelaufen
        if conv.last_message_at:
            age = datetime.now(timezone.utc) - conv.last_message_at.replace(tzinfo=timezone.utc)
            if age > timedelta(minutes=self.SESSION_TIMEOUT_MINUTES):
                # Session abgelaufen - aber Daten behalten für Resume
                old_state = conv.state
                old_data = {
                    "desired_date": conv.desired_date,
                    "desired_time": conv.desired_time,
                    "party_size": conv.party_size,
                    "guest_name": conv.guest_name,
                }
                
                # Prüfe ob wir Daten zum Fortsetzen haben
                has_data = any([
                    conv.desired_date,
                    conv.desired_time,
                    conv.party_size,
                    conv.guest_name,
                ])
                
                if has_data and old_state not in ["INIT", "COMPLETE"]:
                    # Markiere für Resume
                    conv.was_timed_out = True
                    conv.state = "RESUMED"
                else:
                    # Komplett zurücksetzen
                    self._conversations[key] = ConversationState(
                        phone_number=phone_number,
                        restaurant_id=restaurant_id,
                        last_message_at=datetime.now(timezone.utc),
                    )
                    conv = self._conversations[key]
        
        return conv
    
    def update_conversation(self, conv: ConversationState):
        """Aktualisiert eine Konversation."""
        key = f"{conv.phone_number}:{conv.restaurant_id}"
        conv.last_message_at = datetime.now(timezone.utc)
        self._conversations[key] = conv
    
    def clear_conversation(self, phone_number: str, restaurant_id: int):
        """Löscht eine Konversation."""
        key = f"{phone_number}:{restaurant_id}"
        if key in self._conversations:
            del self._conversations[key]
    
    def _is_simple_response(self, message: str) -> bool:
        """
        Prüft ob eine Nachricht einfach genug ist, um ohne KI verarbeitet zu werden.
        
        Einfache Antworten wie "Ja", "Nein", "Ok" brauchen keine KI.
        """
        message_lower = message.lower().strip()
        
        # Liste einfacher Antworten die keine KI brauchen
        simple_responses = [
            # Bestätigungen
            "ja", "jap", "jo", "yes", "ok", "okay", "passt", "stimmt", "genau", 
            "korrekt", "richtig", "bestätigen", "bestätigt", "alles klar",
            # Ablehnungen
            "nein", "nö", "ne", "no", "nicht", "falsch", "abbrechen",
            # Überspringen
            "keine", "kein", "nichts", "weiter", "überspringen", "-",
            # Grüße
            "hallo", "hi", "hey", "moin", "servus", "guten tag",
        ]
        
        # Exakte Übereinstimmung oder sehr kurze Nachricht
        if message_lower in simple_responses:
            return True
        
        # Nachricht mit nur einem Wort das in der Liste ist
        if len(message_lower.split()) == 1 and message_lower in simple_responses:
            return True
        
        # Sehr kurze Nachrichten (1-3 Zeichen außer Zahlen)
        if len(message_lower) <= 3 and not message_lower.isdigit():
            return True
        
        return False
    
    async def analyze_message(
        self,
        message: str,
        conversation_history: list[dict] = None,
    ) -> NLPResult:
        """
        Analysiert eine Nachricht mit KI.
        
        Extrahiert Intent und Entities aus natürlichsprachlicher Eingabe.
        Einfache Nachrichten werden ohne KI verarbeitet für schnellere Antworten.
        """
        # Optimierung: Einfache Antworten ohne KI verarbeiten
        if self._is_simple_response(message):
            logger.info(f"WhatsApp Bot: Using regex for simple response: {message[:20]}")
            return self._analyze_with_regex(message)
        
        client = self._get_openai_client()
        
        if not client:
            return self._analyze_with_regex(message)
        
        try:
            history_text = ""
            if conversation_history:
                history_text = "\n".join([
                    f"{m['role']}: {m['content']}"
                    for m in conversation_history[-5:]
                ])
            
            today = date.today()
            tomorrow = today + timedelta(days=1)
            day_after_tomorrow = today + timedelta(days=2)
            
            # Berechne nächsten Samstag/Sonntag
            days_until_saturday = (5 - today.weekday()) % 7
            if days_until_saturday == 0:
                days_until_saturday = 7
            next_saturday = today + timedelta(days=days_until_saturday)
            next_sunday = next_saturday + timedelta(days=1)
            
            prompt = f"""Analysiere die folgende WhatsApp-Nachricht eines Restaurant-Gastes.

WICHTIG - Aktuelles Datum: {today.strftime('%d.%m.%Y')} ({WEEKDAY_NAMES_DE.get(today.weekday())})

Extrahiere folgende Informationen als JSON:
- intent: "reservation" (neue Reservierung), "cancellation" (Stornierung), "modification" (Änderung bestehender Reservierung), "question" (Frage), "greeting" (Begrüßung), "confirmation" (Ja/OK/Bestätigung), "rejection" (Nein/Ablehnung), "special_request" (Sonderwunsch wie Kinderstuhl, Allergien), "resume_yes" (Fortsetzen), "resume_no" (Neu beginnen), "other"
- date: Gewünschtes Datum im ISO-Format (YYYY-MM-DD) oder null
- time: Gewünschte Uhrzeit im Format HH:MM oder null
- party_size: Anzahl Personen als Integer oder null
- name: Name des Gastes oder null
- confirmation_code: Bestätigungscode wenn erwähnt oder null
- special_request: Sonderwunsch-Text oder null (z.B. "Kinderstuhl", "Fensterplatz", "Allergien")
- modification_field: Was soll geändert werden? "date", "time", "party_size" oder null

Datumsreferenzen (heute ist {today.strftime('%A')}):
- "heute" = {today.isoformat()}
- "morgen" = {tomorrow.isoformat()}
- "übermorgen" = {day_after_tomorrow.isoformat()}
- "nächsten Samstag" / "am Samstag" = {next_saturday.isoformat()}
- "nächsten Sonntag" / "am Sonntag" = {next_sunday.isoformat()}
- "am Wochenende" = {next_saturday.isoformat()} (Samstag)

Wichtige Muster:
- "für 4" oder "4 Personen" oder "zu viert" -> party_size: 4
- "19 Uhr" oder "7 Uhr abends" oder "19:00" -> time: "19:00"
- "auf Müller" oder "Name ist Müller" -> name: "Müller"
- "Kinderstuhl" oder "Hochstuhl" -> special_request: "Kinderstuhl benötigt"
- "vegetarisch" oder "Allergie" -> special_request: entsprechender Text

Konversationsverlauf:
{history_text}

Aktuelle Nachricht: {message}

Antworte NUR mit dem JSON-Objekt:"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Du bist ein NLP-Parser für Restaurant-Reservierungen. Antworte nur mit validem JSON."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            parsed_date = None
            if data.get("date"):
                try:
                    parsed_date = date.fromisoformat(data["date"])
                except ValueError:
                    pass
            
            return NLPResult(
                intent=data.get("intent", "other"),
                parsed_date=parsed_date,
                time=data.get("time"),
                party_size=data.get("party_size"),
                name=data.get("name"),
                confirmation_code=data.get("confirmation_code"),
                special_request=data.get("special_request"),
                modification_field=data.get("modification_field"),
                raw_text=message,
            )
            
        except Exception as e:
            logger.error(f"NLP analysis failed: {e}")
            return self._analyze_with_regex(message)
    
    def _analyze_with_regex(self, message: str) -> NLPResult:
        """Fallback: Regex-basierte Analyse."""
        message_lower = message.lower().strip()
        
        # Intent detection
        intent = "other"
        if any(word in message_lower for word in ["reserv", "tisch", "buchen", "platz", "plätze"]):
            intent = "reservation"
        elif any(word in message_lower for word in ["storno", "absagen", "cancel", "stornieren"]):
            intent = "cancellation"
        elif any(word in message_lower for word in ["ändern", "verschieben", "umbuchen", "änderung"]):
            intent = "modification"
        elif any(word in message_lower for word in ["hallo", "hi", "guten tag", "servus", "moin", "hey"]):
            intent = "greeting"
        elif any(word in message_lower for word in ["ja", "ok", "passt", "genau", "korrekt", "stimmt", "richtig", "bestätigen", "jap", "jo"]):
            intent = "confirmation"
        elif any(word in message_lower for word in ["nein", "nicht", "falsch", "neu", "von vorne", "abbrechen"]):
            intent = "rejection"
        elif any(word in message_lower for word in ["kinderstuhl", "hochstuhl", "allergie", "vegetarisch", "vegan", "fenster", "terrasse", "draußen", "ruhig"]):
            intent = "special_request"
        elif any(word in message_lower for word in ["fortsetzen", "weitermachen", "weiter"]):
            intent = "resume_yes"
        elif "?" in message:
            intent = "question"
        
        # Date extraction
        parsed_date = None
        today = date.today()
        
        if "heute" in message_lower:
            parsed_date = today
        elif "morgen" in message_lower:
            parsed_date = today + timedelta(days=1)
        elif "übermorgen" in message_lower:
            parsed_date = today + timedelta(days=2)
        elif "samstag" in message_lower:
            days_until = (5 - today.weekday()) % 7
            if days_until == 0:
                days_until = 7
            parsed_date = today + timedelta(days=days_until)
        elif "sonntag" in message_lower:
            days_until = (6 - today.weekday()) % 7
            if days_until == 0:
                days_until = 7
            parsed_date = today + timedelta(days=days_until)
        elif "wochenende" in message_lower:
            days_until = (5 - today.weekday()) % 7
            if days_until == 0:
                days_until = 7
            parsed_date = today + timedelta(days=days_until)
        else:
            date_match = re.search(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", message)
            if date_match:
                day = int(date_match.group(1))
                month = int(date_match.group(2))
                year = int(date_match.group(3)) if date_match.group(3) else today.year
                if year < 100:
                    year += 2000
                try:
                    parsed_date = date(year, month, day)
                except ValueError:
                    pass
        
        # Time extraction
        parsed_time = None
        time_patterns = [
            r"(\d{1,2}):(\d{2})\s*(?:uhr)?",
            r"(\d{1,2})\s*uhr",
            r"um\s*(\d{1,2})(?::(\d{2}))?",
        ]
        for pattern in time_patterns:
            time_match = re.search(pattern, message_lower)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.lastindex >= 2 and time_match.group(2) else 0
                # Assume PM for hours 1-10 for reservations
                if 1 <= hour <= 10 and intent in ["reservation", "other"]:
                    hour += 12
                if 0 <= hour < 24 and 0 <= minute < 60:
                    parsed_time = f"{hour:02d}:{minute:02d}"
                break
        
        # Party size extraction
        party_size = None
        size_patterns = [
            r"für\s*(\d+)",
            r"(\d+)\s*person",
            r"(\d+)\s*pers",
            r"(\d+)\s*leute",
            r"(\d+)\s*gäste",
            r"zu\s*(\d+)",
            r"(\d+)\s*plätze",
        ]
        for pattern in size_patterns:
            size_match = re.search(pattern, message_lower)
            if size_match:
                size = int(size_match.group(1))
                if 1 <= size <= 30:
                    party_size = size
                    break
        
        # Name extraction
        name = None
        name_patterns = [
            r"(?:name|heiße|bin|ich bin)\s+(?:ist\s+)?([A-ZÄÖÜa-zäöüß]+(?:\s+[A-ZÄÖÜa-zäöüß]+)?)",
            r"(?:auf\s+(?:den\s+)?(?:namen?\s+)?)([A-ZÄÖÜa-zäöüß]+(?:\s+[A-ZÄÖÜa-zäöüß]+)?)",
        ]
        for pattern in name_patterns:
            name_match = re.search(pattern, message, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()
                break
        
        # Special request extraction
        special_request = None
        if intent == "special_request":
            special_request = message.strip()
        elif any(word in message_lower for word in ["kinderstuhl", "hochstuhl"]):
            special_request = "Kinderstuhl benötigt"
        elif "allergie" in message_lower:
            special_request = f"Allergiehinweis: {message}"
        elif any(word in message_lower for word in ["vegetarisch", "vegan"]):
            special_request = f"Ernährung: {message}"
        
        # Confirmation code extraction
        confirmation_code = None
        code_match = re.search(r"\b([A-Z0-9]{6,10})\b", message.upper())
        if code_match:
            potential_code = code_match.group(1)
            # Nur wenn es wie ein Code aussieht (Mix aus Buchstaben und Zahlen)
            if re.search(r"[A-Z]", potential_code) and re.search(r"[0-9]", potential_code):
                confirmation_code = potential_code
        
        return NLPResult(
            intent=intent,
            parsed_date=parsed_date,
            time=parsed_time,
            party_size=party_size,
            name=name,
            confirmation_code=confirmation_code,
            special_request=special_request,
            raw_text=message,
        )
    
    async def process_message(
        self,
        phone_number: str,
        restaurant_id: int,
        restaurant_name: str,
        message: str,
        opening_hours: Optional[dict] = None,
    ) -> str:
        """
        Verarbeitet eine eingehende WhatsApp-Nachricht.
        
        Args:
            phone_number: Telefonnummer des Gastes
            restaurant_id: ID des Restaurants
            restaurant_name: Name des Restaurants
            message: Nachrichtentext
            opening_hours: Öffnungszeiten des Restaurants
        
        Returns:
            Antwort-Nachricht für den Gast
        """
        conv = self.get_or_create_conversation(phone_number, restaurant_id)
        
        # Füge Nachricht zur History hinzu
        conv.message_history.append({"role": "user", "content": message})
        
        # Analysiere Nachricht
        nlp = await self.analyze_message(message, conv.message_history)
        
        logger.info(f"WhatsApp Bot: {phone_number} -> Intent: {nlp.intent}, State: {conv.state}")
        
        # State Machine
        response = await self._handle_state(conv, nlp, restaurant_name, opening_hours)
        
        # Füge Antwort zur History hinzu
        conv.message_history.append({"role": "assistant", "content": response})
        
        # Aktualisiere Konversation
        self.update_conversation(conv)
        
        return response
    
    async def _handle_state(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
        opening_hours: Optional[dict] = None,
    ) -> str:
        """Verarbeitet basierend auf aktuellem State."""
        
        # Session Resume Handler
        if conv.state == "RESUMED":
            return self._handle_resumed_session(conv, nlp, restaurant_name)
        
        # INIT State
        if conv.state == "INIT":
            return self._handle_init(conv, nlp, restaurant_name)
        
        # Datum sammeln
        if conv.state == "COLLECT_DATE":
            return self._handle_collect_date(conv, nlp, restaurant_name, opening_hours)
        
        # Zeit sammeln
        if conv.state == "COLLECT_TIME":
            return self._handle_collect_time(conv, nlp, restaurant_name, opening_hours)
        
        # Alternative Zeit wählen
        if conv.state == "SUGGEST_ALTERNATIVES":
            return self._handle_alternatives(conv, nlp, restaurant_name)
        
        # Personenanzahl sammeln
        if conv.state == "COLLECT_SIZE":
            return self._handle_collect_size(conv, nlp, restaurant_name)
        
        # Name sammeln
        if conv.state == "COLLECT_NAME":
            return self._handle_collect_name(conv, nlp, restaurant_name)
        
        # Sonderwünsche sammeln
        if conv.state == "COLLECT_SPECIAL":
            return self._handle_collect_special(conv, nlp, restaurant_name)
        
        # Bestätigung
        if conv.state == "CONFIRM":
            return self._handle_confirm(conv, nlp, restaurant_name)
        
        # Stornierung
        if conv.state == "CANCEL":
            return self._handle_cancel(conv, nlp)
        
        # Änderung - Code eingeben
        if conv.state == "MODIFY_CODE":
            return self._handle_modify_code(conv, nlp)
        
        # Änderung - Feld auswählen
        if conv.state == "MODIFY_SELECT":
            return self._handle_modify_select(conv, nlp)
        
        # Änderung - Neuen Wert eingeben
        if conv.state == "MODIFY_VALUE":
            return self._handle_modify_value(conv, nlp, restaurant_name)
        
        # Änderung bestätigen
        if conv.state == "CONFIRM_MODIFY":
            return self._handle_confirm_modify(conv, nlp)
        
        # Fallback
        return self._get_fallback_message(restaurant_name)
    
    def _handle_resumed_session(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt eine fortgesetzte Session nach Timeout."""
        
        # Prüfe ob User fortsetzen oder neu beginnen möchte
        if nlp.intent in ["resume_yes", "confirmation"] or any(word in nlp.raw_text.lower() for word in ["ja", "weiter", "fortsetzen"]):
            conv.was_timed_out = False
            # Zurück zum vorherigen Flow
            return self._determine_next_question(conv, restaurant_name)
        
        elif nlp.intent in ["resume_no", "rejection"] or any(word in nlp.raw_text.lower() for word in ["nein", "neu", "von vorne"]):
            # Komplett zurücksetzen
            conv.state = "INIT"
            conv.desired_date = None
            conv.desired_time = None
            conv.party_size = None
            conv.guest_name = None
            conv.special_requests = None
            conv.was_timed_out = False
            return self._get_welcome_message(restaurant_name)
        
        else:
            # Zeige was wir haben und frage
            info_parts = []
            if conv.desired_date:
                info_parts.append(f"📅 {conv.desired_date.strftime('%d.%m.%Y')}")
            if conv.desired_time:
                info_parts.append(f"⏰ {conv.desired_time} Uhr")
            if conv.party_size:
                info_parts.append(f"👥 {conv.party_size} Personen")
            if conv.guest_name:
                info_parts.append(f"👤 {conv.guest_name}")
            
            info_str = "\n".join(info_parts) if info_parts else "Keine Daten"
            
            return (
                f"Willkommen zurück! 👋\n\n"
                f"Sie hatten bereits begonnen, eine Reservierung anzulegen:\n\n"
                f"{info_str}\n\n"
                f"Möchten Sie *fortfahren* oder *neu beginnen*?"
            )
    
    def _handle_init(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt den INIT State."""
        
        if nlp.intent == "greeting":
            conv.state = "COLLECT_DATE"
            return self._get_welcome_message(restaurant_name)
        
        elif nlp.intent == "reservation":
            # One-Shot: Extrahiere alle verfügbaren Infos
            if nlp.parsed_date:
                conv.desired_date = nlp.parsed_date
            if nlp.time:
                conv.desired_time = nlp.time
            if nlp.party_size:
                conv.party_size = nlp.party_size
            if nlp.name:
                conv.guest_name = nlp.name
            if nlp.special_request:
                conv.special_requests = nlp.special_request
            
            return self._determine_next_question(conv, restaurant_name)
        
        elif nlp.intent == "cancellation":
            conv.state = "CANCEL"
            return (
                f"Sie möchten eine Reservierung stornieren?\n\n"
                f"Bitte nennen Sie mir Ihren *Bestätigungscode*.\n\n"
                f"Sie finden ihn in Ihrer Bestätigungs-Nachricht."
            )
        
        elif nlp.intent == "modification":
            conv.state = "MODIFY_CODE"
            return (
                f"Sie möchten eine bestehende Reservierung ändern?\n\n"
                f"Bitte nennen Sie mir Ihren *Bestätigungscode*.\n\n"
                f"Sie finden ihn in Ihrer Bestätigungs-Nachricht."
            )
        
        elif nlp.intent == "question":
            return (
                f"Gerne helfe ich Ihnen! 😊\n\n"
                f"Bei {restaurant_name} können Sie:\n"
                f"• Einen Tisch *reservieren*\n"
                f"• Eine Reservierung *stornieren*\n"
                f"• Eine Reservierung *ändern*\n\n"
                f"Was möchten Sie tun?"
            )
        
        else:
            # Prüfe ob trotzdem Reservierungsdaten enthalten
            if nlp.parsed_date or nlp.time or nlp.party_size:
                if nlp.parsed_date:
                    conv.desired_date = nlp.parsed_date
                if nlp.time:
                    conv.desired_time = nlp.time
                if nlp.party_size:
                    conv.party_size = nlp.party_size
                if nlp.name:
                    conv.guest_name = nlp.name
                
                return self._determine_next_question(conv, restaurant_name)
            
            conv.state = "COLLECT_DATE"
            return self._get_welcome_message(restaurant_name)
    
    def _handle_collect_date(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
        opening_hours: Optional[dict] = None,
    ) -> str:
        """Behandelt die Datumserfassung."""
        
        if nlp.parsed_date:
            # Prüfe ob Datum in der Vergangenheit
            if nlp.parsed_date < date.today():
                return (
                    f"Das Datum {nlp.parsed_date.strftime('%d.%m.%Y')} liegt leider in der Vergangenheit. 📅\n\n"
                    f"Bitte wählen Sie ein Datum ab heute."
                )
            
            # Prüfe Öffnungszeiten für diesen Tag
            if opening_hours:
                is_open, message, _, _ = check_opening_hours(opening_hours, nlp.parsed_date, "12:00")
                if not is_open and "geschlossen" in message.lower():
                    return f"{message}\n\nBitte wählen Sie einen anderen Tag. 📅"
            
            conv.desired_date = nlp.parsed_date
            
            # Extrahiere auch andere Infos wenn vorhanden
            if nlp.time:
                conv.desired_time = nlp.time
            if nlp.party_size:
                conv.party_size = nlp.party_size
            if nlp.name:
                conv.guest_name = nlp.name
            
            return self._determine_next_question(conv, restaurant_name)
        
        else:
            weekday = WEEKDAY_NAMES_DE.get(date.today().weekday(), "")
            return (
                f"Ich habe das Datum leider nicht verstanden. 🤔\n\n"
                f"Bitte nennen Sie ein Datum, z.B.:\n"
                f"• *heute* ({weekday})\n"
                f"• *morgen*\n"
                f"• *Samstag* oder *Sonntag*\n"
                f"• Ein konkretes Datum wie *25.01.*"
            )
    
    def _handle_collect_time(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
        opening_hours: Optional[dict] = None,
    ) -> str:
        """Behandelt die Zeiterfassung."""
        
        if nlp.time:
            # Prüfe Öffnungszeiten
            if opening_hours and conv.desired_date:
                is_open, message, open_time, close_time = check_opening_hours(
                    opening_hours, conv.desired_date, nlp.time
                )
                if not is_open:
                    # Zeige Öffnungszeiten und frage nach anderer Zeit
                    return (
                        f"{message}\n\n"
                        f"Welche andere Uhrzeit passt Ihnen?"
                    )
            
            conv.desired_time = nlp.time
            
            # Extrahiere auch andere Infos
            if nlp.party_size:
                conv.party_size = nlp.party_size
            if nlp.name:
                conv.guest_name = nlp.name
            
            return self._determine_next_question(conv, restaurant_name)
        
        else:
            # Zeige Öffnungszeiten wenn verfügbar
            time_hint = ""
            if opening_hours and conv.desired_date:
                weekday = conv.desired_date.weekday()
                day_name = WEEKDAY_NAMES.get(weekday, "monday")
                day_hours = opening_hours.get(day_name)
                if day_hours:
                    time_hint = f"\n\nUnsere Öffnungszeiten am {WEEKDAY_NAMES_DE.get(weekday)}: {day_hours.get('open', '11:00')} - {day_hours.get('close', '23:00')} Uhr"
            
            return (
                f"Um welche Uhrzeit möchten Sie reservieren? ⏰\n\n"
                f"Z.B. *19:00* oder *19 Uhr* oder *halb acht*"
                f"{time_hint}"
            )
    
    def _handle_alternatives(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt die Auswahl einer alternativen Zeit."""
        
        if nlp.time:
            # Prüfe ob gewählte Zeit in den Alternativen ist
            if nlp.time in conv.suggested_alternatives or True:  # Akzeptiere auch andere Zeiten
                conv.desired_time = nlp.time
                conv.suggested_alternatives = []
                conv.state = "COLLECT_SIZE" if not conv.party_size else "COLLECT_NAME" if not conv.guest_name else "COLLECT_SPECIAL"
                return self._determine_next_question(conv, restaurant_name)
        
        # Zeige Alternativen erneut
        if conv.suggested_alternatives:
            alt_list = "\n".join([f"• *{t} Uhr*" for t in conv.suggested_alternatives])
            return (
                f"Bitte wählen Sie eine der verfügbaren Zeiten:\n\n"
                f"{alt_list}\n\n"
                f"Oder nennen Sie eine andere Uhrzeit."
            )
        
        # Keine Alternativen mehr - zurück zur Zeitauswahl
        conv.state = "COLLECT_TIME"
        return (
            f"Um welche Uhrzeit möchten Sie stattdessen reservieren? ⏰"
        )
    
    def _handle_collect_size(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt die Erfassung der Personenanzahl."""
        
        if nlp.party_size:
            if nlp.party_size > 20:
                return (
                    f"Für Gruppen über 20 Personen bitten wir Sie, "
                    f"uns direkt anzurufen. 📞\n\n"
                    f"Für wie viele Personen (bis 20) darf ich reservieren?"
                )
            
            conv.party_size = nlp.party_size
            
            if nlp.name:
                conv.guest_name = nlp.name
            
            return self._determine_next_question(conv, restaurant_name)
        
        else:
            return (
                f"Für wie viele Personen darf ich reservieren? 👥\n\n"
                f"Z.B. *4 Personen* oder *für 4* oder *zu viert*"
            )
    
    def _handle_collect_name(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt die Namenserfassung."""
        
        # Verwende extrahierten Namen oder die gesamte Nachricht
        name = nlp.name or nlp.raw_text.strip()
        
        # Filtere offensichtliche Nicht-Namen
        invalid_words = ["ja", "nein", "ok", "hallo", "hi", "danke", "bitte"]
        if name.lower() in invalid_words:
            name = None
        
        if name and len(name) >= 2 and len(name) <= 50:
            conv.guest_name = name
            return self._determine_next_question(conv, restaurant_name)
        
        else:
            return (
                f"Auf welchen Namen soll die Reservierung laufen? 👤\n\n"
                f"Z.B. *Müller* oder *Max Mustermann*"
            )
    
    def _handle_collect_special(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt die Erfassung von Sonderwünschen."""
        
        raw_lower = nlp.raw_text.lower().strip()
        
        # Prüfe ob übersprungen werden soll
        skip_words = ["nein", "keine", "nö", "nichts", "kein", "weiter", "überspringen", "-"]
        if any(raw_lower == word or raw_lower.startswith(word + " ") for word in skip_words):
            conv.state = "CONFIRM"
            return self._get_confirmation_summary(conv, restaurant_name)
        
        # Speichere Sonderwunsch
        if nlp.special_request:
            conv.special_requests = nlp.special_request
        elif len(nlp.raw_text.strip()) > 2:
            conv.special_requests = nlp.raw_text.strip()
        
        conv.state = "CONFIRM"
        return self._get_confirmation_summary(conv, restaurant_name)
    
    def _handle_confirm(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt die Bestätigung."""
        
        logger.info(f"WhatsApp Bot: CONFIRM state - intent={nlp.intent}, raw={nlp.raw_text}")
        
        if nlp.intent == "confirmation" or any(word in nlp.raw_text.lower() for word in ["ja", "ok", "passt", "bestätigen", "stimmt", "korrekt", "genau", "jap", "jo"]):
            conv.state = "COMPLETE"
            logger.info(f"WhatsApp Bot: Reservation confirmed for {conv.guest_name}")
            return "RESERVATION_CONFIRMED"
        
        elif nlp.intent == "rejection" or any(word in nlp.raw_text.lower() for word in ["nein", "nicht", "falsch", "ändern", "korrigieren"]):
            conv.state = "COLLECT_DATE"
            conv.desired_date = None
            conv.desired_time = None
            conv.party_size = None
            conv.special_requests = None
            # Name behalten
            return (
                f"Kein Problem, beginnen wir von vorne. 😊\n\n"
                f"Für welches Datum möchten Sie reservieren?"
            )
        
        else:
            return (
                f"Bitte bestätigen Sie mit *Ja* oder sagen Sie *Nein* zum Ändern.\n\n"
                f"Sie können auch einzelne Angaben korrigieren, z.B.:\n"
                f"• *Andere Uhrzeit: 20:00*\n"
                f"• *5 Personen statt 4*"
            )
    
    def _handle_cancel(
        self,
        conv: ConversationState,
        nlp: NLPResult,
    ) -> str:
        """Behandelt die Stornierung."""
        
        code = nlp.confirmation_code or nlp.raw_text.strip().upper()
        
        # Entferne Leerzeichen und Bindestriche
        code = re.sub(r"[\s\-]", "", code)
        
        if code and len(code) >= 6:
            conv.state = "INIT"
            return f"CANCELLATION_REQUEST:{code}"
        
        else:
            return (
                f"Bitte nennen Sie mir den *Bestätigungscode* Ihrer Reservierung.\n\n"
                f"Der Code besteht aus Buchstaben und Zahlen, z.B. *ABC12345*\n\n"
                f"Sie finden ihn in Ihrer Bestätigungs-Nachricht."
            )
    
    def _handle_modify_code(
        self,
        conv: ConversationState,
        nlp: NLPResult,
    ) -> str:
        """Behandelt die Code-Eingabe für Änderungen."""
        
        code = nlp.confirmation_code or nlp.raw_text.strip().upper()
        code = re.sub(r"[\s\-]", "", code)
        
        if code and len(code) >= 6:
            conv.modification_code = code
            conv.state = "MODIFY_SELECT"
            return (
                f"Bestätigungscode: *{code}*\n\n"
                f"Was möchten Sie ändern?\n\n"
                f"• *Datum*\n"
                f"• *Uhrzeit*\n"
                f"• *Personenanzahl*\n\n"
                f"Oder sagen Sie *Abbrechen* zum Beenden."
            )
        
        else:
            return (
                f"Bitte nennen Sie mir den *Bestätigungscode* Ihrer Reservierung.\n\n"
                f"Der Code besteht aus Buchstaben und Zahlen, z.B. *ABC12345*"
            )
    
    def _handle_modify_select(
        self,
        conv: ConversationState,
        nlp: NLPResult,
    ) -> str:
        """Behandelt die Feldauswahl für Änderungen."""
        
        raw_lower = nlp.raw_text.lower()
        
        if "abbrechen" in raw_lower or "stopp" in raw_lower:
            conv.state = "INIT"
            conv.modification_code = None
            return (
                f"Änderung abgebrochen.\n\n"
                f"Kann ich Ihnen sonst noch helfen?"
            )
        
        if "datum" in raw_lower or nlp.modification_field == "date":
            conv.modification_field = "date"
            conv.state = "MODIFY_VALUE"
            return (
                f"Auf welches *Datum* möchten Sie die Reservierung verschieben?\n\n"
                f"Z.B. *morgen* oder *25.01.*"
            )
        
        elif "uhrzeit" in raw_lower or "zeit" in raw_lower or nlp.modification_field == "time":
            conv.modification_field = "time"
            conv.state = "MODIFY_VALUE"
            return (
                f"Auf welche *Uhrzeit* möchten Sie die Reservierung verschieben?\n\n"
                f"Z.B. *19:00* oder *20 Uhr*"
            )
        
        elif "person" in raw_lower or "anzahl" in raw_lower or "gäste" in raw_lower or nlp.modification_field == "party_size":
            conv.modification_field = "party_size"
            conv.state = "MODIFY_VALUE"
            return (
                f"Auf wie viele *Personen* möchten Sie die Reservierung ändern?\n\n"
                f"Z.B. *5 Personen* oder *für 6*"
            )
        
        else:
            return (
                f"Was möchten Sie ändern?\n\n"
                f"• *Datum*\n"
                f"• *Uhrzeit*\n"
                f"• *Personenanzahl*\n\n"
                f"Oder sagen Sie *Abbrechen*."
            )
    
    def _handle_modify_value(
        self,
        conv: ConversationState,
        nlp: NLPResult,
        restaurant_name: str,
    ) -> str:
        """Behandelt die Werteingabe für Änderungen."""
        
        if conv.modification_field == "date":
            if nlp.parsed_date:
                if nlp.parsed_date < date.today():
                    return f"Das Datum liegt in der Vergangenheit. Bitte wählen Sie ein zukünftiges Datum."
                
                conv.desired_date = nlp.parsed_date
                conv.state = "CONFIRM_MODIFY"
                return f"MODIFICATION_REQUEST:{conv.modification_code}:date:{nlp.parsed_date.isoformat()}"
            else:
                return f"Ich habe das Datum nicht verstanden. Bitte nennen Sie ein Datum wie *morgen* oder *25.01.*"
        
        elif conv.modification_field == "time":
            if nlp.time:
                conv.desired_time = nlp.time
                conv.state = "CONFIRM_MODIFY"
                return f"MODIFICATION_REQUEST:{conv.modification_code}:time:{nlp.time}"
            else:
                return f"Ich habe die Uhrzeit nicht verstanden. Bitte nennen Sie eine Zeit wie *19:00* oder *20 Uhr*"
        
        elif conv.modification_field == "party_size":
            if nlp.party_size:
                conv.party_size = nlp.party_size
                conv.state = "CONFIRM_MODIFY"
                return f"MODIFICATION_REQUEST:{conv.modification_code}:party_size:{nlp.party_size}"
            else:
                return f"Ich habe die Personenanzahl nicht verstanden. Bitte nennen Sie eine Zahl wie *5 Personen*"
        
        return f"Es ist ein Fehler aufgetreten. Bitte versuchen Sie es erneut."
    
    def _handle_confirm_modify(
        self,
        conv: ConversationState,
        nlp: NLPResult,
    ) -> str:
        """Behandelt die Bestätigung einer Änderung."""
        
        if nlp.intent == "confirmation":
            conv.state = "INIT"
            return "MODIFICATION_CONFIRMED"
        else:
            conv.state = "MODIFY_SELECT"
            return (
                f"Änderung abgebrochen.\n\n"
                f"Möchten Sie etwas anderes ändern?\n\n"
                f"• *Datum*\n"
                f"• *Uhrzeit*\n"
                f"• *Personenanzahl*\n\n"
                f"Oder sagen Sie *Abbrechen*."
            )
    
    def _determine_next_question(
        self,
        conv: ConversationState,
        restaurant_name: str,
    ) -> str:
        """Bestimmt die nächste Frage basierend auf fehlenden Infos."""
        
        if not conv.desired_date:
            conv.state = "COLLECT_DATE"
            return (
                f"Für welches Datum möchten Sie bei {restaurant_name} reservieren? 📅\n\n"
                f"Z.B. *heute*, *morgen*, *Samstag* oder ein Datum wie *25.01.*"
            )
        
        if not conv.desired_time:
            conv.state = "COLLECT_TIME"
            weekday_name = WEEKDAY_NAMES_DE.get(conv.desired_date.weekday(), "")
            return (
                f"Super, {weekday_name} {conv.desired_date.strftime('%d.%m.%Y')}! ✓\n\n"
                f"Um welche Uhrzeit soll die Reservierung sein? ⏰"
            )
        
        if not conv.party_size:
            conv.state = "COLLECT_SIZE"
            return (
                f"Perfekt, um {conv.desired_time} Uhr! ✓\n\n"
                f"Für wie viele Personen darf ich reservieren? 👥"
            )
        
        if not conv.guest_name:
            conv.state = "COLLECT_NAME"
            return (
                f"Alles klar, {conv.party_size} {'Person' if conv.party_size == 1 else 'Personen'}! ✓\n\n"
                f"Auf welchen Namen soll die Reservierung laufen? 👤"
            )
        
        # Frage nach Sonderwünschen (optional)
        if conv.state != "COLLECT_SPECIAL" and not conv.special_requests:
            conv.state = "COLLECT_SPECIAL"
            return (
                f"Fast geschafft, {conv.guest_name}! 😊\n\n"
                f"Haben Sie besondere Wünsche?\n"
                f"(z.B. Kinderstuhl, Allergien, Fensterplatz)\n\n"
                f"Antworten Sie mit Ihrem Wunsch oder *Nein* zum Überspringen."
            )
        
        # Alle Infos vorhanden -> Bestätigung
        conv.state = "CONFIRM"
        return self._get_confirmation_summary(conv, restaurant_name)
    
    def _get_welcome_message(self, restaurant_name: str) -> str:
        """Erstellt die Willkommensnachricht."""
        return (
            f"Hallo und herzlich willkommen bei {restaurant_name}! 👋\n\n"
            f"Ich bin Ihr Reservierungsassistent und helfe Ihnen gerne.\n\n"
            f"Sie können mir einfach sagen:\n"
            f"*\"Tisch für 4 Personen am Samstag um 19 Uhr\"*\n\n"
            f"Oder wir gehen Schritt für Schritt vor.\n\n"
            f"Für welches Datum möchten Sie reservieren? 📅"
        )
    
    def _get_confirmation_summary(self, conv: ConversationState, restaurant_name: str) -> str:
        """Erstellt die Bestätigungszusammenfassung."""
        weekday_name = WEEKDAY_NAMES_DE.get(conv.desired_date.weekday(), "") if conv.desired_date else ""
        
        special_line = ""
        if conv.special_requests:
            special_line = f"📝 {conv.special_requests}\n"
        
        return (
            f"Perfekt! Hier Ihre Reservierung im Überblick:\n\n"
            f"🍽️ *{restaurant_name}*\n"
            f"📅 {weekday_name}, {conv.desired_date.strftime('%d.%m.%Y')}\n"
            f"⏰ {conv.desired_time} Uhr\n"
            f"👥 {conv.party_size} {'Person' if conv.party_size == 1 else 'Personen'}\n"
            f"👤 {conv.guest_name}\n"
            f"{special_line}\n"
            f"Stimmt das so? Antworten Sie mit *Ja* zum Bestätigen."
        )
    
    def _get_fallback_message(self, restaurant_name: str) -> str:
        """Erstellt die Fallback-Nachricht."""
        return (
            f"Entschuldigung, das habe ich nicht verstanden. 🤔\n\n"
            f"Bei {restaurant_name} kann ich Ihnen helfen mit:\n\n"
            f"• *Reservieren* - Tisch buchen\n"
            f"• *Stornieren* - Reservierung absagen\n"
            f"• *Ändern* - Reservierung anpassen\n\n"
            f"Sagen Sie mir einfach, was Sie möchten!"
        )


# Singleton instance
whatsapp_bot = WhatsAppBotService()
