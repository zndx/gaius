-- migrate:up
-- Admitted 512-token items (Gaius inbound, Aegir grain) and
-- positional CLT/SAE activations that ground the contrib SKOS.

CREATE TABLE IF NOT EXISTS public.admitted_item (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    text TEXT NOT NULL,
    aperture_code TEXT NOT NULL DEFAULT '',
    margin DOUBLE PRECISION NOT NULL DEFAULT 0,
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, char_start, char_end)
);
CREATE INDEX IF NOT EXISTS admitted_item_source ON public.admitted_item (source_id);
CREATE INDEX IF NOT EXISTS admitted_item_admitted ON public.admitted_item (admitted_at DESC);

CREATE TABLE IF NOT EXISTS public.activation (
    id BIGSERIAL PRIMARY KEY,
    item_id BIGINT NOT NULL REFERENCES public.admitted_item (id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    layer INTEGER NOT NULL,
    feature_idx INTEGER NOT NULL,
    position INTEGER NOT NULL,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    activation DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS activation_item ON public.activation (item_id);
CREATE INDEX IF NOT EXISTS activation_feat ON public.activation (model, layer, feature_idx);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.admitted_item TO gaius;
GRANT USAGE, SELECT ON SEQUENCE public.admitted_item_id_seq TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.activation TO gaius;
GRANT USAGE, SELECT ON SEQUENCE public.activation_id_seq TO gaius;
