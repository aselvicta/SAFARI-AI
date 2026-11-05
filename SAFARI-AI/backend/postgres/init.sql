CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS store_meta (
    key text PRIMARY KEY,
    value text NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id text PRIMARY KEY,
    name text NOT NULL,
    organization text,
    url text,
    phase integer NOT NULL DEFAULT 1,
    authority_score double precision NOT NULL DEFAULT 1.0,
    topics text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documents (
    document_id text PRIMARY KEY,
    title text NOT NULL,
    organization text,
    document_type text,
    body text NOT NULL DEFAULT '',
    language text NOT NULL DEFAULT 'en',
    authority text NOT NULL DEFAULT 'curated',
    authority_score double precision NOT NULL DEFAULT 0.85,
    status text NOT NULL DEFAULT 'current',
    version integer NOT NULL DEFAULT 1,
    published_date date,
    effective_from date,
    effective_until date,
    retrieved_at date,
    source_url text,
    park_slug text
);

CREATE TABLE IF NOT EXISTS document_versions (
    id bigserial PRIMARY KEY,
    document_id text NOT NULL,
    version integer NOT NULL,
    title text,
    status text,
    effective_from date,
    effective_until date,
    source_url text,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    position integer NOT NULL,
    body text NOT NULL,
    embedding vector(384),
    title text,
    organization text,
    document_type text,
    language text,
    authority text,
    authority_score double precision,
    status text,
    version integer,
    published_date date,
    effective_from date,
    effective_until date,
    retrieved_at date,
    source_url text,
    park_slug text
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_park_idx ON chunks (park_slug);

CREATE TABLE IF NOT EXISTS parks (
    slug text PRIMARY KEY,
    name text NOT NULL,
    area_km2 double precision,
    established_year integer,
    gazette text,
    circuit text,
    interests text[] NOT NULL DEFAULT '{}',
    beach boolean NOT NULL DEFAULT false,
    mountain_climb boolean NOT NULL DEFAULT false,
    aliases text[] NOT NULL DEFAULT '{}',
    strict_aliases text[] NOT NULL DEFAULT '{}',
    source_url text,
    source_title text
);

CREATE TABLE IF NOT EXISTS regions (
    region_id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS visitor_categories (
    category_id text PRIMARY KEY,
    label text NOT NULL,
    description text NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id text PRIMARY KEY,
    name text NOT NULL,
    park_slug text REFERENCES parks(slug),
    source_document_id text
);

CREATE TABLE IF NOT EXISTS fees (
    id bigserial PRIMARY KEY,
    document_id text NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    park_slug text,
    name text NOT NULL,
    visitor_category text NOT NULL,
    age_band text NOT NULL,
    amount numeric NOT NULL,
    currency text NOT NULL,
    unit text NOT NULL DEFAULT 'per_person_per_day'
);

CREATE TABLE IF NOT EXISTS accommodation (
    accommodation_id text PRIMARY KEY,
    name text NOT NULL,
    park_slug text REFERENCES parks(slug),
    source_document_id text
);

CREATE TABLE IF NOT EXISTS facilities (
    facility_id text PRIMARY KEY,
    name text NOT NULL,
    park_slug text REFERENCES parks(slug)
);

CREATE TABLE IF NOT EXISTS contacts (
    contact_id text PRIMARY KEY,
    organization text NOT NULL,
    postal text,
    phone text,
    email text,
    source_url text
);

INSERT INTO visitor_categories (category_id, label, description) VALUES
    ('citizen', 'Tanzanian citizen', 'Identity is not inferred. A current tariff must define the rate.'),
    ('eac_citizen', 'East African Community citizen', 'Identity is not inferred. A current tariff must define the rate.'),
    ('resident', 'Resident', 'Identity is not inferred. A current tariff must define the rate.'),
    ('non_resident', 'Non-resident', 'Identity is not inferred. A current tariff must define the rate.')
ON CONFLICT (category_id) DO NOTHING;

INSERT INTO contacts (contact_id, organization, postal, phone, email, source_url) VALUES
    (
        'tanapa',
        'Tanzania National Parks',
        'PO Box 3134, Arusha',
        '+255 (0) 272 970 404',
        'info@tanzaniaparks.go.tz',
        'https://www.tanzaniaparks.go.tz/nationalparks'
    )
ON CONFLICT (contact_id) DO NOTHING;

-- v2: structured rows from live sources (tariff items, park profiles, activities, contacts)
CREATE TABLE IF NOT EXISTS records (
    kind text NOT NULL,
    key text NOT NULL,
    payload jsonb NOT NULL,
    source_id text NOT NULL,
    source_url text,
    retrieved_at text,
    PRIMARY KEY (kind, key)
);

-- v2: per-source sync status shown on /v1/status
CREATE TABLE IF NOT EXISTS source_status (
    source_id text PRIMARY KEY,
    status jsonb NOT NULL
);
