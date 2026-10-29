-- Status table for the privacy layer (plain PostgreSQL).
-- One row per report: where it is, and why it was blocked. No personal data in it.
create table if not exists reports (
    id text primary key,
    status text not null check (status in ('processing', 'sanitized', 'blocked_privacy')),
    block_reason text,  -- step and error type only, never an error message
    source_type text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists reports_status_idx on reports (status);
