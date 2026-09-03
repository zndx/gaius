-- migrate:up
-- objective_verify joins the long-net class. Since 2026-09-02 the
-- prospects_intelligence rubric gate hands its FINAL CALL to the Overwatch
-- judge (ACP+Grok), a ~30 min consultation; verify_all runs objectives
-- serially inside one task, so a verification legitimately runs past the
-- 45 min default net. 2026-09-03 13:38: the watchdog would have reset a
-- live, progressing verification mid-judge at the 14:25 tick — a false
-- positive of exactly the class the ledger scores (D4). Progress over
-- timeouts: the net is a net, not a deadline.
SELECT cron.alter_job(
  (SELECT jobid FROM cron.job WHERE jobname = 'task-watchdog'),
  command := (
    SELECT replace(command,
                   '''publish_cards'')',
                   '''publish_cards'', ''objective_verify'')')
    FROM cron.job WHERE jobname = 'task-watchdog'
  )
);

-- migrate:down
SELECT cron.alter_job(
  (SELECT jobid FROM cron.job WHERE jobname = 'task-watchdog'),
  command := (
    SELECT replace(command,
                   '''publish_cards'', ''objective_verify'')',
                   '''publish_cards'')')
    FROM cron.job WHERE jobname = 'task-watchdog'
  )
);
