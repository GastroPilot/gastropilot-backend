-- Performance-Indizes für GastroPilot
-- Diese Indizes verbessern die Query-Performance für häufige Abfragen

-- ============================================
-- RESERVATIONS
-- ============================================

-- Index für Datumsfilterung (häufigste Query)
CREATE INDEX IF NOT EXISTS idx_reservations_restaurant_start_at 
ON reservations(restaurant_id, start_at);

-- Index für Status-Filter
CREATE INDEX IF NOT EXISTS idx_reservations_restaurant_status 
ON reservations(restaurant_id, status);

-- Composite Index für Dashboard-Queries (restaurant + date + status)
CREATE INDEX IF NOT EXISTS idx_reservations_dashboard 
ON reservations(restaurant_id, start_at, status);

-- Index für Tisch-Zuordnung
CREATE INDEX IF NOT EXISTS idx_reservations_table_start 
ON reservations(table_id, start_at) WHERE table_id IS NOT NULL;


-- ============================================
-- ORDERS
-- ============================================

-- Index für aktive Bestellungen
CREATE INDEX IF NOT EXISTS idx_orders_restaurant_status 
ON orders(restaurant_id, status);

-- Index für Tisch-Bestellungen
CREATE INDEX IF NOT EXISTS idx_orders_table_status 
ON orders(table_id, status) WHERE table_id IS NOT NULL;

-- Index für Datum (für Statistiken)
CREATE INDEX IF NOT EXISTS idx_orders_restaurant_opened 
ON orders(restaurant_id, opened_at);

-- Index für bezahlte Bestellungen (für Umsatz-Queries)
CREATE INDEX IF NOT EXISTS idx_orders_paid 
ON orders(restaurant_id, paid_at) WHERE status = 'paid';


-- ============================================
-- ORDER ITEMS
-- ============================================

-- Index für Bestellung → Items
CREATE INDEX IF NOT EXISTS idx_order_items_order_status 
ON order_items(order_id, status);


-- ============================================
-- TABLES
-- ============================================

-- Index für aktive Tische
CREATE INDEX IF NOT EXISTS idx_tables_restaurant_active 
ON tables(restaurant_id, is_active);

-- Index für Bereich
CREATE INDEX IF NOT EXISTS idx_tables_area 
ON tables(area_id) WHERE area_id IS NOT NULL;


-- ============================================
-- TABLE_DAY_CONFIGS
-- ============================================

-- Composite Index für Tages-Abfragen
CREATE INDEX IF NOT EXISTS idx_table_day_configs_lookup 
ON table_day_configs(restaurant_id, date, table_id);

-- Index für temporäre Tische
CREATE INDEX IF NOT EXISTS idx_table_day_configs_temp 
ON table_day_configs(restaurant_id, date) WHERE is_temporary = true;


-- ============================================
-- BLOCKS
-- ============================================

-- Index für Zeitraum-Abfragen
CREATE INDEX IF NOT EXISTS idx_blocks_restaurant_time 
ON blocks(restaurant_id, start_at, end_at);


-- ============================================
-- BLOCK_ASSIGNMENTS
-- ============================================

-- Index für Tisch → Blocks
CREATE INDEX IF NOT EXISTS idx_block_assignments_table 
ON block_assignments(table_id, block_id);


-- ============================================
-- AUDIT_LOGS
-- ============================================

-- Index für Zeitraum-Abfragen
CREATE INDEX IF NOT EXISTS idx_audit_logs_restaurant_time 
ON audit_logs(restaurant_id, created_at_utc DESC);

-- Index für Entity-Abfragen
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity 
ON audit_logs(entity_type, entity_id);


-- ============================================
-- REFRESH_TOKENS
-- ============================================

-- Index für Token-Lookup (häufig bei Auth)
-- Bereits vorhanden durch unique constraint, aber stellen wir sicher
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_expires 
ON refresh_tokens(user_id, expires_at) WHERE revoked_at IS NULL;


-- ============================================
-- NOTES
-- ============================================
-- 
-- Ausführung:
-- PostgreSQL: psql -d <database> -f performance_indexes.sql
-- SQLite: sqlite3 <database.db> < performance_indexes.sql
--
-- Diese Indizes sollten nach der initialen Datenbankeinrichtung 
-- einmalig ausgeführt werden.
--
-- Für bestehende Datenbanken mit vielen Daten kann REINDEX 
-- nach dem Erstellen der Indizes hilfreich sein:
-- REINDEX DATABASE <database_name>;  -- PostgreSQL
