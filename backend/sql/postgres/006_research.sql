-- Research of the responsible authority: the result of a report and the memory of confirmed and found answers.
-- Safe to run more than once. Run it after 001 to 005.
alter table reports add column if not exists research jsonb;

alter table reports drop constraint if exists reports_status_check;
alter table reports add constraint reports_status_check
    check (status in ('processing', 'sanitized', 'classified', 'researched', 'blocked_privacy', 'rejected'));

-- The memory of the research. The key is the place (normalized) and the category.
-- No report, no user and no personal data in it: only a place, a category and a public authority.
create table if not exists authority_registry (
    country_code text not null,
    municipality text not null,
    category text not null,
    result jsonb not null,
    confirmations integer not null default 0,  -- how many users confirmed the answer
    team_verified boolean not null default false,  -- a person of the team checked it
    updated_at timestamptz not null default now(),
    primary key (country_code, municipality, category)
);
