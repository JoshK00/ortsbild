-- The draft of a report: the message that the user approves.
-- Safe to run more than once. Run it after 001 to 006.
alter table reports add column if not exists draft jsonb;

alter table reports drop constraint if exists reports_status_check;
alter table reports add constraint reports_status_check
    check (status in ('processing', 'sanitized', 'classified', 'researched', 'drafted', 'blocked_privacy', 'rejected'));
