-- migrate:up

-- ============================================================================
-- PROFILES
-- ============================================================================

-- Common profile for shared temporal grounding
INSERT INTO profiles (name, description, feed_config) VALUES
(
    'common',
    'Shared temporal grounding from curated news sources',
    '{"purpose": "temporal_grounding", "shared": true}'
);

-- Weathership profile - Research/academic focus
INSERT INTO profiles (name, description, feed_config) VALUES
(
    'weathership',
    'Research profile: distributed computing, synthetic biology, philosophy of mind',
    '{
        "focus_areas": [
            "distributed_computing",
            "synthetic_biology",
            "philosophy_of_mind",
            "epistemology",
            "consciousness"
        ],
        "sources": ["arxiv", "biorxiv", "philpapers"]
    }'
);

-- Cloudera profile - Enterprise/industry focus
INSERT INTO profiles (name, description, feed_config) VALUES
(
    'cloudera',
    'Enterprise profile: Cloudera docs, data platform industry trends',
    '{
        "focus_areas": [
            "data_engineering",
            "distributed_systems",
            "enterprise_data_platforms"
        ],
        "sources": ["docs", "industry_blogs"]
    }'
);

-- ============================================================================
-- FEED SOURCES - Common (Temporal Grounding)
-- ============================================================================

-- NOTE: legiblenews.com/feed returns 404 as of 2025-11-30
-- TODO: Implement 'brave' source type for sites without RSS feeds
-- Brave Search API explicitly allows storing/using results in AI pipelines
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes, active) VALUES
(
    'legiblenews',
    'rss',
    'https://legiblenews.com',
    '{
        "feed_url": "https://legiblenews.com/feed",
        "purpose": "temporal_grounding",
        "max_items": 50,
        "status": "feed_unavailable_2025-11-30",
        "alternative": "Use brave source type with query: site:legiblenews.com"
    }',
    60,  -- Hourly
    false  -- INACTIVE: feed URL returns 404, consider brave source type
);

-- ============================================================================
-- FEED SOURCES - Weathership Profile
-- ============================================================================

-- arXiv: Distributed, Parallel, and Cluster Computing
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'arxiv_cs_dc',
    'arxiv',
    'https://arxiv.org',
    '{
        "categories": ["cs.DC"],
        "feeds": [
            "https://arxiv.org/list/cs.DC/new",
            "https://arxiv.org/list/cs.DC/recent"
        ],
        "api_url": "http://export.arxiv.org/api/query",
        "max_results": 100,
        "description": "Distributed, Parallel, and Cluster Computing"
    }',
    360  -- Every 6 hours
);

-- bioRxiv: Synthetic Biology
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'biorxiv_synbio',
    'biorxiv',
    'https://www.biorxiv.org',
    '{
        "collection": "synthetic-biology",
        "feed_url": "https://www.biorxiv.org/collection/synthetic-biology.rss",
        "api_url": "https://api.biorxiv.org/details/biorxiv",
        "max_results": 50
    }',
    360  -- Every 6 hours
);

-- PhilPapers: Philosophy sources
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'philpapers',
    'philpapers',
    'https://philpapers.org',
    '{
        "areas": [
            "epistemology",
            "philosophy-of-mind",
            "aesthetics",
            "logic-and-philosophy-of-logic",
            "freedom-and-liberty",
            "theories-of-free-will",
            "temporal-experience",
            "consciousness"
        ],
        "search_urls": {
            "epistemology": "/browse/epistemology",
            "philosophy_of_mind": "/browse/philosophy-of-mind",
            "consciousness": "/browse/consciousness",
            "free_will": "/browse/free-will"
        },
        "note": "May require agentic scraping for full content"
    }',
    1440  -- Daily
);

-- PhilEvents: Philosophy events and papers
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'philevents',
    'api',
    'https://philevents.org',
    '{
        "topics": [
            "epistemology",
            "philosophy-of-mind",
            "consciousness",
            "free-will"
        ],
        "note": "Events and CFPs in philosophy"
    }',
    1440  -- Daily
);

-- ============================================================================
-- FEED SOURCES - Cloudera Profile
-- ============================================================================

-- Cloudera Documentation
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'cloudera_docs',
    'docs',
    'https://docs.cloudera.com',
    '{
        "sitemap_url": "https://docs.cloudera.com/sitemap.xml",
        "priority_paths": [
            "/cdp-private-cloud/",
            "/cdp-public-cloud/",
            "/machine-learning/",
            "/data-engineering/",
            "/dataflow/"
        ],
        "exclude_patterns": ["/_archive/", "/older-versions/"]
    }',
    10080  -- Weekly
);

-- Cloudera Main Site / Blog
-- NOTE: blog.cloudera.com/feed/ redirects to main site (no RSS) as of 2025-11-30
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes, active) VALUES
(
    'cloudera_blog',
    'rss',
    'https://www.cloudera.com',
    '{
        "feed_url": "https://blog.cloudera.com/feed/",
        "topics": ["engineering", "product", "data-platform"],
        "status": "feed_unavailable_2025-11-30"
    }',
    1440,  -- Daily
    false  -- INACTIVE: redirects to non-RSS page
);

-- Databricks (industry peer)
-- Working feed discovered via Brave Search: https://www.databricks.com/feed
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'databricks_blog',
    'rss',
    'https://www.databricks.com',
    '{
        "feed_url": "https://www.databricks.com/feed",
        "topics": ["engineering", "lakehouse", "spark"]
    }',
    1440  -- Daily
);

-- Temporal.io (workflow orchestration)
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'temporal_blog',
    'rss',
    'https://temporal.io',
    '{
        "feed_url": "https://temporal.io/blog/feed.xml",
        "topics": ["workflows", "distributed-systems", "orchestration"]
    }',
    1440  -- Daily
);

-- Crusoe.ai (GPU cloud)
INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes) VALUES
(
    'crusoe_blog',
    'scraper',
    'https://crusoe.ai',
    '{
        "blog_path": "/blog",
        "topics": ["gpu", "cloud", "ai-infrastructure"],
        "note": "May need scraper - check for RSS"
    }',
    1440  -- Daily
);

-- ============================================================================
-- PROFILE-SOURCE ASSOCIATIONS
-- ============================================================================

-- Common profile gets legiblenews
INSERT INTO profile_sources (profile_id, source_id, weight)
SELECT p.id, s.id, 1.0
FROM profiles p, feed_sources s
WHERE p.name = 'common' AND s.name = 'legiblenews';

-- Weathership profile gets research sources
INSERT INTO profile_sources (profile_id, source_id, weight)
SELECT p.id, s.id,
    CASE s.name
        WHEN 'arxiv_cs_dc' THEN 1.0
        WHEN 'biorxiv_synbio' THEN 0.8
        WHEN 'philpapers' THEN 0.9
        WHEN 'philevents' THEN 0.7
        ELSE 0.5
    END
FROM profiles p, feed_sources s
WHERE p.name = 'weathership'
  AND s.name IN ('arxiv_cs_dc', 'biorxiv_synbio', 'philpapers', 'philevents');

-- Weathership also inherits common sources (for temporal grounding)
INSERT INTO profile_sources (profile_id, source_id, weight)
SELECT p.id, s.id, 0.5  -- Lower weight for grounding
FROM profiles p, feed_sources s
WHERE p.name = 'weathership' AND s.name = 'legiblenews';

-- Cloudera profile gets enterprise sources
INSERT INTO profile_sources (profile_id, source_id, weight)
SELECT p.id, s.id,
    CASE s.name
        WHEN 'cloudera_docs' THEN 1.0
        WHEN 'cloudera_blog' THEN 0.9
        WHEN 'databricks_blog' THEN 0.7
        WHEN 'temporal_blog' THEN 0.6
        WHEN 'crusoe_blog' THEN 0.5
        ELSE 0.5
    END
FROM profiles p, feed_sources s
WHERE p.name = 'cloudera'
  AND s.name IN ('cloudera_docs', 'cloudera_blog', 'databricks_blog', 'temporal_blog', 'crusoe_blog');

-- Cloudera also inherits common sources
INSERT INTO profile_sources (profile_id, source_id, weight)
SELECT p.id, s.id, 0.5
FROM profiles p, feed_sources s
WHERE p.name = 'cloudera' AND s.name = 'legiblenews';


-- migrate:down

DELETE FROM profile_sources;
DELETE FROM feed_sources;
DELETE FROM profiles;
