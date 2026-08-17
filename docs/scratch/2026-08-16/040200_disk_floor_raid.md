# Disk envelope is per write mount

`prospects-check` failed `#YK.00000005.DISK` on `/` (20Gi / 32Gi)
while RustFS lives on `/raid` (156Gi free). `assert_host_envelope`
used to walk every path in `ENVELOPE_DISK_MIN_FREE_GIB`.

Now `disk_paths_for(kind)`: prospects/FMP → `/raid` only; ambient
none; article-curate still `/` + `/raid`.
