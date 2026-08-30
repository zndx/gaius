-- migrate:up

-- Stagger article-curate-daily off the :00 boundary. clt-skos-admit runs */15 and
-- holds the single spare GPU token (extract+light share it while thinking pins
-- heavy's 4-GPU floor) for ~195s, so a 09:00 article-curate landed on the 09:00
-- clt-skos-admit hold every night and timed out (#YK.00000002.NOTADMITTED).
-- 09:07 UTC sits in the free window between holds (:03-:15).
SELECT cron.alter_job(
    (SELECT jobid FROM cron.job WHERE jobname = 'article-curate-daily'),
    schedule := '7 9 * * *'
);

-- migrate:down

SELECT cron.alter_job(
    (SELECT jobid FROM cron.job WHERE jobname = 'article-curate-daily'),
    schedule := '0 9 * * *'
);
