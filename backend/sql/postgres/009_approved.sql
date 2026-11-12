-- The user releases a report: from then on it is visible in the dashboard and counts as a vote.
-- It is a time, not a status, because the release is independent of how far the chain got (classified, researched, drafted).
-- Safe to run more than once. Run it after 001 to 008.
alter table reports add column if not exists approved_at timestamptz;
create index if not exists reports_approved_idx on reports (approved_at) where approved_at is not null;
