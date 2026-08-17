# GPU co-tenancy participation contract — draft for signals-protocol

**Date:** 2026-07-27
**Context:** Same-day follow-up to `155643_federation_submodule_scheduler_maturity.md`.
Gaius's cleanup paths are now lease-aware (spare live `/tmp/zndx-gpu-leases` holders and
their descendants — verified live against aegir's GPU 0–3 lease). RH: "we'll have to teach
the other engines how to participate effectively in the federation." This note is the
teaching material — the participation contract, drafted here first per the signals-protocol
rule (changes land there by PR visible to all three projects, then propagate by submodule
bump). Target: a `CO-TENANCY.md` (or spec-doc section) in `zndx/signals-protocol`.

---

## Finding: the lock convention has a set-granularity hole

`claim_gpus` (aegir `gpu_guard.py`, atelier equivalent) derives the flock filename from the
exact sorted GPU set: `gpu-0-1-2-3.lock`. Overlapping-but-different sets produce different
filenames — aegir holding `gpu-0-1-2-3.lock` does not conflict with a claim of
`gpu-2-3.lock`. Both flocks succeed; the cooperative layer sees nothing. The nvidia-smi
probe backstops only after a foreign process holds ≥512 MiB on a target GPU, so two engines
claiming overlapping sets **while the GPUs are still idle** pass both checks and OOM later
mid-model-load. Overlap must be detected by intersecting the target set against **all** live
`*.owner.json` `gpus` arrays — filename identity is not a conflict test.

## The contract (v1 — advisory co-tenancy)

An engine participates effectively when it follows all six rules:

- **R1 — Claim before you bind.** Before starting anything that will hold GPU memory,
  acquire the per-set flock in the shared lease dir and write `<set>.owner.json`
  (`{pid, project, role, gpus, ts, host}`). flock auto-releases if the holder dies.
- **R2 — Intersect, don't just lock.** After (or while) acquiring the flock, read every
  other live `owner.json` and refuse if any live holder's `gpus` intersects the target set.
  (Closes the granularity hole; none of the three engines does this today.)
- **R3 — Probe before you claim.** nvidia-smi compute-apps check on the target GPUs
  (min_mib=512 convention) as the authoritative backstop — catches non-participants.
- **R4 — Never kill what a lease protects.** Every cleanup/kill path spares any process
  that is a live lease holder or its descendant. Stale leases (dead holder pid) are
  ignored — dead siblings never block cleanup. *(Gaius: done 2026-07-27 in
  `scripts/lib/gpu-helpers.sh` `_kill_unleased` + `engine/resources/gpu_leases.py`;
  both usable as reference implementations.)*
- **R5 — Release what you drop.** Remove the lease on clean shutdown/reallocation.
  Readers always verify holder liveness, so crashes degrade safely.
- **R6 — Re-lease on reallocation.** Dynamic engines (gaius moves endpoints across GPUs)
  hold one lease per disjoint set currently bound and re-lease when the allocation changes,
  including transient workloads (render eviction windows, flow GPU bursts).

## Homework by project

| project | work |
|---|---|
| gaius | **Write leases** (R1/R5/R6) in the orchestrator endpoint lifecycle — the missing half of mutuality; siblings currently see gaius only via their nvidia-smi probes. R2 when claiming. R4 done. |
| aegir | R2 overlap intersection in `gpu_guard.claim_gpus`; audit any kill/cleanup paths for R4 (supervisor restarts?). |
| atelier | Same as aegir (guard is the shared pattern). |
| signals-protocol | Land this contract as `CO-TENANCY.md`; optionally vendor the R4 reference helpers (bash + python) beside the proto so all three lift the same code. |

## Graduation path (beyond advisory)

1. **Visibility:** engines advertise `gpu_ids` per endpoint via `zndx.engine.v1.Status`
   (field already exists) — dashboards and peers see allocation, not just leases.
2. **Arbitration:** gaius exposes `BeginWorkload` on the v1 face — siblings request GPU
   windows from the CP-SAT makespan scheduler instead of racing for leases (plan, not refuse).
3. **Optional single pane:** the YuniKorn-on-RKE2 mode (placeholder pods mirroring engine
   workloads, YK queues per project) — recorded 155643 addendum; needs its own design note.

## Next steps

- [ ] Gaius lease-writing (R1/R5/R6) in orchestrator endpoint lifecycle
- [ ] PR this contract to zndx/signals-protocol as CO-TENANCY.md; submodule bump ×3
- [ ] Sibling sessions pick up R2 + R4 audits from the contract
