-- Sign in with Apple: refresh tokens, and the owner of a report.
-- Safe to run more than once. Run it after 001 to 003.

-- One row per refresh token. Only the hash of the token is stored, never the token.
create table if not exists refresh_tokens (
    id text primary key,
    session_id text not null,
    user_key text not null,  -- keyed hash of the Apple id, never the Apple id itself
    token_hash text not null unique,
    expires_at timestamptz not null,
    used_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists refresh_tokens_session_idx on refresh_tokens (session_id);
create index if not exists refresh_tokens_user_idx on refresh_tokens (user_key);

-- Owner of a report, the id the app made up (so a retry does not create a second report),
-- the municipality (tenant) and the sanitized result. No raw data and no Apple id in them.
alter table reports add column if not exists user_key text;
alter table reports add column if not exists client_report_id text;
alter table reports add column if not exists tenant text;
alter table reports add column if not exists sanitized_report jsonb;

create unique index if not exists reports_user_client_idx on reports (user_key, client_report_id)
    where user_key is not null and client_report_id is not null;
create index if not exists reports_user_created_idx on reports (user_key, created_at);
