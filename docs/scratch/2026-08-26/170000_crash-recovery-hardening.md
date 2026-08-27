# Crash-recovery hardening — APST fix, crash-gated GPU defer, auto-reboot

Follow-on to `165731_overnight-hard-crash-nvme2-bus-drop.md`. Goal: survive the
next hard crash without (a) another APST bus-drop, (b) an 8-hour dead-box wedge,
or (c) a reboot cycle if GPU load re-triggers the crash.

## 1. APST disable (grub) — APPLIED, effective next reboot

`/etc/default/grub` `GRUB_CMDLINE_LINUX` gained `nvme_core.default_ps_max_latency_us=0`
(backup: `/etc/default/grub.bak.2026-08-26`; `update-grub` run; 5 occurrences in
`/boot/grub/grub.cfg`). Forbids the drives entering the slow-wake ps4 deep state
that dropped nvme2. Owner chose NOT to also disable APST at runtime — it activates
on the next reboot. `pcie_aspm=off` was discussed but not applied (APST-only, per
owner's "most conservative" call).

## 2. Crash-gated GPU defer — INSTALLED + verified (except live engine skip)

**Policy: hold GPU workloads on every unclean reboot** (owner's choice), resume
manually. Loop-proof: crash → auto-reboot → GPU deferred → stable, waiting.

Boot→GPU-load map (from a read-only Explore pass): the only boot-time GPU load is
the **"thinking"** endpoint (Qwen3-27B, TP=4, GPUs 0-3), started via two paths —
preload (`server.py:292`, gated on `startup.clean_start`) and ambient re-ensure
(`server.py:1040`, gated on `startup.auto_start_ambient`). Evolution
(`server.py:308`, `auto_start_evolution`) is a background GPU consumer once idle.
Everything else (ColNomic, CLT, coding/fast) is lazy/on-demand.

Pieces:
- **Config bug fix** — `src/gaius/engine/config.py`: HOCON `${?ENV}` overrides
  substitute *strings*, and `"false"` is truthy, so `GAIUS_AUTO_START_AMBIENT` /
  `GAIUS_AUTO_EVOLUTION` (and the other startup booleans) were **silently ignored**.
  Added `_sb()` bool-coercion over all startup boolean flags. Verified: each env
  lever now flips a real `bool`. (Only `clean_start` worked before, via its
  explicit Python parse.)
- **`scripts/processes/gaius-engine.sh`** — before the final `exec`, if the marker
  `/var/lib/gaius/defer-gpu` exists, export `GAIUS_CLEAN_START=false`,
  `GAIUS_AUTO_START_AMBIENT=false`, `GAIUS_AUTO_EVOLUTION=false`. This is the
  direct exec parent of the engine, so env reaches it with no devenv-precedence
  issue. Chosen over an engine code-path change to keep blast radius minimal (no
  edit to `server.py` critical path) and testable without an engine restart.
- **`scripts/crash-guard.sh` + `scripts/systemd/crash-guard.service`** — oneshot,
  `RemainAfterExit=yes`, `Before=signals.target gaius.service aegir.service`.
  ExecStop (graceful shutdown) writes `/var/lib/gaius/clean-shutdown`; ExecStart
  (boot) → sentinel present = clean (consume + clear marker), absent = unclean
  (drop marker). State dir `/var/lib/gaius` is `root:rch 0775` (rch clears the
  marker), on the **root disk, not /raid** (RAID0 is the thing most likely wedged).
- **`scripts/gpu-resume.sh` + `just resume-gpu`** — `/gpu start thinking`, clears
  the marker **only on success** (failed resume re-defers next start, no loop).

Installed + bootstrapped in clean-armed state (pre-seeded sentinel consumed;
enabled; active). Verified on the live unit: graceful stop→ExecStop writes
sentinel; start→clean; crash path (no sentinel)→drops marker rch can read;
`gaius-engine.sh` would export the defer env. `bash -n` clean on all scripts.

**Not yet verified live:** the engine actually skipping GPU load on a deferred
boot — needs an engine restart, deferred to avoid disrupting the running
inference workload. Config flags + `server.py` gates are confirmed by code.

## 3. Auto-reboot (hung_task_panic) — STAGED, NOT armed

`scripts/systemd/60-crash-recovery.conf` (staged in repo, not copied to
`/etc/sysctl.d`). Sets `kernel.hung_task_panic=1`, `hung_task_timeout_secs=600`
(generous, avoids false triggers), `kernel.panic=10`, `panic_on_oops=1`. Current
effective: `hung_task_panic=0` — so last night's D-state I/O wedge would NOT
auto-reboot. **Deliberately not armed until the defer chain is validated live**
(auto-reboot without a working defer = the reboot loop we're preventing).

## Validation + arming plan (owner)

1. **Planned reboot** (`sudo systemctl reboot`) — applies APST; comes up clean →
   GPU loads normally. Check natural comeback: `systemctl --failed` +
   `systemctl status signals-refresh.service` (the `signals.target` verifier).
   This morning's crash-comeback failed on: signals.service (foundation),
   signals-polaris, aegir gateway, and `#EN.00000031.FDWINGEST` (warehouse ingest
   not fresh) — compare after this clean reboot.
2. **Controlled defer test** (at a convenient time — it restarts vLLM):
   `sudo touch /var/lib/gaius/defer-gpu && sudo systemctl restart gaius.service`,
   then `nvidia-smi` (GPUs 0-3 should stay idle — use nvidia-smi, `/gpu status`
   is currently unreliable), then `just resume-gpu` to bring it back.
3. **Arm auto-reboot** once satisfied:
   `sudo install -m0644 scripts/systemd/60-crash-recovery.conf /etc/sysctl.d/` &&
   `sudo sysctl --system`.

## Open / out-of-scope observations
- **`/gpu status` returns empty `data`** while vLLM is loaded (nvidia-smi shows
  GPUs 0-3 ~100%). Orchestrator endpoint registry looks un-adopted — likely a
  residue of the imperfect morning comeback. Worth a separate look.
- Backup / off-RAID0 for the data plane remains the top structural item
  (4-6 week lead time per owner).
