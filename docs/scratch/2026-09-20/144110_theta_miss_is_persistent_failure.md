# Theta miss / not-caught-up is a persistent failure (2026-09-20)

A missed Monday Theta cycle, or a previous ISO week that is not caught up,
is a **failure**. It is not `CHANNEL_BRIEFING`, not “Airflow is up so the hub
is fine,” and not a footnote on a `fresh` AgentRTC pack. Do not catch up as
a job.

## Nautilus (Gaius spec)

- `task.theta_cycle` and `flow.ThetaCycleFlow`: `CHANNEL_AGENDA_EVENT` at
  horizon slot 3 (was `CHANNEL_BRIEFING` at slot 7, “briefing by the next
  day, not a 2 h alarm”).
- New `objective.theta_cycle`: FAIL until `theta_consolidation_runs` has a
  completed, error-empty row for the previous ISO week. Skip ≠ success.
- `spec_version` 2026-09-20.1.

Nautilus stays observe-only. The 34 h in-memory window still drops old
ladders; the 6 h objective FAIL re-opens “not caught up” until a successful
`source=airflow` tick.

## Coordination (Gaius engine)

- Weekly cadence window for `theta_cycle` is 8 days (not horizon×3 = 15 h,
  which re-fired MISSTICK the evening after a good Monday run).
- Previous-week slice with no completed row is `theta_not_caught_up` after
  Monday 06:00 UTC + 5 h net. A recent tick for the wrong slice does not
  clear it.
- `status().persistent_failures` includes `theta_cycle`.
- Engine/Status advertises `capability=coordination` with guru / miss /
  fail in `Endpoint.detail`. `Surface.url` stays the Watch target.

## Federated workspace (Hermes AgentRTC)

- Sitrep reads that coordination endpoint (legacy `#CO.…` URLs still parse).
- `persistent_failures: ["theta_cycle not caught up"]` on the snapshot.
- Conversational pack is `workspace=failed` when Theta is not caught up,
  even if thoughts/agenda briefs are fresh. Pipeline block leads with
  PERSISTENT FAILURES. Do not catch up Theta.
