"""
AI Service für intelligente Tischzuordnung.

Nutzt OpenAI GPT-4o-mini für kontextbasierte Vorschläge,
welcher Tisch für eine neue Bestellung am wahrscheinlichsten ist.
"""

import logging
from datetime import UTC, datetime

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TableSuggestion(BaseModel):
    """Ein Tischvorschlag mit Confidence Score."""

    table_id: int
    table_number: str
    confidence: float  # 0.0 - 1.0
    reason: str  # Kurze Begründung
    guest_name: str | None = None
    reservation_id: int | None = None


class TableContext(BaseModel):
    """Kontext eines Tisches für die KI."""

    id: int
    number: str
    capacity: int
    status: str  # "free", "occupied", "reserved"
    current_guest: str | None = None
    has_active_order: bool = False


class ReservationContext(BaseModel):
    """Kontext einer Reservierung für die KI."""

    id: int
    table_id: int | None
    guest_name: str | None
    party_size: int
    status: str
    start_at: str
    end_at: str


class OrderContext(BaseModel):
    """Kontext einer Bestellung für die KI."""

    id: int
    table_id: int | None
    status: str
    items_count: int


class RestaurantContext(BaseModel):
    """Gesamter Restaurant-Kontext für die KI-Anfrage."""

    tables: list[TableContext]
    active_reservations: list[ReservationContext]
    pending_orders: list[OrderContext]
    current_time: str
    context_hint: str | None = None  # Optionaler Hinweis vom Benutzer


class AIService:
    """
    Service für KI-gestützte Funktionen.

    Verwendet OpenAI GPT-4o-mini für:
    - Tischvorschläge basierend auf aktuellem Restaurant-Kontext
    """

    def __init__(self):
        self._client = None
        self._enabled = False
        self._model = "gpt-4o-mini"
        self._max_tokens = 500
        self._temperature = 0.3

    def _get_client(self):
        """Lazy-Load des OpenAI Clients."""
        if self._client is None:
            from app.settings import (
                AI_ENABLED,
                AI_MAX_TOKENS,
                AI_MODEL,
                AI_TEMPERATURE,
                OPENAI_API_KEY,
            )

            self._enabled = AI_ENABLED
            self._model = AI_MODEL
            self._max_tokens = AI_MAX_TOKENS
            self._temperature = AI_TEMPERATURE

            if self._enabled and OPENAI_API_KEY:
                try:
                    from openai import OpenAI

                    self._client = OpenAI(api_key=OPENAI_API_KEY)
                    logger.info(f"AI Service initialized with model: {self._model}")
                except ImportError:
                    logger.warning("OpenAI package not installed. AI features disabled.")
                    self._enabled = False
                except Exception as e:
                    logger.error(f"Failed to initialize OpenAI client: {e}")
                    self._enabled = False
            else:
                if not self._enabled:
                    logger.info("AI Service disabled via configuration")
                elif not OPENAI_API_KEY:
                    logger.warning("OPENAI_API_KEY not set. AI features disabled.")
                    self._enabled = False

        return self._client

    @property
    def is_enabled(self) -> bool:
        """Prüft ob der AI Service aktiviert und konfiguriert ist."""
        self._get_client()  # Initialisiert _enabled
        return self._enabled

    def _build_system_prompt(self) -> str:
        """Erstellt den System-Prompt für die Tischzuordnung."""
        return """Du bist ein intelligenter Assistent für ein Restaurant-Management-System.
Deine Aufgabe ist es, basierend auf dem aktuellen Restaurant-Kontext den wahrscheinlichsten Tisch für eine neue Bestellung vorzuschlagen.

Regeln für die Zuordnung:
1. Bevorzuge Tische mit aktiven Reservierungen im Status "seated" (Gäste sitzen bereits)
2. Wenn ein Tisch eine aktive Reservierung hat aber noch keine offene Bestellung, ist das ein sehr guter Kandidat
3. Berücksichtige den context_hint falls vorhanden (z.B. Gästename)
4. Tische mit Status "free" und ohne Reservierung sind weniger wahrscheinlich
5. Tische die bereits eine offene Bestellung haben, bekommen niedrigere Confidence

Gib IMMER genau 3 Vorschläge zurück, sortiert nach Confidence (höchste zuerst).
Jeder Vorschlag muss eine Begründung auf Deutsch enthalten.

Antworte NUR mit einem JSON-Array im folgenden Format:
[
  {
    "table_id": 1,
    "table_number": "01",
    "confidence": 0.92,
    "reason": "Reservierung für Familie Müller seit 18:00 aktiv, noch keine Bestellung",
    "guest_name": "Müller",
    "reservation_id": 123
  }
]"""

    def _build_user_prompt(self, context: RestaurantContext) -> str:
        """Erstellt den User-Prompt mit dem Restaurant-Kontext."""
        tables_info = []
        for t in context.tables:
            info = f"- Tisch {t.number}: Kapazität {t.capacity}, Status: {t.status}"
            if t.current_guest:
                info += f", Gast: {t.current_guest}"
            if t.has_active_order:
                info += ", hat bereits offene Bestellung"
            tables_info.append(info)

        reservations_info = []
        for r in context.active_reservations:
            info = f"- Reservierung #{r.id}: Tisch {r.table_id or 'nicht zugewiesen'}, "
            info += f"Gast: {r.guest_name or 'unbekannt'}, {r.party_size} Personen, "
            info += f"Status: {r.status}, {r.start_at} - {r.end_at}"
            reservations_info.append(info)

        orders_info = []
        for o in context.pending_orders:
            info = f"- Bestellung #{o.id}: Tisch {o.table_id or 'keiner'}, "
            info += f"Status: {o.status}, {o.items_count} Positionen"
            orders_info.append(info)

        prompt = f"""Aktuelle Uhrzeit: {context.current_time}

TISCHE:
{chr(10).join(tables_info) if tables_info else "Keine Tische verfügbar"}

AKTIVE RESERVIERUNGEN:
{chr(10).join(reservations_info) if reservations_info else "Keine aktiven Reservierungen"}

OFFENE BESTELLUNGEN:
{chr(10).join(orders_info) if orders_info else "Keine offenen Bestellungen"}
"""

        if context.context_hint:
            prompt += f"\nHINWEIS VOM BENUTZER: {context.context_hint}"

        prompt += "\n\nWelche 3 Tische sind am wahrscheinlichsten für eine neue Bestellung?"

        return prompt

    async def suggest_tables(
        self,
        context: RestaurantContext,
    ) -> list[TableSuggestion]:
        """
        Schlägt die wahrscheinlichsten Tische für eine neue Bestellung vor.

        Args:
            context: Der aktuelle Restaurant-Kontext

        Returns:
            Liste von bis zu 3 Tischvorschlägen, sortiert nach Confidence
        """
        client = self._get_client()

        if not self._enabled or client is None:
            logger.warning("AI Service not available, returning empty suggestions")
            return []

        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(context)

            logger.debug(f"AI Request - User prompt length: {len(user_prompt)}")

            response = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            logger.debug(f"AI Response: {content}")

            # Parse JSON response
            import json

            data = json.loads(content)

            # Handle both array and object with "suggestions" key
            suggestions_data = data if isinstance(data, list) else data.get("suggestions", [])

            suggestions = []
            for item in suggestions_data[:3]:  # Max 3 suggestions
                try:
                    suggestion = TableSuggestion(
                        table_id=item["table_id"],
                        table_number=str(item["table_number"]),
                        confidence=min(1.0, max(0.0, float(item["confidence"]))),
                        reason=item["reason"],
                        guest_name=item.get("guest_name"),
                        reservation_id=item.get("reservation_id"),
                    )
                    suggestions.append(suggestion)
                except (KeyError, ValueError) as e:
                    logger.warning(f"Invalid suggestion item: {item}, error: {e}")
                    continue

            # Sort by confidence descending
            suggestions.sort(key=lambda x: x.confidence, reverse=True)

            logger.info(
                f"AI suggested {len(suggestions)} tables, top confidence: "
                f"{suggestions[0].confidence if suggestions else 'N/A'}"
            )

            return suggestions

        except Exception as e:
            logger.error(f"AI suggestion failed: {e}", exc_info=True)
            return []

    def build_context_from_data(
        self,
        tables: list[dict],
        reservations: list[dict],
        orders: list[dict],
        context_hint: str | None = None,
    ) -> RestaurantContext:
        """
        Baut den Restaurant-Kontext aus den Rohdaten.

        Args:
            tables: Liste von Tisch-Dicts aus der Datenbank
            reservations: Liste von Reservierungs-Dicts
            orders: Liste von Bestellungs-Dicts
            context_hint: Optionaler Hinweis vom Benutzer

        Returns:
            RestaurantContext für die KI-Anfrage
        """
        now = datetime.now(UTC)

        # Ermittle welche Tische aktive Bestellungen haben
        tables_with_orders = {
            o.get("table_id")
            for o in orders
            if o.get("table_id") and o.get("status") not in ("paid", "canceled")
        }

        # Ermittle aktive Reservierungen pro Tisch
        active_reservations_by_table = {}
        for r in reservations:
            if r.get("status") in ("confirmed", "seated"):
                table_id = r.get("table_id")
                if table_id:
                    active_reservations_by_table[table_id] = r

        # Baue Tisch-Kontext
        table_contexts = []
        for t in tables:
            if not t.get("is_active", True):
                continue

            table_id = t["id"]
            active_res = active_reservations_by_table.get(table_id)

            if active_res and active_res.get("status") == "seated":
                status = "occupied"
                guest_name = active_res.get("guest_name")
            elif active_res:
                status = "reserved"
                guest_name = active_res.get("guest_name")
            else:
                status = "free"
                guest_name = None

            table_contexts.append(
                TableContext(
                    id=table_id,
                    number=t.get("number", str(table_id)),
                    capacity=t.get("capacity", 0),
                    status=status,
                    current_guest=guest_name,
                    has_active_order=table_id in tables_with_orders,
                )
            )

        # Baue Reservierungs-Kontext
        reservation_contexts = []
        for r in reservations:
            if r.get("status") in ("confirmed", "seated"):
                reservation_contexts.append(
                    ReservationContext(
                        id=r["id"],
                        table_id=r.get("table_id"),
                        guest_name=r.get("guest_name"),
                        party_size=r.get("party_size", 0),
                        status=r.get("status", ""),
                        start_at=r.get("start_at", "")[:16] if r.get("start_at") else "",
                        end_at=r.get("end_at", "")[:16] if r.get("end_at") else "",
                    )
                )

        # Baue Bestellungs-Kontext
        order_contexts = []
        for o in orders:
            if o.get("status") not in ("paid", "canceled"):
                order_contexts.append(
                    OrderContext(
                        id=o["id"],
                        table_id=o.get("table_id"),
                        status=o.get("status", ""),
                        items_count=len(o.get("items", [])) if "items" in o else 0,
                    )
                )

        return RestaurantContext(
            tables=table_contexts,
            active_reservations=reservation_contexts,
            pending_orders=order_contexts,
            current_time=now.strftime("%H:%M"),
            context_hint=context_hint,
        )

    async def suggest_table_for_reservation(
        self,
        tables: list[dict],
        reservations: list[dict],
        blocks: list[dict],
        block_assignments: list[dict],
        desired_datetime: datetime,
        end_datetime: datetime,
        party_size: int,
        preferences: dict | None = None,
    ) -> "TableAssignmentResult":
        """
        Wählt automatisch den besten Tisch für eine neue Reservierung.

        Diese Methode kombiniert regelbasierte Logik mit optionaler KI-Unterstützung:
        1. Filtert Tische nach Kapazität
        2. Prüft auf überlappende Reservierungen
        3. Prüft auf Blockierungen
        4. Wählt optimalen Tisch (kleinster passender)

        Args:
            tables: Liste aller Tische
            reservations: Liste bestehender Reservierungen
            blocks: Liste von Blockierungen
            block_assignments: Zuordnung Blockierungen zu Tischen
            desired_datetime: Gewünschter Startzeitpunkt
            end_datetime: Endzeitpunkt der Reservierung
            party_size: Anzahl Personen
            preferences: Optionale Präferenzen (z.B. {"outdoor": True})

        Returns:
            TableAssignmentResult mit bestem Tisch oder Fehler
        """
        # Filtere aktive Tische mit ausreichender Kapazität
        suitable_tables = [
            t for t in tables if t.get("is_active", True) and t.get("capacity", 0) >= party_size
        ]

        if not suitable_tables:
            return TableAssignmentResult(
                success=False,
                reason="Kein Tisch mit ausreichender Kapazität verfügbar",
            )

        # Sortiere nach Kapazität (kleinster zuerst für optimale Auslastung)
        suitable_tables.sort(key=lambda t: t.get("capacity", 0))

        # Erstelle Set von blockierten Tisch-IDs im Zeitraum
        blocked_table_ids = set()
        for block in blocks:
            block_start = block.get("start_at")
            block_end = block.get("end_at")

            # Parse datetime strings if needed
            if isinstance(block_start, str):
                block_start = datetime.fromisoformat(block_start.replace("Z", "+00:00"))
            if isinstance(block_end, str):
                block_end = datetime.fromisoformat(block_end.replace("Z", "+00:00"))

            # Prüfe Überlappung
            if block_start < end_datetime and block_end > desired_datetime:
                # Block überschneidet sich mit gewünschtem Zeitraum
                block_id = block.get("id")
                for ba in block_assignments:
                    if ba.get("block_id") == block_id:
                        blocked_table_ids.add(ba.get("table_id"))

        # Erstelle Set von reservierten Tisch-IDs im Zeitraum
        reserved_table_ids = set()
        for res in reservations:
            if res.get("status") in ("pending", "confirmed", "seated"):
                res_start = res.get("start_at")
                res_end = res.get("end_at")

                if isinstance(res_start, str):
                    res_start = datetime.fromisoformat(res_start.replace("Z", "+00:00"))
                if isinstance(res_end, str):
                    res_end = datetime.fromisoformat(res_end.replace("Z", "+00:00"))

                # Prüfe Überlappung
                if res_start < end_datetime and res_end > desired_datetime:
                    table_id = res.get("table_id")
                    if table_id:
                        reserved_table_ids.add(table_id)

        # Finde verfügbare Tische
        available_tables = []
        for table in suitable_tables:
            table_id = table.get("id")
            if table_id not in blocked_table_ids and table_id not in reserved_table_ids:
                available_tables.append(table)

        if not available_tables:
            return TableAssignmentResult(
                success=False,
                reason="Alle passenden Tische sind bereits reserviert oder blockiert",
            )

        # Wähle besten Tisch
        # Hier könnte KI für komplexere Entscheidungen eingesetzt werden
        best_table = available_tables[0]  # Kleinster verfügbarer

        # Berücksichtige Präferenzen wenn vorhanden
        if preferences:
            if preferences.get("outdoor"):
                outdoor_tables = [t for t in available_tables if t.get("is_outdoor")]
                if outdoor_tables:
                    best_table = outdoor_tables[0]
            elif preferences.get("indoor"):
                indoor_tables = [t for t in available_tables if not t.get("is_outdoor")]
                if indoor_tables:
                    best_table = indoor_tables[0]

        # Tischname formatieren (vermeide "Tisch Tisch 2")
        table_num = best_table.get("number", "")
        table_display = (
            table_num if str(table_num).lower().startswith("tisch") else f"Tisch {table_num}"
        )

        return TableAssignmentResult(
            success=True,
            table_id=best_table.get("id"),
            table_number=best_table.get("number"),
            start_at=desired_datetime,
            end_at=end_datetime,
            confidence=0.95,
            reason=f"{table_display} mit {best_table.get('capacity')} Plätzen ausgewählt",
            alternatives=[
                {
                    "table_id": t.get("id"),
                    "table_number": t.get("number"),
                    "capacity": t.get("capacity"),
                }
                for t in available_tables[1:4]  # Nächste 3 Alternativen
            ],
        )


class TableAssignmentResult(BaseModel):
    """Ergebnis der automatischen Tischzuordnung."""

    success: bool
    table_id: int | None = None
    table_number: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    confidence: float = 0.0
    reason: str = ""
    alternatives: list[dict] = []


# Singleton-Instanz
ai_service = AIService()
