# Discover salience clock

Default window is the last hour of **production** (`feature_tape.created_at`),
not wall-clock. After 09:50 the hist is 08:50–09:50 by minute (tail to
zero inside the episode), not 11 empty hours since.

Countdown: soonest cron that can still write salience (skip empty
feature_probe). Next real episode is `check-due-fetches` 17 */4.

Trendlines: 5-minute SMA of salience, watts, util. Watts/util from
`meta.gpu_minute_stats` when present (repo GPUMinuteStats formula).
