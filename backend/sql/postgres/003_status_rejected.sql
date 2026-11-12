-- For a database that was created before the status "rejected" existed: allow it.
-- Safe to run more than once. (A fresh database gets it from 002_reports.sql.)
alter table reports drop constraint if exists reports_status_check;
alter table reports add constraint reports_status_check
    check (status in ('processing', 'sanitized', 'blocked_privacy', 'rejected'));
