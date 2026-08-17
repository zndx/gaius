# Agenda view + calendar details without the CTA

Google Calendar `details` now uses `strip_calendar_markup` so
`[Add to Google Calendar](…)` is never copied into the event.
Session bodies no longer store that markdown; the UI button builds
the TEMPLATE URL.

Opening a card is a rendered Kumo view (markdown, wiki hops, tables,
`:::gaius-artifact` / ohlc JSON). Pencil edits, check saves, ×
closes. Asset `0.2.13-agenda-view`.
