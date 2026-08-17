# Agenda pins today; future/past lazy-load

Schedule still runs future → today → past. First paint puts
`#agenda-today` at the top of `.agenda-main`. Scroll up for later
sessions, down for history.

Render budget is ~3× the viewport row count. “Earlier future” /
“Older” cues at the ends of the schedule widen the slice, then
`window_days` (+30) so Nov 14 is not in the first 14-day fetch.
`list_items` now windows on calendar day (`starts` or created).
Those cues are not federation Sentinels (MiNiFi).
Asset `0.2.14-agenda-fold`.
