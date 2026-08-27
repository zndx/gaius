# Overnight hard crash — nvme2 fell off the PCIe bus (RAID0 → hard hang)

**Date of crash:** 2026-08-26 **07:45:58 UTC**
**Discovered / recovered:** 2026-08-26 15:53 (manual power-cycle)
**Downtime:** ~8h 8m (hung, not powered off — sat dead until morning)
**Data loss:** none (ext4 journal replay recovered `/raid`; workload was GPU-bound)
**Inference workload:** vLLM 4-way TP on GPUs 0–3 — **victim, not cause**

## Root cause (high confidence on mechanism)

NVMe drive **`nvme2n1`** (WD_BLACK SN850X 1000GB, serial **235146805255**,
PCI **0000:04:00.0**) **dropped off the PCIe bus** at 07:45:58. The kernel saw
all-ones reads on both the controller status and PCI status registers — the
hallmark of a device that has stopped responding entirely:

```
07:45:58 kernel: nvme nvme2: controller is down; will reset: CSTS=0xffffffff, PCI_STATUS=0xffff
07:45:58 kernel: nvme nvme2: Does your device have a faulty power saving mode enabled?
07:45:58 kernel: nvme nvme2: Try "nvme_core.default_ps_max_latency_us=0 pcie_aspm=off pcie_port_pm=off" and report a bug
07:45:59 kernel: workqueue: sync_rcu_exp_select_node_cpus hogged CPU for >10000us 4 times ...
07:45:59 warp-svc: DNS proxy health status: Healthy
<NUL><NUL>...   ← rsyslog's last disk block, zero-filled (unclean stop)
```

### Why one drive took down the whole box

The four SN850X NVMes are in **`md0` = RAID0** (striped, 3.6 TB, ext4, mounted
`/raid`, `stripe=512`, 85% full). **RAID0 has no redundancy** — losing any one
member faults the entire array's in-flight I/O. `/raid` holds the signals
warehouse / KB (`/raid/signals/var/kb/...`), so the engine + Kudu ingest were
actively touching it. When nvme2 vanished:

1. All `/raid` I/O faulted; processes touching it blocked in uninterruptible D-state.
2. The kernel's controller-reset path stalled RCU / hogged CPUs (the workqueue msg).
3. The box **livelocked within ~1 second** — no further log output.

`kernel.panic=2` is set, but the machine did **not** auto-reboot, which confirms
this was a **hard livelock, not a clean `panic()`** — the panic/reboot path never
ran. That is why it sat wedged for 8 hours instead of self-recovering.

## Timeline & log-source note

- `07:31:12` — warp-svc snapshot shows 4× `VLLM::Worker_TP` healthy, 131 GB RAM
  free, disk I/O only ~7 MB/s (workload is compute-bound, disks near-idle).
- `07:45:58` — nvme2 off the bus (above).
- `07:45:59` — last log line; hard hang.
- `15:53` — manual power-cycle (boot 0).

**Two log timelines diverged** and this misled the first pass: the systemd
**journal** for the crash boot ends at `07:30:46` (its last unflushed segment was
lost in the hard freeze), but **rsyslog** (`/var/log/syslog`) flushed all the way
to `07:45:59`. rsyslog is the authoritative timeline here. The real crash is
07:45:58, not 07:30.

## What we ruled out

- **Not thermal** — nvme2 (`nvme-pci-0400`) is the *coolest* drive (49.9 °C now);
  the ~66 °C drives are nvme0/nvme3 and are fine.
- **Not the GPUs / inference** — zero Xid / PCIe AER / GPU errors in the window;
  vLLM workers healthy right up to the freeze.
- **Not RAM/CPU** — no MCE / EDAC / ECC events; no OOM kill.
- **Not a broad power/PCIe-fabric event** — only nvme2 errored; if a rail/fabric
  glitch hit, GPUs and other NVMes would have errored too. BMC SEL shows no
  power/thermal assertions (only clock-sync events; BMC clock unreliable).
- **First occurrence** — `controller is down` appears exactly once in retained
  logs. Link is healthy now (Gen4 x4, 16 GT/s), no NVMe errors since reboot.

## Dying drive vs. transient power-state hiccup? — RESOLVED: power-state

Pulled SMART on all four (installed `nvme-cli`; did **not** restart gaius). Every
drive is health-clean, and the failed drive shows **no internal fault**:

| Drive | Serial | Power-on hrs | Wear | Media errs | Err-log | Spare | Crit-warn |
|-------|--------|-------------:|-----:|-----------:|--------:|------:|----------:|
| nvme0 | …0259  | 15,091       | 0%   | 0          | 0       | 100%  | 0 |
| nvme1 | …1926  | 14,938       | 0%   | 0          | 0       | 100%  | 0 |
| **nvme2** | …5255 | **194**   | 0%   | 0          | 0       | 100%  | 0 |
| nvme3 | …0253  | 227          | 0%   | 0          | 0       | 100%  | 0 |

Findings:
- **No SMART weakness anywhere.** 0% wear, 100% spare, 0 media errors, empty
  controller error-log, no critical warning — on all four including nvme2. Links
  all Gen4 x4, zero PCIe AER errors, no NVMe events since reboot. nvme2's own
  controller logged **no** error for the drop → it was a host-visible bus
  disappearance, not an internally-recorded media/controller fault.
- **Confirmed APST is the mechanism.** All four drives: identical firmware
  `620361WD`, `apsta=0x1` (APST enabled), deep non-operational state **ps4 =
  0.005 W with 45,700 µs (45.7 ms) exit latency**. Kernel ceiling
  `nvme_core.default_ps_max_latency_us=100000` (100 ms) > 45.7 ms, so the kernel
  **allows** the drive into that slow-to-wake state. Workload was GPU-bound
  (disks ~idle) → prime conditions for a deep-state wake failure. This is exactly
  the "faulty power saving mode" the kernel flagged.
- **The risk is not drive-specific.** Old and new drives share firmware + APST
  config, so **any of the four** can do this until APST/ASPM is disabled. nvme2
  was just the one that hit it.

### KEY FINDING — nvme2/nvme3 have a firmware timer anomaly (NOT replacements)

Owner confirmed no drives were replaced. Corroborated: `data_units_written`,
`host_read/write_commands` are ~equal across all four, and **`power_cycles` (58)
and `unsafe_shutdowns` (22) are byte-identical** on all four — impossible for
8-day-old drives. RAID0 can't rebuild, so equal `data_units_written` proves all
four have been in the stripe since creation. **Same age, never swapped.**

What's actually wrong: **only the time-based SMART counters on nvme2 and nvme3 are
corrupt.** `power_on_hours` reads 194/227 h vs a true ~15,000 h; `controller_busy_time`
is also off (643/639 vs nvme0's 193 min). Every *event* counter is correct. This
is a **controller/firmware timekeeping defect localized to the matched pair nvme2 +
nvme3** — and nvme2 is the drive that dropped off the bus.

Why it matters: **APST deep-state transitions are driven by the controller's idle
timers** (`enlat`/`exlat`). A drive with a broken internal clock is exactly what
botches a deep-power-state wake and drops off the bus. So this is **not** a generic
"all four equally exposed to APST config" situation — nvme2/nvme3 carry a real
defect, one already manifested. Treat 2 & 3 as the suspect pair.

Consequence for recommendations: keep the APST/ASPM disable (removes the
timer-driven transitions entirely). Additionally: **check WD for firmware newer
than `620361WD`** (all four are on it; a timer/APST fix would be the real cure),
and the wrong-POH-with-healthy-wear is concrete evidence for a WD support/RMA case
on nvme2/nvme3. Backup / off-RAID0 is now higher priority — two known-defective
controllers sit in a zero-redundancy stripe under the entire data plane.

## Recommendations (prioritized)

1. ~~Read SMART to rule out a failing drive~~ **DONE — all four clean** (see table
   above). No drive replacement indicated on health grounds.

2. **Apply the kernel's suggested mitigation — this is now the primary fix.**
   Confirmed APST is on with a 45.7 ms deep state under a 100 ms ceiling. Add to
   the kernel cmdline (`/etc/default/grub` `GRUB_CMDLINE_LINUX_DEFAULT`, then
   `sudo update-grub` + reboot):
   ```
   nvme_core.default_ps_max_latency_us=0 pcie_aspm=off
   ```
   `default_ps_max_latency_us=0` forbids APST from using any non-operational
   state (all have exlat > 0), keeping the drives in operational states; `pcie_aspm=off`
   removes the link-side power-save interaction. Applies to all four (shared
   firmware/APST config), not just nvme2.

3. **Auto-recover from a future wedge** instead of sitting dead for hours. This
   was a livelock, so `kernel.panic=2` didn't fire. Consider:
   ```
   kernel.hung_task_panic=1     # panic (→ reboot) on a stuck D-state task
   kernel.softlockup_panic=1
   ```
   and/or arming the **BMC hardware watchdog** so the box self-reboots when the
   kernel stops petting it. Weigh against wanting the box frozen for forensics.

4. **Reconsider RAID0 for warehouse/KB data.** Any single NVMe failure = total
   `/raid` loss and, as seen, likely a box-wide hang. Options: RAID10 (needs the
   redundancy trade-off / more drives), regular backups/snapshots of
   `/raid/signals`, and/or making the Kudu ingest + engine tolerate `/raid`
   disappearing without wedging the host.

5. **Firmware** — check for a WD SN850X firmware update (these are all the same
   model/batch; a firmware-level power-state fix, if one exists, would cover all
   four).

## Current state (post-reboot, verified)

- `/raid` mounted rw, ext4, **clean**; `md0` clean, 4 members, no ext4 errors.
- GPUs 0–3 back under vLLM load (99–100%, 119–135 W, 56–68 °C); 4–5 idle.
- 552 GB free on `/raid` (85% full).
