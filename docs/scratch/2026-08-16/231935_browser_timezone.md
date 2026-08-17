# Browser timezone, not a setting

Ask Clock uses `Intl` IANA zone + local 09:00 resolved to UTC ISO.
Agenda paints and groups by local wall time. Writes resolve
`tomorrow_morning` tokens and remap invented `09:00Z` when the
browser is not UTC (MDT 09:00 = 15:00Z).

No timezone setting. Server stays UTC. Asset `0.2.17-tz-clock`.
Review Prospects moved to 15:00Z so it reads 09:00 from MDT.
