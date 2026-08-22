# `systemctl restart gaius` is the remediations

A detached `python -m gaius.engine` answering Status made the oneshot
unit look `active (exited)` while the listener lived in `session-1.scope`.
That masked `#EN.00000016.NOTUNIT`. Membership is the **same**
process-compose graph `systemctl` and `devenv processes` see. A dedicated
`GAIUS_DEVENV_RUNTIME` splits those surfaces (Atelier already forbids it).
setsid is test-only while devenv is down.

Skip-up now requires `owned_by_unit_compose`. `/health fix engine` is
`sudo systemctl restart gaius.service` (full stop then start), not
`devenv up -d` beside a foreign engine.

The dispatcher bind (feed_check handlers) is a separate engine bug; it
loads on the unit recycle.
