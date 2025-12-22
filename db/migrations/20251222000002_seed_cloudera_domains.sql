-- migrate:up

-- ============================================================================
-- UPDATE EXISTING PROFILES WITH AGENTIC TEXT
-- ============================================================================

-- Cloudera profile: Enterprise data platform focus
UPDATE profiles SET
    profile_text = 'This profile focuses on Cloudera Data Platform technologies.
Prioritize documentation accuracy and operational guidance.
Key products: CDP Private Cloud Base, Kudu, Impala, NiFi/CFM, Flink/CSA.
When uncertain, cite official Cloudera documentation.
Emphasis on K8s operator patterns and data engineering best practices.',
    kb_path_prefixes = ARRAY['current/cloudera/']
WHERE name = 'cloudera';

-- Weathership profile: Research and academic focus
UPDATE profiles SET
    profile_text = 'Research profile exploring distributed computing, synthetic biology,
and philosophy of mind. Focus on arxiv papers, academic publications,
and theoretical foundations. Emphasize epistemological rigor and
cross-domain pattern recognition. Temporal grounding through curated sources.',
    kb_path_prefixes = ARRAY['current/weathership/', 'current/research/']
WHERE name = 'weathership';

-- Common profile: Shared temporal grounding
UPDATE profiles SET
    profile_text = 'Shared temporal grounding context. Contains curated news
and current events for situational awareness across all profiles.
Provides time-anchored context for agent reasoning.',
    kb_path_prefixes = ARRAY['current/common/', 'current/news/']
WHERE name = 'common';

-- ============================================================================
-- CLOUDERA PROFILE DOMAINS
-- Based on CDP Private Cloud Base product areas
-- ============================================================================

-- Get cloudera profile ID for foreign key
DO $$
DECLARE
    v_cloudera_id INTEGER;
BEGIN
    SELECT id INTO v_cloudera_id FROM profiles WHERE name = 'cloudera';

    IF v_cloudera_id IS NULL THEN
        RAISE NOTICE 'Cloudera profile not found, skipping domain seeding';
        RETURN;
    END IF;

    -- CSA: Cloudera Streaming Analytics (Flink + SQL Stream Builder)
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_cloudera_id,
        'csa',
        'CSA Operator',
        'Cloudera Streaming Analytics: Flink, SQL Stream Builder, Kafka integration',
        'CSA (Cloudera Streaming Analytics) domain covers Apache Flink,
SQL Stream Builder, and Kafka integration. Focus on K8s operator patterns,
streaming architecture, and stateful stream processing.
Current version: CSA 1.10+. Key concepts: checkpointing, state backends,
windowing, watermarks, CEP. Deployment via csa-operator Helm chart.',
        ARRAY['current/cloudera/docs/csa/', 'current/cloudera/k8s/csa-operator/']
    );

    -- Kudu: Columnar storage for fast analytics
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_cloudera_id,
        'kudu',
        'Apache Kudu',
        'Apache Kudu: Fast analytics on fast data, columnar storage',
        'Apache Kudu provides fast analytics on fast-changing data.
Columnar storage engine designed for Apache Impala and Spark workloads.
Focus on schema design, partition strategies, compaction tuning.
Key concepts: tablet servers, masters, replication, range/hash partitioning.
Integration with Impala for SQL analytics and NiFi for ingestion.',
        ARRAY['current/cloudera/docs/kudu/', 'current/kudu/']
    );

    -- Impala: MPP SQL engine
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_cloudera_id,
        'impala',
        'Apache Impala',
        'Apache Impala: MPP SQL query engine for analytics',
        'Apache Impala is a massively parallel processing (MPP) SQL engine
for interactive analytics on data stored in HDFS, Kudu, or cloud storage.
Focus on query optimization, catalog management, admission control.
Key concepts: query planning, runtime profiles, Parquet optimization.
Integration with Kudu for mutable data and Hive metastore for schema.',
        ARRAY['current/cloudera/docs/impala/']
    );

    -- CFM: Cloudera Flow Management (NiFi)
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_cloudera_id,
        'cfm',
        'CFM/NiFi',
        'Cloudera Flow Management: Apache NiFi, flow orchestration',
        'CFM (Cloudera Flow Management) provides Apache NiFi for
data flow orchestration and routing. Focus on processor configuration,
flow versioning (NiFi Registry), clustering, and security.
Key concepts: processor groups, back pressure, provenance, site-to-site.
Integration with Kafka, Kudu, HDFS, and cloud storage targets.',
        ARRAY['current/cloudera/docs/cfm/', 'current/cloudera/docs/nifi/']
    );

    -- CDP: Core platform infrastructure
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_cloudera_id,
        'cdp',
        'CDP Core',
        'CDP Private Cloud Base: Core infrastructure and management',
        'CDP Private Cloud Base provides the core infrastructure for
Cloudera Data Platform on-premises. Focus on Cloudera Manager,
cluster administration, security (Ranger, Knox), and lifecycle management.
Key concepts: parcels, host templates, LDAP integration, Kerberos, TLS.
Base services: HDFS, YARN, ZooKeeper, Hive, Spark.',
        ARRAY['current/cloudera/docs/cdp/', 'current/cloudera/docs/private-cloud/']
    );

    -- K8s Operators: Kubernetes operator patterns
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_cloudera_id,
        'operators',
        'K8s Operators',
        'Kubernetes operators for Cloudera services',
        'Kubernetes operators for deploying and managing Cloudera services.
Focus on Helm chart customization, CRD specifications, reconciliation patterns.
Key operators: csa-operator, kudu-operator, impala-operator.
Deployment patterns: StatefulSets, PVCs, service discovery, monitoring.',
        ARRAY['current/cloudera/k8s/', 'current/cloudera/operators/']
    );

END $$;

-- ============================================================================
-- WEATHERSHIP PROFILE DOMAINS
-- Research focus areas
-- ============================================================================

DO $$
DECLARE
    v_weathership_id INTEGER;
BEGIN
    SELECT id INTO v_weathership_id FROM profiles WHERE name = 'weathership';

    IF v_weathership_id IS NULL THEN
        RAISE NOTICE 'Weathership profile not found, skipping domain seeding';
        RETURN;
    END IF;

    -- LIMS: Lab Information Management System (research data)
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_weathership_id,
        'lims',
        'LIMS/Lab Data',
        'Laboratory information management and research data',
        'Laboratory Information Management System domain for tracking
experimental data, samples, protocols, and research outputs.
Focus on data provenance, reproducibility, and scientific workflows.
Integration with computational biology pipelines and analysis tools.',
        ARRAY['current/weathership/lims/', 'current/research/lab/']
    );

    -- Philosophy: Philosophy of mind and epistemology
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_weathership_id,
        'philosophy',
        'Philosophy',
        'Philosophy of mind, consciousness, epistemology',
        'Philosophy domain covering consciousness studies, epistemology,
philosophy of mind, and foundations of reasoning. Focus on sources
from PhilPapers, SEP, and major philosophy journals.
Key concepts: phenomenal consciousness, intentionality, free will,
rationality, scientific realism.',
        ARRAY['current/weathership/philosophy/', 'current/research/phil/']
    );

    -- Distributed: Distributed systems research
    INSERT INTO profile_domains (profile_id, name, display_name, description, domain_text, kb_path_prefixes)
    VALUES (
        v_weathership_id,
        'distributed',
        'Distributed Systems',
        'Distributed computing research and theory',
        'Distributed systems research covering consensus algorithms,
fault tolerance, distributed storage, and coordination protocols.
Focus on arxiv cs.DC papers and foundational research.
Key concepts: CAP theorem, Paxos, Raft, CRDT, Byzantine fault tolerance.',
        ARRAY['current/weathership/distributed/', 'current/research/cs.DC/']
    );

END $$;

-- ============================================================================
-- CLOUDERA DOCS SOURCE CONFIGURATION
-- Configure feed source for doc ETL with domains
-- ============================================================================

-- Update cloudera_docs source with domain-aware config
UPDATE feed_sources SET
    config = jsonb_set(
        config,
        '{domains}',
        '{
            "csa": {
                "path_patterns": ["/csa/", "/streaming-analytics/"],
                "archive_urls": []
            },
            "kudu": {
                "path_patterns": ["/kudu/", "/runtime/kudu/"],
                "archive_urls": []
            },
            "impala": {
                "path_patterns": ["/impala/", "/runtime/impala/"],
                "archive_urls": []
            },
            "cfm": {
                "path_patterns": ["/cfm/", "/nifi/", "/dataflow/"],
                "archive_urls": []
            },
            "cdp": {
                "path_patterns": ["/cdp-private-cloud/", "/private-cloud-base/"],
                "archive_urls": []
            }
        }'::jsonb
    )
WHERE name = 'cloudera_docs';


-- migrate:down

-- Remove weathership domains
DELETE FROM profile_domains
WHERE profile_id = (SELECT id FROM profiles WHERE name = 'weathership');

-- Remove cloudera domains
DELETE FROM profile_domains
WHERE profile_id = (SELECT id FROM profiles WHERE name = 'cloudera');

-- Reset profile text fields
UPDATE profiles SET
    profile_text = NULL,
    kb_path_prefixes = '{}'
WHERE name IN ('cloudera', 'weathership', 'common');

-- Reset cloudera_docs config
UPDATE feed_sources SET
    config = config - 'domains'
WHERE name = 'cloudera_docs';
