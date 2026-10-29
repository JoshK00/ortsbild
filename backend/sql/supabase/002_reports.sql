-- Status table for the privacy layer. Run once in the Supabase SQL editor.
-- One row per report: where it is, and why it was blocked. No personal data in it.
create table if not exists public.reports (
    id text primary key,
    status text not null check (status in ('processing', 'sanitized', 'blocked_privacy', 'rejected')),
    block_reason text,  -- step and error type only, never an error message
    source_type text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists reports_status_idx on public.reports (status);

-- Row level security on and NO policy: only the backend with the secret key can access it.
alter table public.reports enable row level security;

-- The backend role needs explicit access (a table created here does not grant it).
-- The public roles get nothing, the app must never read or write this table directly.
grant select, insert, update, delete on public.reports to service_role;
revoke all on public.reports from anon, authenticated;
