-- migrate:up

-- ============================================================================
-- SEED 'OPEN' DOMAIN FOR COMMON PROFILE
--
-- Semantic distinction:
--   NULL domain  = No domain specified (absence of constraint)
--   'open' domain = Explicit Open World Assumption - class/property definitions
--                   apply to any relevant individual, including ones not yet
--                   represented in the knowledge base
--
-- This aligns with OWL's Open World Assumption where the absence of information
-- does not imply falsity. Explicitly choosing 'open' signals intent to work
-- with an extensible ontology.
-- ============================================================================

-- Create 'open' domain for common profile with semantic description
INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, is_active)
SELECT
    p.id,
    'open',
    'Open Domain',
    'Open-domain ontology where definitions apply to any relevant individual',
    'Open World Assumption: Class and property definitions extend beyond the ' ||
    'closed set of known individuals. New entities may be introduced without ' ||
    'schema modification. Suitable for exploratory research, cross-domain ' ||
    'synthesis, and general-purpose agent operations.',
    TRUE  -- Set as active domain for common profile
FROM profiles p
WHERE p.name = 'common'
ON CONFLICT (profile_id, name) DO UPDATE
SET is_active = TRUE,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    domain_text = EXCLUDED.domain_text;

-- migrate:down

-- Remove 'open' domain from common profile
DELETE FROM profile_domains
WHERE name = 'open'
AND profile_id = (SELECT id FROM profiles WHERE name = 'common');
