-- A report waits for the answer of the user when the picture is not clear.
-- Safe to run more than once. Run it after 001 to 007.
alter table reports drop constraint if exists reports_status_check;
alter table reports add constraint reports_status_check
    check (status in ('processing', 'sanitized', 'classified', 'needs_input', 'researched', 'drafted', 'blocked_privacy', 'rejected'));
