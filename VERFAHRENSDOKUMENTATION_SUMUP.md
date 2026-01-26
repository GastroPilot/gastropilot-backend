# Verfahrensdokumentation: SumUp Zahlungsintegration und Belegwesen

**Stand:** Januar 2026  
**Version:** 1.0  
**Geltungsbereich:** GastroPilot System mit SumUp Terminal-Integration

---

## 1. Einleitung und Zweck

Diese Verfahrensdokumentation beschreibt die technische Umsetzung und rechtliche Konformität des Zahlungssystems mit SumUp-Terminal-Integration im GastroPilot-System. Sie dient der Nachvollziehbarkeit für Betriebsprüfungen und Kassen-Nachschauen durch das Finanzamt gemäß § 146a AO (Abgabenordnung) und der Kassensicherungsverordnung (KassenSichV).

---

## 2. Rechtliche Grundlagen

### 2.1 Gesetzliche Anforderungen

Das System erfüllt folgende gesetzliche Vorgaben:

- **§ 146a AO**: Anforderungen an elektronische Aufzeichnungs- und Sicherungssysteme
- **KassenSichV** (Kassensicherungsverordnung): TSE-Pflicht seit 1. Januar 2020
- **GoBD** (Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff)
- **Belegausgabepflicht**: Jeder Geschäftsvorfall muss mit Einzelpositionen dokumentiert werden

### 2.2 Zentrale Anforderungen

| Anforderung | Gesetzliche Grundlage | Erfüllung |
|------------|----------------------|-----------|
| Einzelaufzeichnungspflicht | § 146a AO / KassenSichV | ✅ Vollständig erfüllt |
| TSE-Signatur | KassenSichV § 146a AO | ✅ Über SumUp Terminal |
| Belegausgabepflicht | § 146a AO | ✅ PDF-Rechnung mit allen Daten |
| Aufbewahrung (10 Jahre) | § 147 AO | ✅ Datenbank + PDF-Speicherung |
| Einzelpositionen auf Beleg | GoBD / KassenSichV | ✅ Vollständig dokumentiert |

---

## 3. Systemarchitektur

### 3.1 Komponenten

Das System besteht aus folgenden Komponenten:

1. **GastroPilot Backend** (FastAPI)
   - Verwaltung von Bestellungen (Orders)
   - Speicherung von Einzelpositionen (OrderItems)
   - Generierung von PDF-Rechnungen
   - SumUp API-Integration

2. **SumUp Terminal**
   - TSE-zertifiziertes Zahlungsterminal
   - Verarbeitung von Kartenzahlungen
   - Generierung von TSE-Signaturen

3. **Datenbank**
   - PostgreSQL-Datenbank
   - Speicherung aller Transaktionsdaten
   - Langzeitarchivierung (10 Jahre)

### 3.2 Datenfluss

```
1. Bestellung wird erstellt
   ↓
2. OrderItems werden gespeichert (Artikel, Menge, Einzelpreis, MwSt)
   ↓
3. Zahlung wird initiiert → SumUp Checkout erstellt
   ↓
4. Zahlung erfolgt am SumUp Terminal (TSE-Signatur)
   ↓
5. Webhook von SumUp → Receipt-Daten werden abgerufen
   ↓
6. PDF-Rechnung wird generiert (mit allen Einzelpositionen + SumUp-Daten)
   ↓
7. Alle Daten werden in Datenbank gespeichert
```

---

## 4. Belegwesen und Einzelaufzeichnungspflicht

### 4.1 Hauptbeleg: PDF-Rechnung

**WICHTIG:** Die PDF-Rechnung ist der **Hauptbeleg** für die Einzelaufzeichnungspflicht. Sie enthält alle gesetzlich erforderlichen Informationen.

#### 4.1.1 Enthaltene Einzelpositionen

Jede Rechnung enthält eine vollständige Tabelle mit:

- **Artikelbezeichnung** (`item_name`)
- **Artikelbeschreibung** (`item_description`, falls vorhanden)
- **Menge** (`quantity`)
- **Einzelpreis** (`unit_price` inkl. MwSt)
- **Gesamtpreis** (`total_price` inkl. MwSt)
- **MwSt-Satz** (`tax_rate`: 7% oder 19%)
- **Notizen** (`notes`, falls vorhanden)

**Beispiel:**
```
Artikel              | Menge | Einzelpreis | Gesamtpreis
---------------------|-------|-------------|------------
Pizza Margherita     |   2   |   12,50 €   |   25,00 €
Pasta Carbonara      |   1   |   14,90 €   |   14,90 €
```

#### 4.1.2 Weitere Rechnungsbestandteile

- Restaurant-Informationen (Name, Adresse, Kontaktdaten)
- Bestellnummer und Datum
- Tisch-Informationen (falls vorhanden)
- Zwischensumme
- Rabatte (falls vorhanden)
- MwSt-Aufschlüsselung nach Steuersätzen (7% und 19%)
- Trinkgeld (falls vorhanden)
- Gesamtbetrag

### 4.2 SumUp-Zahlungsdaten im Beleg

Nach erfolgreicher Zahlung werden automatisch alle SumUp-Daten abgerufen und im Beleg angezeigt:

#### 4.2.1 Basis-Transaktionsdaten
- **Transaction Code** (z.B. "TEENSK4W2K")
- **Checkout ID**
- **Belegnummer** (Receipt No)
- **Transaktionszeit** (Datum und Uhrzeit)

#### 4.2.2 Zahlungsdetails
- **Zahlungsart** (Karte, Kontaktlos, etc.)
- **Eingabemethode** (Chip, Kontaktlos, Magnetstreifen, Manuell)
- **Verifizierung** (PIN, Unterschrift, Keine)
- **Kartendaten** (letzte 4 Ziffern, Kartentyp)

#### 4.2.3 TSE / Acquirer-Daten
- **Terminal ID (TID)**: Eindeutige Terminal-Identifikation
- **Autorisierungscode**: Von der Bank/Acquirer zurückgegebener Code
- **Return Code**: Status-Code der Transaktion
- **Lokale Zeit**: Zeitstempel des Acquirers

#### 4.2.4 EMV / TSE-Daten
- Alle verfügbaren EMV-Felder (falls vorhanden)
- TSE-relevante Datenstrukturen

#### 4.2.5 MwSt-Aufschlüsselung (SumUp)
- Netto-Beträge nach Steuersätzen
- MwSt-Beträge nach Steuersätzen
- Brutto-Beträge nach Steuersätzen

### 4.3 SumUp Receipt als Ergänzung

**Hinweis:** Der SumUp-Receipt dient als **Zahlungsbeleg** und **ergänzt** die PDF-Rechnung. Er belegt die Zahlungsabwicklung und enthält die TSE-Signatur.

**Wichtig:** Da SumUp's Checkout API keine direkten Line Items unterstützt, können die Einzelpositionen im SumUp-Receipt möglicherweise nicht vollständig erscheinen. **Dies ist rechtlich unproblematisch**, da:

1. Die PDF-Rechnung als Hauptbeleg alle Einzelpositionen vollständig enthält
2. Der SumUp-Receipt primär der Zahlungsabwicklung dient
3. Alle SumUp-Daten (TSE, Transaction Code, etc.) in der PDF-Rechnung dokumentiert sind

---

## 5. Technische Umsetzung

### 5.1 Datenmodell

#### 5.1.1 Order (Bestellung)
```python
- id: Eindeutige Bestellnummer
- order_number: Bestellnummer (z.B. "ORD-2026-001")
- subtotal: Zwischensumme inkl. MwSt
- tax_amount_7: MwSt bei 7% Steuersatz
- tax_amount_19: MwSt bei 19% Steuersatz
- discount_amount: Rabattbetrag
- tip_amount: Trinkgeld
- total: Gesamtbetrag
- payment_method: "sumup_card"
- payment_status: "paid", "partial", "unpaid"
- opened_at: Erstellungszeitpunkt
- paid_at: Zahlungszeitpunkt
```

#### 5.1.2 OrderItem (Einzelposition)
```python
- id: Eindeutige Positionsnummer
- order_id: Verknüpfung zur Bestellung
- item_name: Artikelbezeichnung
- item_description: Artikelbeschreibung
- quantity: Menge
- unit_price: Einzelpreis inkl. MwSt
- total_price: Gesamtpreis inkl. MwSt
- tax_rate: MwSt-Satz (0.07 oder 0.19)
- category: Kategorie (optional)
- notes: Notizen (optional)
```

#### 5.1.3 SumUpPayment (Zahlungsdaten)
```python
- id: Eindeutige Zahlungs-ID
- order_id: Verknüpfung zur Bestellung
- checkout_id: SumUp Checkout ID
- transaction_code: SumUp Transaction Code
- transaction_id: SumUp Transaction ID
- reader_id: Terminal ID (falls vorhanden)
- amount: Zahlungsbetrag
- currency: Währung (EUR)
- status: "successful", "failed", "pending", "canceled"
- webhook_data: JSON mit vollständigen Receipt-Daten
  - receipt_data: Vollständiger SumUp Receipt
    - transaction_data: Transaktionsdetails
    - merchant_data: Merchant-Informationen
    - emv_data: EMV/TSE-Daten
    - acquirer_data: Acquirer-Daten (TID, Authorization Code, etc.)
  - receipt_items: Line Items aus Receipt (falls vorhanden)
  - receipt_no: Belegnummer
- initiated_at: Initiierungszeitpunkt
- completed_at: Abschlusszeitpunkt
```

### 5.2 Zahlungsprozess

#### Schritt 1: Checkout-Erstellung
1. Backend lädt alle `OrderItems` der Bestellung
2. Items werden in SumUp-Format konvertiert (Netto-Preise)
3. Items werden als `metadata` an SumUp übergeben:
   - `metadata.order_items`: Original-Items (inkl. MwSt)
   - `metadata.products`: SumUp Receipt-Format (Netto-Preise)
4. Checkout wird erstellt (mit oder ohne Reader, je nach Test-/Produktionsmodus)
5. `SumUpPayment`-Eintrag wird erstellt (Status: "pending")

#### Schritt 2: Zahlung am Terminal
1. Kunde zahlt am SumUp Terminal
2. Terminal generiert TSE-Signatur
3. Zahlung wird von SumUp verarbeitet

#### Schritt 3: Webhook-Verarbeitung
1. SumUp sendet Webhook an Backend (`/v1/webhooks/sumup`)
2. Webhook wird verifiziert (Signature Verification)
3. Bei erfolgreicher Zahlung (`status: "PAID"`):
   - `SumUpPayment.status` wird auf "successful" gesetzt
   - Transaction Code wird gespeichert
   - **Vollständiger Receipt wird von SumUp abgerufen** (`GET /v1.1/receipts/{transaction_code}`)
   - Alle Receipt-Daten werden in `webhook_data.receipt_data` gespeichert
   - Order wird als "paid" markiert

#### Schritt 4: Rechnungsgenerierung
1. PDF-Rechnung wird generiert (`GET /restaurants/{restaurant_id}/invoices/{order_id}/pdf`)
2. Alle `OrderItems` werden als Tabelle eingefügt
3. SumUp-Daten werden aus `SumUpPayment.webhook_data.receipt_data` geladen
4. Alle SumUp-Daten werden im Beleg angezeigt:
   - Transaction Code, Checkout ID, Belegnummer
   - Transaktionsdetails (Zeit, Zahlungsart, Eingabemethode)
   - TSE-Daten (Terminal ID, Authorization Code, Return Code)
   - EMV-Daten (falls vorhanden)
   - MwSt-Aufschlüsselung

### 5.3 API-Endpunkte

#### Rechnungsgenerierung
```
GET /restaurants/{restaurant_id}/invoices/{order_id}/pdf
```
- Generiert PDF-Rechnung mit allen Einzelpositionen und SumUp-Daten
- Erfordert Authentifizierung und Berechtigung

#### SumUp-Zahlung initiieren
```
POST /restaurants/{restaurant_id}/sumup/orders/{order_id}/pay
```
- Erstellt SumUp Checkout
- Übergibt OrderItems als Metadata
- Gibt Checkout ID zurück

#### Webhook-Empfang
```
POST /v1/webhooks/sumup
```
- Empfängt SumUp Webhooks
- Verifiziert Signature
- Verarbeitet Zahlungsstatus
- Ruft Receipt-Daten ab

---

## 6. Datenaufbewahrung und Archivierung

### 6.1 Aufbewahrungsfristen

Gemäß § 147 AO müssen alle Belege und Aufzeichnungen **mindestens 10 Jahre** aufbewahrt werden.

### 6.2 Gespeicherte Daten

#### Datenbank (PostgreSQL)
- Alle `Order`-Einträge (mit Timestamps)
- Alle `OrderItem`-Einträge (Einzelpositionen)
- Alle `SumUpPayment`-Einträge (inkl. vollständiger `webhook_data`)

#### PDF-Rechnungen
- Werden bei Bedarf generiert
- Können für Archivierung exportiert werden
- Enthalten alle gesetzlich erforderlichen Informationen

### 6.3 Datenintegrität

- Alle Daten werden unveränderbar in der Datenbank gespeichert
- Timestamps werden automatisch gesetzt (`created_at_utc`, `updated_at_utc`)
- SumUp-Daten werden unverändert aus dem Receipt übernommen
- Keine manuelle Nachbearbeitung möglich

---

## 7. Konformität mit gesetzlichen Anforderungen

### 7.1 Einzelaufzeichnungspflicht (§ 146a AO)

✅ **ERFÜLLT**

- Jede Bestellung enthält vollständige Liste aller Einzelpositionen
- Jede Position enthält: Artikel, Menge, Einzelpreis, Gesamtpreis, MwSt-Satz
- Alle Positionen werden in der PDF-Rechnung dokumentiert
- Daten sind in der Datenbank dauerhaft gespeichert

### 7.2 TSE-Pflicht (KassenSichV)

✅ **ERFÜLLT**

- SumUp Terminal ist TSE-zertifiziert
- Jede Zahlung erhält TSE-Signatur
- Terminal ID (TID) wird im Beleg dokumentiert
- Authorization Code und Return Code werden gespeichert

### 7.3 Belegausgabepflicht (§ 146a AO)

✅ **ERFÜLLT**

- PDF-Rechnung wird für jeden Geschäftsvorfall generiert
- Rechnung enthält alle gesetzlich erforderlichen Informationen
- Rechnung kann dem Kunden ausgehändigt werden (Papier oder elektronisch)
- SumUp-Receipt ergänzt die Rechnung als Zahlungsbeleg

### 7.4 GoBD-Konformität

✅ **ERFÜLLT**

- **Vollständigkeit**: Alle Transaktionen werden erfasst
- **Richtigkeit**: Daten werden unverändert gespeichert
- **Nachvollziehbarkeit**: Jede Position ist einzeln nachvollziehbar
- **Unveränderbarkeit**: Daten werden nicht nachträglich geändert
- **Aufbewahrung**: 10 Jahre Aufbewahrungsfrist wird eingehalten

---

## 8. Verfahren bei Finanzamtprüfung

### 8.1 Vorbereitung

Bei einer Kassen-Nachschau oder Betriebsprüfung können folgende Dokumente vorgelegt werden:

1. **Verfahrensdokumentation** (dieses Dokument)
2. **Beispiel-Rechnungen** (PDF mit allen Einzelpositionen)
3. **Datenbank-Auszüge** (falls erforderlich)
4. **SumUp-Receipts** (als Zahlungsbelege)

### 8.2 Nachweis der Einzelpositionen

**Frage:** "Wo sind die Einzelpositionen dokumentiert?"

**Antwort:** 
- Alle Einzelpositionen sind in der **PDF-Rechnung** vollständig dokumentiert
- Jede Position enthält: Artikel, Menge, Einzelpreis, Gesamtpreis, MwSt-Satz
- Die Daten sind in der Datenbank gespeichert und können jederzeit abgerufen werden
- Die Rechnung kann für jede Bestellung generiert werden: `GET /restaurants/{restaurant_id}/invoices/{order_id}/pdf`

### 8.3 Nachweis der TSE-Konformität

**Frage:** "Wie wird die TSE-Pflicht erfüllt?"

**Antwort:**
- Das SumUp Terminal ist TSE-zertifiziert
- Jede Zahlung erhält eine TSE-Signatur
- Die Terminal ID (TID) wird im Beleg dokumentiert
- Alle TSE-relevanten Daten (Authorization Code, Return Code, EMV-Daten) werden in der PDF-Rechnung angezeigt

### 8.4 Nachweis der Vollständigkeit

**Frage:** "Sind alle Transaktionen erfasst?"

**Antwort:**
- Alle Bestellungen werden in der Datenbank gespeichert (`Order`-Tabelle)
- Alle Zahlungen werden dokumentiert (`SumUpPayment`-Tabelle)
- Jede Zahlung ist mit einer Bestellung verknüpft (`order_id`)
- Alle Daten sind mit Timestamps versehen und unveränderbar

---

## 9. Besonderheiten und Limitationen

### 9.1 SumUp API-Limitationen

**Limitation:** SumUp's Checkout API unterstützt keine direkten "Line Items" beim Erstellen des Checkouts.

**Lösung:**
- Items werden als `metadata` übergeben
- Items werden zusätzlich in der `description` als Text eingefügt
- Nach erfolgreicher Zahlung wird der vollständige Receipt abgerufen
- **Alle Einzelpositionen sind in der PDF-Rechnung vollständig dokumentiert**

### 9.2 Rechtliche Bewertung

**Ist es rechtlich problematisch, dass SumUp-Receipts möglicherweise keine Einzelpositionen enthalten?**

**Nein, aus folgenden Gründen:**

1. **PDF-Rechnung ist Hauptbeleg**: Die PDF-Rechnung enthält alle Einzelpositionen vollständig und erfüllt die Einzelaufzeichnungspflicht.

2. **SumUp-Receipt ist Zahlungsbeleg**: Der SumUp-Receipt dient primär der Dokumentation der Zahlungsabwicklung und TSE-Signatur.

3. **Vollständige Dokumentation**: Alle SumUp-Daten (TSE, Transaction Code, Terminal ID, etc.) sind in der PDF-Rechnung dokumentiert.

4. **GoBD-Konformität**: Das System erfüllt alle GoBD-Anforderungen durch die vollständige Dokumentation in der PDF-Rechnung.

**Fazit:** Die Kombination aus PDF-Rechnung (Hauptbeleg mit Einzelpositionen) und SumUp-Receipt (Zahlungsbeleg mit TSE-Signatur) erfüllt alle gesetzlichen Anforderungen.

---

## 10. Wartung und Aktualisierung

### 10.1 Regelmäßige Prüfungen

- **Monatlich**: Prüfung der Datenintegrität
- **Quartal**: Prüfung der SumUp-API-Konnektivität
- **Jährlich**: Review der Verfahrensdokumentation

### 10.2 Änderungen dokumentieren

Alle Änderungen am System müssen in dieser Dokumentation aktualisiert werden:
- Änderungen am Datenmodell
- Änderungen am Zahlungsprozess
- Änderungen an der Rechnungsgenerierung
- Änderungen an der SumUp-Integration

---

## 11. Anhang

### 11.1 Technische Details

- **Backend-Framework**: FastAPI (Python)
- **Datenbank**: PostgreSQL
- **PDF-Generierung**: ReportLab
- **SumUp API**: REST API v0.1 (Checkouts), v1.1 (Receipts), v2.1 (Transactions)

### 11.2 Dateien und Code-Stellen

- **Rechnungsgenerierung**: `app/routers/invoices.py`
- **SumUp-Integration**: `app/routers/sumup.py`
- **Webhook-Verarbeitung**: `app/routers/webhook_sumup.py`
- **SumUp-Service**: `app/services/sumup_service.py`
- **Datenmodelle**: `app/database/models.py`
  - `Order`: Bestellungen
  - `OrderItem`: Einzelpositionen
  - `SumUpPayment`: Zahlungsdaten

### 11.3 Kontakt und Support

Bei Fragen zur Verfahrensdokumentation oder technischen Details:
- Siehe: `SUMUP_SETUP.md` für Setup-Anleitung
- Siehe: `SUMUP_POSTMAN_EXAMPLES.md` für API-Beispiele

---

**Ende der Verfahrensdokumentation**

*Diese Dokumentation wurde erstellt, um die Konformität mit § 146a AO, KassenSichV und GoBD nachzuweisen. Sie sollte bei Finanzamtprüfungen vorgelegt werden können.*
