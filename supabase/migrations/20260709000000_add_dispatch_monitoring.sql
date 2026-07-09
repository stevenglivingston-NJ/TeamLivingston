-- Monitoring for dispatch-notify edge function
-- Creates a function to check if notifications are being processed on schedule

-- Function to check dispatch health (called by monitoring/alerting)
create or replace function dispatch_notify_health_check()
returns table (
  healthy boolean,
  last_processed_at timestamptz,
  pending_count bigint,
  minutes_since_last_process int
) as $$
declare
  v_last_processed timestamptz;
  v_pending_count bigint;
  v_minutes_since int;
begin
  -- Get last successful dispatch time
  select sent_at into v_last_processed
  from notify_queue
  where status = 'sent'
  order by sent_at desc
  limit 1;

  -- Count pending notifications (should be low if dispatcher is healthy)
  select count(*) into v_pending_count
  from notify_queue
  where status = 'pending';

  -- Calculate minutes since last dispatch
  v_minutes_since := extract(epoch from (now() - coalesce(v_last_processed, now()))) / 60;

  -- Healthy if: last dispatch within 5 minutes OR no pending notifications
  return query select
    (v_minutes_since <= 5 or v_pending_count = 0),
    v_last_processed,
    v_pending_count,
    v_minutes_since;
end;
$$ language plpgsql security definer;

-- Grant execute to authenticated users for monitoring dashboards
grant execute on function dispatch_notify_health_check to authenticated;
grant execute on function dispatch_notify_health_check to service_role;

comment on function dispatch_notify_health_check is 'Monitor dispatch-notify edge function health. Healthy = processed within 5min OR no pending. Call this every 10 minutes to alert on failures.';
