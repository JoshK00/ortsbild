-- Pseudonym table for the privacy layer (plain PostgreSQL).
-- Only a keyed hash (HMAC) of the user identifier is stored, never the identifier itself.
create table if not exists pseudonyms (
    identifier_hash text primary key,
    pseudonym text not null unique,
    created_at timestamptz not null default now()
);

-- TODO: Run the backend with its own database user that may only use these two tables
--       (today it uses the database owner).
