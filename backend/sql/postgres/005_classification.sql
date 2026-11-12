-- Classification of a report: the result and the status "classified".
-- Safe to run more than once. Run it after 001 to 004.
alter table reports add column if not exists classification jsonb;

alter table reports drop constraint if exists reports_status_check;
alter table reports add constraint reports_status_check
    check (status in ('processing', 'sanitized', 'classified', 'blocked_privacy', 'rejected'));
