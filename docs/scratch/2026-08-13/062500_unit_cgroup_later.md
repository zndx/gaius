# gaius.service vs session-1.scope

**Date:** 2026-08-13

Live `:50051` pid 995466 is `user.slice/user-1001.slice/session-1.scope`
(devenv under the login/tmux session). `gaius.service` is oneshot
`active (exited)` with `CGroup: /system.slice/gaius.service` and **0 tasks**.

Fine for lattice-ci. Later: `systemctl restart gaius` → one listener;
`stop` drops it. Ownership = unit ExecStart/Stop control, not cgroup.
