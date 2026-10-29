-- Pseudonym table for the privacy layer. Run once in the Supabase SQL editor.
-- Only a keyed hash (HMAC) of the user identifier is stored, never the identifier itself.
create table if not exists public.pseudonyms (
    identifier_hash text primary key,
    pseudonym text not null unique,
    created_at timestamptz not null default now()
);

-- Row level security on and NO policy: the app and anonymous users cannot read or write.
-- Only the backend with the secret key (service role) can access the table.
alter table public.pseudonyms enable row level security;

-- The backend role needs explicit access (a table created here does not grant it).
-- The public roles get nothing, the app must never read or write this table directly.
grant select, insert, update, delete on public.pseudonyms to service_role;
revoke all on public.pseudonyms from anon, authenticated;
