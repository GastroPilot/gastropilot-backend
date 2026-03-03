-- Guest Portal: Extend guest_profiles, add reviews table, add table_tokens
-- Migration: 001_guest_portal
-- Date: 2026-03-02

BEGIN;

-- ============================================================
-- 1. Extend guest_profiles with auth fields
-- ============================================================

ALTER TABLE guest_profiles
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

ALTER TABLE guest_profiles
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;

ALTER TABLE guest_profiles
    ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(255);

ALTER TABLE guest_profiles
    ADD COLUMN IF NOT EXISTS allergen_profile JSONB DEFAULT '[]';

-- ============================================================
-- 2. Reviews table
-- ============================================================

CREATE TABLE IF NOT EXISTS reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    guest_profile_id UUID NOT NULL REFERENCES guest_profiles(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    title VARCHAR(200),
    text TEXT,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviews_tenant_id ON reviews(tenant_id);
CREATE INDEX IF NOT EXISTS idx_reviews_guest_profile_id ON reviews(guest_profile_id);
CREATE INDEX IF NOT EXISTS idx_reviews_tenant_visible ON reviews(tenant_id) WHERE is_visible = TRUE;

-- ============================================================
-- 3. Table tokens for QR code ordering
-- ============================================================

ALTER TABLE tables
    ADD COLUMN IF NOT EXISTS table_token VARCHAR(64) UNIQUE;

ALTER TABLE tables
    ADD COLUMN IF NOT EXISTS token_created_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_tables_table_token ON tables(table_token) WHERE table_token IS NOT NULL;

-- ============================================================
-- 4. Order items: course field for multi-course kitchen
-- ============================================================

ALTER TABLE order_items
    ADD COLUMN IF NOT EXISTS course INTEGER DEFAULT 1;

-- ============================================================
-- 5. Waitlist: tracking token for public live updates
-- ============================================================

ALTER TABLE waitlist
    ADD COLUMN IF NOT EXISTS tracking_token VARCHAR(64) UNIQUE;

CREATE INDEX IF NOT EXISTS idx_waitlist_tracking_token
    ON waitlist(tracking_token) WHERE tracking_token IS NOT NULL;

-- ============================================================
-- 6. RLS policies for reviews
-- ============================================================

ALTER TABLE reviews ENABLE ROW LEVEL SECURITY;

-- Staff can see reviews for their restaurant
CREATE POLICY reviews_tenant_isolation ON reviews
    USING (tenant_id::text = current_setting('app.current_tenant_id', true));

-- Allow insert for any authenticated connection (guest auth bypasses RLS)
CREATE POLICY reviews_insert ON reviews
    FOR INSERT
    WITH CHECK (true);

-- ============================================================
-- 7. Updated_at trigger for reviews
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS reviews_updated_at ON reviews;
CREATE TRIGGER reviews_updated_at
    BEFORE UPDATE ON reviews
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMIT;
