# SportsPlex — Sports Court Booking Platform

A production-quality, multi-facility sports court booking platform built with **Streamlit**, **Supabase**, and **Stripe**. Supports real-time availability, instant booking confirmation, membership discounts, admin dashboards, and revenue analytics.

---

## Features

**Player Experience**
- Browse real-time court availability by facility, sport, date, and duration
- Instant booking with Stripe Checkout — no card stored on our servers
- 10-minute booking hold prevents slot conflicts during payment
- Automatic refund on cancellation based on configurable cancellation policy
- Membership discounts (Basic 10% / Premium 20% / Corporate 25%)
- Waiver acceptance tracked per user

**Admin Dashboard**
- KPI overview: today's bookings, revenue, occupancy
- Full booking search with admin cancel + Stripe refund
- Facility configuration: operating hours, courts, booking rules, pricing rules, closures
- Revenue analytics: daily trend, sport breakdown, peak hours heatmap

**Technical**
- Role-based navigation: `player` / `facility_admin` / `super_admin`
- All timestamps stored as UTC (`TIMESTAMPTZ`); displayed in facility's local timezone
- Booking conflict prevention at two layers: application + DB `EXCLUDE USING GIST`
- Idempotency keys prevent double-holds and double-confirmations
- Server-side Stripe session verification — never trusts the return URL alone

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit ≥ 1.36 (multi-page, `st.navigation`) |
| Database & Auth | Supabase (Postgres + GoTrue) |
| Payments | Stripe Checkout (hosted) |
| ORM / Client | supabase-py |
| Charts | Plotly |
| Timezone | Python `zoneinfo` (stdlib, DST-aware) |
| Deployment | Streamlit Community Cloud |

---

## Project Structure

```
├── app.py                          # Entry point — page config, navigation, session init
├── requirements.txt
├── .env.example                    # Copy to .env and fill in secrets
├── styles/
│   └── custom.css                  # Global design system (sky-blue + violet palette)
├── pages/
│   ├── home.py                     # Public landing page
│   ├── login.py                    # Sign in / sign up / reset password
│   ├── profile.py                  # Profile, waiver, account security
│   ├── availability.py             # Browse & select court slots
│   ├── book.py                     # Booking review + Stripe checkout initiation
│   ├── payment_success.py          # Stripe return URL — server-side verification
│   ├── my_bookings.py              # View & cancel bookings
│   └── admin/
│       ├── dashboard.py            # KPI cards, today's schedule, recent activity
│       ├── bookings_mgmt.py        # Search all bookings, admin cancel + refund
│       ├── config.py               # Facility settings, hours, courts, pricing, closures
│       └── metrics.py              # Revenue charts, occupancy heatmap
├── services/
│   ├── auth_service.py             # Supabase Auth wrapper (sign in/up, session management)
│   ├── availability_service.py     # Pure-computation slot availability engine
│   ├── booking_service.py          # Hold lifecycle, booking confirmation, cancellation
│   ├── payment_service.py          # Stripe Checkout, verification, refunds
│   ├── pricing_service.py          # Rule-based pricing engine with membership discounts
│   └── admin_service.py            # Admin-only queries (uses service role client)
├── db/
│   ├── supabase_client.py          # Anon client (RLS enforced) + Admin client (bypasses RLS)
│   └── queries.py                  # Thin DB query wrappers
├── components/
│   ├── auth_guard.py               # require_auth(), require_admin(), sidebar user panel
│   ├── slot_selector.py            # Availability slot grid component
│   ├── booking_card.py             # Booking summary card
│   └── pricing_summary.py          # Price breakdown display
└── utils/
    ├── config.py                   # AppConfig from environment variables (fail-fast)
    ├── constants.py                # All magic strings: BookingStatus, SessionKey, etc.
    ├── time_utils.py               # DST-safe UTC ↔ local conversion, slot generation
    └── validators.py               # Email, password, phone, booking validation
```

---

## Setup Guide

### Prerequisites

- Python 3.11+
- A [Supabase](https://supabase.com) project (free tier works)
- A [Stripe](https://stripe.com) account (test mode for development)

---

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd online-reservation-application

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

```env
# Supabase
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=eyJ...          # Found in Supabase → Settings → API
SUPABASE_SERVICE_ROLE_KEY=eyJ...  # KEEP SECRET — bypasses all RLS

# Stripe
STRIPE_SECRET_KEY=sk_test_...     # Use sk_test_ for development
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...   # Not used in MVP — set to any string

# App
APP_NAME=SportsPlex
APP_ENV=development                # Set to "production" on deploy
APP_URL=http://localhost:8501      # Base URL for Stripe success_url redirect
DEFAULT_TIMEZONE=America/New_York
```

> **Security note:** Never commit `.env` to version control. The `.gitignore` should exclude it.

---

### 3. Supabase Database Setup

#### 3a. Enable Extensions

In Supabase SQL Editor, run:

```sql
-- Required for booking conflict prevention
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

#### 3b. Core Schema

Run the following SQL in your Supabase SQL Editor (Project → SQL Editor → New Query):

```sql
-- ── User Profiles ─────────────────────────────────────────────
CREATE TABLE user_profiles (
    id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name       TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    role            TEXT NOT NULL DEFAULT 'player'
                        CHECK (role IN ('player', 'facility_admin', 'super_admin')),
    membership_type TEXT NOT NULL DEFAULT 'none'
                        CHECK (membership_type IN ('none', 'basic', 'premium', 'corporate')),
    waiver_accepted     BOOLEAN NOT NULL DEFAULT FALSE,
    waiver_accepted_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Facilities ────────────────────────────────────────────────
CREATE TABLE facilities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE,
    address     TEXT,
    city        TEXT,
    state       TEXT,
    zip_code    TEXT,
    timezone    TEXT NOT NULL DEFAULT 'America/New_York',
    phone       TEXT,
    email       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Facility Settings ─────────────────────────────────────────
CREATE TABLE facility_settings (
    facility_id                     UUID PRIMARY KEY REFERENCES facilities(id) ON DELETE CASCADE,
    min_booking_minutes             INT  NOT NULL DEFAULT 60,
    booking_increment_minutes       INT  NOT NULL DEFAULT 30,
    max_booking_hours               INT  NOT NULL DEFAULT 4,
    buffer_minutes_between_bookings INT  NOT NULL DEFAULT 0,
    booking_window_days             INT  NOT NULL DEFAULT 30,
    hold_expiry_minutes             INT  NOT NULL DEFAULT 10,
    cancellation_window_hours       INT  NOT NULL DEFAULT 24,
    partial_refund_window_hours     INT  NOT NULL DEFAULT 12,
    allow_auto_assign_court         BOOLEAN NOT NULL DEFAULT TRUE,
    allow_waitlist                  BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Facility Operating Hours ──────────────────────────────────
CREATE TABLE facility_operating_hours (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id  UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    day_of_week  TEXT NOT NULL
                     CHECK (day_of_week IN ('monday','tuesday','wednesday','thursday',
                                            'friday','saturday','sunday')),
    is_open      BOOLEAN NOT NULL DEFAULT TRUE,
    open_time    TIME NOT NULL DEFAULT '08:00:00',
    close_time   TIME NOT NULL DEFAULT '22:00:00',
    UNIQUE (facility_id, day_of_week)
);

-- ── Facility Closures ─────────────────────────────────────────
CREATE TABLE facility_closures (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id  UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    closure_date DATE NOT NULL,
    reason       TEXT,
    closure_type TEXT NOT NULL DEFAULT 'one_time'
                     CHECK (closure_type IN ('one_time', 'recurring')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Courts ────────────────────────────────────────────────────
CREATE TABLE courts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id   UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    description   TEXT,
    sport_type    TEXT NOT NULL
                      CHECK (sport_type IN ('pickleball','badminton','tennis',
                                            'karate','multi-sport')),
    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','inactive','maintenance')),
    indoor        BOOLEAN NOT NULL DEFAULT TRUE,
    capacity      INT,
    display_order INT NOT NULL DEFAULT 0,
    hourly_rate   NUMERIC(10,2) NOT NULL DEFAULT 25.00,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Pricing Rules ─────────────────────────────────────────────
CREATE TABLE pricing_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id     UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    rule_type       TEXT NOT NULL
                        CHECK (rule_type IN ('base','peak','off_peak','weekend','event','membership')),
    price_per_hour  NUMERIC(10,2) NOT NULL,
    applies_to_days TEXT[],                -- NULL = all days
    peak_start_time TIME,
    peak_end_time   TIME,
    sport_type      TEXT,                  -- NULL = all sports
    court_id        UUID REFERENCES courts(id),  -- NULL = all courts
    priority        INT NOT NULL DEFAULT 10,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Blackout Periods ──────────────────────────────────────────
CREATE TABLE blackout_periods (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id     UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    name            TEXT,
    start_time_utc  TIMESTAMPTZ NOT NULL,
    end_time_utc    TIMESTAMPTZ NOT NULL,
    court_id        UUID REFERENCES courts(id),  -- NULL = all courts
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Booking Holds ─────────────────────────────────────────────
CREATE TABLE booking_holds (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id      UUID NOT NULL REFERENCES facilities(id),
    court_id         UUID NOT NULL REFERENCES courts(id),
    user_id          UUID NOT NULL REFERENCES auth.users(id),
    booking_date     DATE NOT NULL,
    start_time_utc   TIMESTAMPTZ NOT NULL,
    end_time_utc     TIMESTAMPTZ NOT NULL,
    duration_minutes INT NOT NULL,
    estimated_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
    idempotency_key  UUID NOT NULL UNIQUE,
    expires_at       TIMESTAMPTZ NOT NULL,
    is_converted     BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_session_id TEXT,
    promo_code_id    UUID,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Bookings ──────────────────────────────────────────────────
CREATE TABLE bookings (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id                 UUID NOT NULL REFERENCES facilities(id),
    court_id                    UUID NOT NULL REFERENCES courts(id),
    user_id                     UUID NOT NULL REFERENCES auth.users(id),
    hold_id                     UUID REFERENCES booking_holds(id),
    booking_date                DATE NOT NULL,
    start_time_utc              TIMESTAMPTZ NOT NULL,
    end_time_utc                TIMESTAMPTZ NOT NULL,
    duration_minutes            INT NOT NULL,
    booking_type                TEXT NOT NULL DEFAULT 'standard'
                                    CHECK (booking_type IN ('standard','full_day','event','blocked')),
    status                      TEXT NOT NULL DEFAULT 'pending_payment'
                                    CHECK (status IN ('hold','pending_payment','confirmed',
                                                      'cancelled','refunded','blocked',
                                                      'expired','no_show')),
    base_amount                 NUMERIC(10,2) NOT NULL DEFAULT 0,
    discount_amount             NUMERIC(10,2) NOT NULL DEFAULT 0,
    tax_amount                  NUMERIC(10,2) NOT NULL DEFAULT 0,
    fee_amount                  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total_amount                NUMERIC(10,2) NOT NULL DEFAULT 0,
    currency                    TEXT NOT NULL DEFAULT 'usd',
    stripe_checkout_session_id  TEXT UNIQUE,
    stripe_payment_intent_id    TEXT,
    promo_code_id               UUID,
    notes                       TEXT,
    admin_notes                 TEXT,
    waiver_accepted             BOOLEAN NOT NULL DEFAULT FALSE,
    waiver_accepted_at          TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Prevents overlapping confirmed bookings for the same court at the DB level
    EXCLUDE USING GIST (
        court_id WITH =,
        tstzrange(start_time_utc, end_time_utc, '[)') WITH &&
    ) WHERE (status IN ('confirmed', 'pending_payment'))
);

-- ── Payments ──────────────────────────────────────────────────
CREATE TABLE payments (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_id                  UUID NOT NULL REFERENCES bookings(id),
    facility_id                 UUID NOT NULL REFERENCES facilities(id),
    user_id                     UUID NOT NULL REFERENCES auth.users(id),
    stripe_checkout_session_id  TEXT,
    stripe_payment_intent_id    TEXT,
    amount                      NUMERIC(10,2) NOT NULL,
    currency                    TEXT NOT NULL DEFAULT 'usd',
    payment_status              TEXT NOT NULL DEFAULT 'pending'
                                    CHECK (payment_status IN ('pending','completed','failed',
                                                              'refunded','partial_refund')),
    refund_status               TEXT NOT NULL DEFAULT 'none'
                                    CHECK (refund_status IN ('none','partial','full')),
    refunded_amount             NUMERIC(10,2) NOT NULL DEFAULT 0,
    idempotency_key             TEXT UNIQUE,
    paid_at                     TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Facility Admins (join table) ──────────────────────────────
CREATE TABLE facility_admins (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_id UUID NOT NULL REFERENCES facilities(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (facility_id, user_id)
);

-- ── Promo Codes ───────────────────────────────────────────────
CREATE TABLE promo_codes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT NOT NULL UNIQUE,
    discount_type   TEXT NOT NULL CHECK (discount_type IN ('percent', 'fixed')),
    discount_value  NUMERIC(10,2) NOT NULL,
    max_uses        INT,
    used_count      INT NOT NULL DEFAULT 0,
    valid_from      TIMESTAMPTZ,
    valid_until     TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### 3c. Row Level Security (RLS)

```sql
-- Enable RLS on all tables
ALTER TABLE user_profiles     ENABLE ROW LEVEL SECURITY;
ALTER TABLE facilities        ENABLE ROW LEVEL SECURITY;
ALTER TABLE facility_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE facility_operating_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE facility_closures ENABLE ROW LEVEL SECURITY;
ALTER TABLE courts            ENABLE ROW LEVEL SECURITY;
ALTER TABLE pricing_rules     ENABLE ROW LEVEL SECURITY;
ALTER TABLE blackout_periods  ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking_holds     ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings          ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments          ENABLE ROW LEVEL SECURITY;
ALTER TABLE facility_admins   ENABLE ROW LEVEL SECURITY;
ALTER TABLE promo_codes       ENABLE ROW LEVEL SECURITY;

-- Helper functions
CREATE OR REPLACE FUNCTION is_super_admin()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT EXISTS (
        SELECT 1 FROM user_profiles
        WHERE id = auth.uid() AND role = 'super_admin'
    );
$$;

CREATE OR REPLACE FUNCTION is_facility_admin(fac_id UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER AS $$
    SELECT EXISTS (
        SELECT 1 FROM facility_admins
        WHERE user_id = auth.uid()
          AND facility_id = fac_id
          AND is_active = TRUE
    ) OR is_super_admin();
$$;

-- User profiles: own row only (service role handles cross-user reads)
CREATE POLICY "Users can view their own profile"
    ON user_profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update their own profile"
    ON user_profiles FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "Service role can insert profiles"
    ON user_profiles FOR INSERT WITH CHECK (TRUE);

-- Facilities: public read, admin write
CREATE POLICY "Facilities are publicly readable"
    ON facilities FOR SELECT USING (TRUE);
CREATE POLICY "Admins can update facilities"
    ON facilities FOR UPDATE USING (is_facility_admin(id));

-- Facility settings, hours, closures: public read
CREATE POLICY "Settings are publicly readable"
    ON facility_settings FOR SELECT USING (TRUE);
CREATE POLICY "Hours are publicly readable"
    ON facility_operating_hours FOR SELECT USING (TRUE);
CREATE POLICY "Closures are publicly readable"
    ON facility_closures FOR SELECT USING (TRUE);

-- Courts: public read
CREATE POLICY "Courts are publicly readable"
    ON courts FOR SELECT USING (TRUE);

-- Pricing rules: public read
CREATE POLICY "Pricing rules are publicly readable"
    ON pricing_rules FOR SELECT USING (TRUE);

-- Blackout periods: public read
CREATE POLICY "Blackout periods are publicly readable"
    ON blackout_periods FOR SELECT USING (TRUE);

-- Booking holds: own holds only
CREATE POLICY "Users can view their own holds"
    ON booking_holds FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Authenticated users can create holds"
    ON booking_holds FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can update their own holds"
    ON booking_holds FOR UPDATE USING (auth.uid() = user_id);

-- Bookings: own bookings only
CREATE POLICY "Users can view their own bookings"
    ON bookings FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Authenticated users can create bookings"
    ON bookings FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can update their own bookings"
    ON bookings FOR UPDATE USING (auth.uid() = user_id);

-- Payments: own payments only
CREATE POLICY "Users can view their own payments"
    ON payments FOR SELECT USING (auth.uid() = user_id);

-- Promo codes: authenticated read
CREATE POLICY "Authenticated users can read promo codes"
    ON promo_codes FOR SELECT USING (auth.role() = 'authenticated');
```

#### 3d. Triggers (optional but recommended)

```sql
-- Auto-update updated_at timestamps
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_facilities_updated_at
    BEFORE UPDATE ON facilities
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER trg_bookings_updated_at
    BEFORE UPDATE ON bookings
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Auto-create user profile on sign-up
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    INSERT INTO user_profiles (id, full_name, email)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', 'User'),
        NEW.email
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();
```

#### 3e. Seed Data

```sql
-- Insert a sample facility
INSERT INTO facilities (name, slug, address, city, state, zip_code, timezone, phone, email)
VALUES (
    'SportsPlex Downtown',
    'sportsplex-downtown',
    '123 Court Street',
    'New York', 'NY', '10001',
    'America/New_York',
    '(212) 555-0100',
    'info@sportsplex.com'
);

-- Get the facility ID for subsequent inserts
DO $$
DECLARE
    fac_id UUID;
BEGIN
    SELECT id INTO fac_id FROM facilities WHERE slug = 'sportsplex-downtown';

    -- Settings
    INSERT INTO facility_settings (facility_id) VALUES (fac_id);

    -- Operating hours (Mon–Fri 6am–10pm, Sat–Sun 7am–9pm)
    INSERT INTO facility_operating_hours (facility_id, day_of_week, open_time, close_time)
    VALUES
        (fac_id, 'monday',    '06:00', '22:00'),
        (fac_id, 'tuesday',   '06:00', '22:00'),
        (fac_id, 'wednesday', '06:00', '22:00'),
        (fac_id, 'thursday',  '06:00', '22:00'),
        (fac_id, 'friday',    '06:00', '22:00'),
        (fac_id, 'saturday',  '07:00', '21:00'),
        (fac_id, 'sunday',    '07:00', '21:00');

    -- Courts
    INSERT INTO courts (facility_id, name, sport_type, indoor, hourly_rate, display_order)
    VALUES
        (fac_id, 'Pickleball Court 1', 'pickleball', true,  25.00, 1),
        (fac_id, 'Pickleball Court 2', 'pickleball', true,  25.00, 2),
        (fac_id, 'Badminton Court 1',  'badminton',  true,  20.00, 3),
        (fac_id, 'Tennis Court 1',     'tennis',     false, 35.00, 4),
        (fac_id, 'Karate Studio',      'karate',     true,  30.00, 5);

    -- Pricing rules
    INSERT INTO pricing_rules (facility_id, name, rule_type, price_per_hour, priority)
    VALUES (fac_id, 'Standard Rate', 'base', 25.00, 0);

    INSERT INTO pricing_rules
        (facility_id, name, rule_type, price_per_hour, applies_to_days,
         peak_start_time, peak_end_time, priority)
    VALUES
        (fac_id, 'Peak Evening', 'peak', 35.00,
         ARRAY['monday','tuesday','wednesday','thursday','friday'],
         '17:00', '22:00', 20),
        (fac_id, 'Weekend Rate', 'weekend', 40.00,
         ARRAY['saturday','sunday'],
         NULL, NULL, 15),
        (fac_id, 'Off-Peak Morning', 'off_peak', 20.00,
         ARRAY['monday','tuesday','wednesday','thursday','friday'],
         '06:00', '12:00', 10);
END $$;
```

---

### 4. Stripe Setup

1. Create a [Stripe account](https://stripe.com) and get your API keys from the dashboard
2. Use **test mode** keys (`pk_test_...` / `sk_test_...`) during development
3. No webhook configuration required for the MVP — the app verifies payments via the return URL

For **production**, set `APP_URL` to your Streamlit Community Cloud URL so Stripe redirects correctly:
```
success_url = {APP_URL}/payment-success?session_id={CHECKOUT_SESSION_ID}
```

---

### 5. Local Development

```bash
# Activate venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux

# Run the app
streamlit run app.py
```

The app opens at `http://localhost:8501`.

**First-time setup checklist:**
- [ ] Supabase project created and SQL schema applied
- [ ] RLS policies enabled
- [ ] Seed data inserted (at least one facility, courts, pricing rules)
- [ ] `.env` file populated with all required keys
- [ ] Stripe test keys configured

---

## Deployment — Streamlit Community Cloud

1. Push your repository to GitHub (ensure `.env` is in `.gitignore`)

2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**

3. Select your repository, branch, and set `app.py` as the main file

4. Under **Advanced settings → Secrets**, add all environment variables from `.env.example` in TOML format:

```toml
SUPABASE_URL = "https://your-project-id.supabase.co"
SUPABASE_ANON_KEY = "eyJ..."
SUPABASE_SERVICE_ROLE_KEY = "eyJ..."
STRIPE_SECRET_KEY = "sk_live_..."
STRIPE_PUBLISHABLE_KEY = "pk_live_..."
STRIPE_WEBHOOK_SECRET = "whsec_..."
APP_NAME = "SportsPlex"
APP_ENV = "production"
APP_URL = "https://your-app-name.streamlit.app"
DEFAULT_TIMEZONE = "America/New_York"
```

5. Set `APP_URL` to your Streamlit app URL (e.g., `https://sportsplex.streamlit.app`) so Stripe's success redirect works

6. In Supabase → Auth → URL Configuration, add your Streamlit URL to **Redirect URLs** to allow password reset emails

---

## Architecture Notes

### Booking Hold Mechanism

```
User selects slot → create_hold() (10 min expiry)
                 → Stripe Checkout → user pays
                 → payment_success.py loads
                 → verify_payment_session() (server-side Stripe API call)
                 → confirm_booking_from_hold() → booking.status = confirmed
```

Holds expire automatically. If a user closes the browser after paying but before the success page loads, the slot is released — this is the only known data loss scenario in the MVP (see Known Limitations).

### Conflict Prevention (Belt-and-Suspenders)

**Layer 1 — Application:** `_check_slot_conflicts()` in `booking_service.py` checks existing bookings and active holds before inserting a new hold.

**Layer 2 — Database:** `EXCLUDE USING GIST` on the bookings table prevents overlapping `confirmed` or `pending_payment` bookings at the Postgres level. If two concurrent requests slip through Layer 1, exactly one DB insert will succeed.

### Two Supabase Clients

| Client | Key | RLS | Used for |
|---|---|---|---|
| `get_client()` | Anon key | Enforced | All user-facing operations |
| `get_admin_client()` | Service role key | Bypassed | Payment confirmation, admin ops |

The service role key **must never be exposed to the browser**. It is only used server-side in Streamlit Python code.

### Pricing Engine

Rules are matched by priority (highest wins). Priority levels:

| Type | Priority | Typical Use |
|---|---|---|
| `base` | 0 | Default catch-all rate |
| `off_peak` | 10 | Morning / weekday discount |
| `weekend` | 15 | Saturday / Sunday rate |
| `peak` | 20 | Evening weekday premium |
| `event` | 25 | Special event override |

Membership discounts are applied after rule matching: Basic 10%, Premium 20%, Corporate 25%.

---

## Known Limitations (MVP)

| Limitation | Impact | Post-MVP Fix |
|---|---|---|
| No Stripe webhooks | If user pays but closes browser before success page loads, booking is not confirmed. Payment is captured; requires admin refund. | Deploy a FastAPI webhook handler on Railway/Render |
| No email notifications | Users don't receive booking confirmation emails | Supabase Edge Functions + Resend/SendGrid |
| No calendar sync | No iCal / Google Calendar export | Add `.ics` download on booking confirmation page |
| Single currency (USD) | No multi-currency support | Stripe multi-currency is straightforward to add |
| No waitlist | When courts are full, users see no availability | `allow_waitlist` setting is prepared in DB schema |

---

## Phases Delivered

| Phase | Description | Status |
|---|---|---|
| 1 | SQL schema, RLS policies, DB design | ✅ |
| 2 | Auth, session management, profile | ✅ |
| 3 | Availability engine, booking flow | ✅ |
| 4 | Stripe Checkout integration | ✅ |
| 5 | My Bookings, cancellation & refunds | ✅ |
| 6 | Admin dashboard, config, metrics | ✅ |
| 7 | UI polish — sky-blue/violet design system | ✅ |
| 8 | This README + deployment guide | ✅ |

---

## License

MIT — see `LICENSE` for details.
