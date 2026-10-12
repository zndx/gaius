# Decisions GPU handover

A workload that asks for `decisions` needs the whole box: thinking stays on
the heavy queue (4 GPUs) and two `d3-flash` replicas take both light seats.
Hermes moshi was holding GPU 5. Gaius does not kill that process and does
not dial another project's `Engine/Yield`.

Signals is the indication. Kind `decisions` is a coordination activity that
claims `root.internal.inference.heavy` 4 and `root.internal.inference.light`
2, precludes `agent-rtc`, `medium`, and `extract`, and sets posture
`federation.gpu=yield`. Light and heavy are not precluded, because the
declarer has to admit thinking and the replicas. Priority is 200 so the
claim wins arbitration. The activity is in force only while it is
`RUNNING`. Peers other than `activity.peer` stop their own GPU host
processes and drop their leases. If they have not done so within 150s,
BeginWorkload fails with `#CO.00000010.NOHANDOVER` and does not start CUDA
on a foreign card.

Gaius declares that activity before it places the replicas, heartbeats
every 60s (horizon 2h, under the 180s lease TTL), and releases it when the
workload completes or the deploy fails. The Hermes signals plugin is the
peer that yields: a running `federation.gpu=yield` from anyone but Hermes
POSTs the local moshi supervisor `/interactive/off`. `/interactive/on`
happens when the activity ends only if moshi was serving and the
interactive session is still running.

Unit checks: signals `test_activities.py` 20 passed; gaius handover
declaration plus `test_coordination.py` 40 passed; Hermes
`test_gpu_handover.py` 5 passed. The live engine has not been restarted
onto this code, so `/decide` still sees no replicas.
