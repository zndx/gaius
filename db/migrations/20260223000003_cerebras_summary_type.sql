-- Add 'cerebras' to summary_type CHECK constraints
-- Enables Cerebras GLM-4.7 thinking summaries alongside frontier and open_weights

-- card_summaries
ALTER TABLE collections.card_summaries
  DROP CONSTRAINT IF EXISTS card_summaries_summary_type_check;
ALTER TABLE collections.card_summaries
  ADD CONSTRAINT card_summaries_summary_type_check
  CHECK (summary_type IN ('frontier', 'open_weights', 'cerebras'));

-- collection_summaries
ALTER TABLE collections.collection_summaries
  DROP CONSTRAINT IF EXISTS collection_summaries_summary_type_check;
ALTER TABLE collections.collection_summaries
  ADD CONSTRAINT collection_summaries_summary_type_check
  CHECK (summary_type IN ('frontier', 'open_weights', 'cerebras'));
