# Impala ticket refresh is an Airflow workload

`gaius_impala_krb_renew` (`20 */8 * * *`, task type `impala_krb_renew`) is the
clock. The handler runs `signals_impala_kinit` once against `SIGNALS_ROOT`.
There is no pg_cron job. A miss is 18 hours without a success, inside the
24 hour ticket lifetime and after one skipped 8 hour slot.

The resident loop and the devenv process are not the supervisor.
