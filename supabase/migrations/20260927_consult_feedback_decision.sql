-- Post-consult survey v2 (2026-09-27): where the client stands on their project, asked separately
-- from the 1-5 rating so an undecided-but-happy client doesn't drag the consultation score down.
--   ready      = "Ready to move forward"
--   need_info  = "Still undecided — I need more information"  (alerts the office to follow up)
--   not_now    = "Not moving forward right now"
alter table public.consult_feedback
  add column if not exists decision text
  check (decision is null or decision in ('ready', 'need_info', 'not_now'));

comment on column public.consult_feedback.decision is
  'Client''s project decision from the post-consult survey: ready | need_info | not_now (null = not answered).';
