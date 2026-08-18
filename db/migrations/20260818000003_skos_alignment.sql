-- migrate:up
-- ACP verdicts on CLT/SAE ↔ SDG SKOS alignments.

CREATE TABLE IF NOT EXISTS public.skos_alignment (
    id BIGSERIAL PRIMARY KEY,
    clt_uri TEXT NOT NULL,
    sae_uri TEXT NOT NULL DEFAULT '',
    sdg_uri TEXT NOT NULL DEFAULT '',
    match_kind TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    item_ids BIGINT[] NOT NULL DEFAULT '{}',
    run_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS skos_alignment_clt ON public.skos_alignment (clt_uri);
CREATE INDEX IF NOT EXISTS skos_alignment_verdict ON public.skos_alignment (verdict);

GRANT SELECT, INSERT, UPDATE ON public.skos_alignment TO gaius;
GRANT USAGE, SELECT ON SEQUENCE public.skos_alignment_id_seq TO gaius;
