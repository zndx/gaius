# HS2 `CREATE ... STORED AS KUDU` crash-looped the shared tablet server

Building out the cognition/DCGM tiers, I created two Kudu tables through
Impala HS2. That put the federation's single tablet server into a SIGSEGV
restart loop for ~80 minutes. Dropping the two tables stopped it.

## Evidence

```text
first crash            2026-08-25 17:38:34 UTC
cognition_metrics_tier0 created 17:23:02   (HS2 CREATE ... STORED AS KUDU)
gpu_dcgm_tier0          created 17:29:04   (same)
crashes                415, roughly one every 8-10s
signature              SIGSEGV (@0x0), PC 0x0, stack unresolvable, minidump written
tables dropped         18:56
last crash             18:57:01
tserver uptime after   5:44 and climbing (was ~9s)
```

It is not a corrupt tablet. Bootstraps completed before the crash varied
(24, 34, 49, 41, 56, 38 of 56), several runs finished *all* tablets and still
died, and no unfinished tablet was common across runs. The one tablet it
happened to die near belongs to `gpu_metrics_tier0`, which predates today.

## Why this was foreseeable

`scripts/gpu_metrics_kudu_ingest.py` says it outright:

```python
# HS2 CREATE TABLE STORED AS Kudu hits Java SASL (KUDU-2121). Retry slowly.
```

which is why the repo carries `scripts/gpu_kudu_create.cc` — a C++ Kudu client
that creates `gpu_metrics_tier0` directly. I used HS2 because
`impala_fdw_exec` is fenced to range-partition DDL and HS2 was the path that
appeared to work: `CREATE TABLE` returned OK, `DESCRIBE` returned the schema,
`SHOW TABLES` listed it, and the table read and wrote correctly. Nothing
failed in the foreground. The damage showed up only in the tablet server.

## Two further deviations from the proven table

`gpu_kudu_create.cc` builds `gpu_metrics_tier0` as:

```cpp
b.AddColumn("epoch_hour")->Type(INT32)->NotNull();
b.AddColumn("ts_ns")     ->Type(INT64)->NotNull();
b.AddColumn("gpu_index") ->Type(INT32)->NotNull();
...                                     // all measures NotNull
b.SetPrimaryKey({"epoch_hour", "ts_ns", "gpu_index"});   // all INT
c->add_hash_partitions({"gpu_index"}, 2);
c->set_range_partition_columns({"epoch_hour"});
c->num_replicas(1);
```

Mine differed in two ways beyond the creation path:

- **STRING in the primary key** — `channel` and `field`. The proven table's PK
  is entirely integer.
- **Nullable non-PK columns**, the HS2 default, against `NotNull` throughout.

Either could matter. The creation path is the one the codebase already warns
about, so it is the first thing to change.

## Operational lesson for the tiering design

Hash × range means every UTC hour adds `hash_buckets` tablets *per table*.
`gpu_metrics_tier0` was at 42 tablets for ~21 hours. Adding two more tables at
2 buckets each tripled hourly tablet creation on a single-tserver Kudu.

That is the pressure the tiered design exists to relieve: `DROP RANGE
PARTITION` after an Iceberg+HDF5 verify is the only thing that bounds tablet
count. **A tier0 table must not go live before its tier-up path exists**, or
it grows without a valve. `gpu_metrics_settle` covers only `gpu_metrics`.

## State now

Rolled back to a working warehouse:

- Kudu: `gpu_metrics_tier0`, `kudu_types_probe` only. Stable.
- Impala: `gpu_metrics{,_tier0,_tier1}`. The two Polaris/Iceberg tiers I
  registered were dropped with their views.
- Postgres (`:5444`, `:5455`): foreign tables back to the `gpu_metrics` family.
- Gaius: the ingest writes `gpu_metrics_tier0` only; cognition/DCGM writes and
  the cognition read are parked in place with a pointer to this note. The
  DCGM extended-field *capture* stays (it is free and harmless).
- `:5444` had exhausted `max_connections` — the ingest's error path reconnects
  each tick and had been failing for ~20 minutes. The engine restart cleared it.

Kept, because they are independent and correct:

- **impala_fdw parameterised pushdown** (`a596ab4`). `foreign_expr_walker` had
  no `Param` case, so every `$1`/`$2` qual was classified local and full
  scanned: 12.92s vs 0.02s for the identical 66-row window. Now 0.01-0.02s.
- **Waterfall reads tier0 with a reused connection**. Opening a backend costs
  a full impala_fdw session (Kerberos + Kudu client + metadata), measured at
  2.8-15.7s; the strip made two fresh connections per poll and 503'd against
  the Discover surface's 4s budget.

## The outstanding blocker for transparent hierarchy

The Iceberg HDF5 tier does not evaluate predicates. Straight to Impala:

```text
gpu_metrics_tier0  WHERE ts_ns = <one instant>  ->        6 rows
gpu_metrics_tier1  WHERE ts_ns = <one instant>  ->  493,476 rows   (all of it)
gpu_metrics (view)                              ->  493,482 rows
```

`EXPLAIN VERBOSE` shows the FDW sending `WHERE ts_ns = …`; the custom HDF5
FileFormat reader returns every row regardless. **Any filtered query against
tier1 or a union view returns wrong answers**, not merely slow ones. Until
that is fixed the hierarchy cannot be transparent — a reader has to know which
tier it is talking to, which is exactly what the design is meant to abolish.

## Correct path forward

1. Fix the HDF5 reader's predicate evaluation. Nothing else about the
   hierarchy is trustworthy until a filtered read of tier1 is correct.
2. Generalise `gpu_kudu_create.cc` into a creator that takes a schema, and
   create `cognition_metrics_tier0` / `gpu_dcgm_tier0` through it — all-INT
   primary key (`channel_id` / `field_id` rather than STRING), `NotNull`
   throughout, mirroring the proven table.
3. Extend tier-up to the new products *before* they take writes, so every
   tier0 has a `DROP RANGE PARTITION` valve from day one.
4. Only then re-enable the ingest writes and the cognition read.
