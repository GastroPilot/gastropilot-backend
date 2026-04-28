"""Unit tests for the allergen-safety service.

Covers the four risk-level transitions for ``check_item_safety``:

- ``safe`` — Item hat dokumentierte Allergene/Zutaten, aber kein Match auf
  das Gastprofil.
- ``warning`` — Match nur in ``ingredients[*].may_contain`` (Spurenwarnung).
- ``danger`` — direkter Match zwischen Gast- und Item-Allergenen.
- ``unknown`` — weder ``allergens`` noch ``ingredients`` sind gepflegt.

Plus DE↔EN-Aliase: Gastprofil "lactose" muss auf Item "milch" matchen und
umgekehrt.

Die Funktion ist rein synchron und ohne Datenbank-Side-Effects, daher kommt
hier (anders als in den anderen Tests im selben Verzeichnis) keine
``_FakeSession`` zum Einsatz.
"""

from __future__ import annotations

from app.services.allergen_service import _normalize_allergen, check_item_safety


def test_safe_item_has_documented_allergens_but_no_match() -> None:
    is_safe, matched, risk, may_contain = check_item_safety(
        item_allergens=["gluten"],
        item_ingredients=[],
        guest_allergens=["milk"],
    )

    assert is_safe is True
    assert matched == []
    assert risk == "safe"
    assert may_contain == []


def test_warning_when_only_may_contain_overlaps() -> None:
    is_safe, matched, risk, may_contain = check_item_safety(
        item_allergens=["gluten"],
        item_ingredients=[
            {
                "name": "Schokoglasur",
                "allergens": [],
                "may_contain": ["nuts"],
            }
        ],
        guest_allergens=["nuts"],
    )

    # is_safe stays True (no direct allergen match) but the caller MUST treat
    # may_contain as a soft warning. The risk_level is the discriminator.
    assert is_safe is True
    assert matched == []
    assert risk == "warning"
    assert may_contain == ["nuts"]


def test_danger_on_direct_match() -> None:
    is_safe, matched, risk, may_contain = check_item_safety(
        item_allergens=["milk", "gluten"],
        item_ingredients=[],
        guest_allergens=["milk"],
    )

    assert is_safe is False
    assert matched == ["milk"]
    assert risk == "danger"
    assert may_contain == []


def test_de_en_alias_lactose_matches_milch() -> None:
    """Gast-Profil ``lactose`` (EN) muss auf Item ``milch`` (DE) matchen."""
    is_safe, matched, risk, _ = check_item_safety(
        item_allergens=["milch"],
        item_ingredients=[],
        guest_allergens=["lactose"],
    )

    assert is_safe is False
    assert matched == ["milk"]  # canonical EU-14 EN-Singular
    assert risk == "danger"


def test_de_en_alias_milch_matches_lactose() -> None:
    """Und umgekehrt: Gast-Profil ``milch`` muss auf Item ``lactose`` matchen."""
    is_safe, matched, risk, _ = check_item_safety(
        item_allergens=["lactose"],
        item_ingredients=[],
        guest_allergens=["milch"],
    )

    assert is_safe is False
    assert matched == ["milk"]
    assert risk == "danger"


def test_unknown_when_item_has_no_allergens_and_no_ingredients() -> None:
    """Wenn nichts gepflegt ist, ist eine Aussage nicht möglich → ``unknown``.

    Vorher hat ``check_item_safety`` für diesen Fall ``safe`` zurückgegeben,
    was guests in ein falsches Sicherheitsgefühl wiegt.
    """
    is_safe, matched, risk, may_contain = check_item_safety(
        item_allergens=[],
        item_ingredients=[],
        guest_allergens=["nuts"],
    )

    # ``is_safe`` reflektiert nur das Fehlen direkter Matches — Frontend muss
    # zusätzlich auf ``risk_level == "unknown"`` reagieren.
    assert is_safe is True
    assert matched == []
    assert risk == "unknown"
    assert may_contain == []


def test_unknown_also_when_ingredients_is_empty_list_and_allergens_blank() -> None:
    """Whitespace-only / leere Strings dürfen nicht als 'gepflegt' gewertet."""
    is_safe, _matched, risk, _may = check_item_safety(
        item_allergens=["", "  "],
        item_ingredients=[],
        guest_allergens=["milk"],
    )

    assert is_safe is True
    assert risk == "unknown"


def test_unknown_falls_back_to_safe_when_ingredients_documented() -> None:
    """Sobald Zutaten gepflegt sind (auch ohne Match), ist die Aussage belastbar."""
    is_safe, _matched, risk, _may = check_item_safety(
        item_allergens=[],
        item_ingredients=[{"name": "Tomate", "allergens": []}],
        guest_allergens=["milk"],
    )

    assert is_safe is True
    assert risk == "safe"


def test_normalize_allergen_aliases_to_eu14_en_singular() -> None:
    assert _normalize_allergen("lactose") == "milk"
    assert _normalize_allergen("Milch") == "milk"
    assert _normalize_allergen("Erdnüsse") == "peanuts"
    assert _normalize_allergen("peanut") == "peanuts"
    assert _normalize_allergen("schalenfrüchte") == "nuts"
    # Unbekannte Codes überleben (lower-case).
    assert _normalize_allergen("custom_x") == "custom_x"
    # Empty input safely returns empty string.
    assert _normalize_allergen("") == ""
