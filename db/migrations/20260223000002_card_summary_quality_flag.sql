-- Add needs_retry flag to card_summaries
-- Marks entries where generation produced low-quality output
-- (e.g., frontier summary with zero Brave citations for recent/uncrawled papers)

ALTER TABLE collections.card_summaries
ADD COLUMN IF NOT EXISTS needs_retry BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN collections.card_summaries.needs_retry IS
  'True when generation produced low-quality output (e.g., frontier with zero citations)';
