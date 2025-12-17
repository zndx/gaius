-- migrate:up
-- Topic modeling tables for corpus, models, rubrics, and scores

-- Corpus versions track the state of document collections
CREATE TABLE corpus_versions (
    id SERIAL PRIMARY KEY,
    version_id VARCHAR(128) UNIQUE NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    vocabulary_size INTEGER NOT NULL DEFAULT 0,
    minio_path TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_corpus_versions_created ON corpus_versions(created_at DESC);

COMMENT ON TABLE corpus_versions IS 'Tracks corpus snapshots for incremental topic model training';

-- Topic models with training metadata
CREATE TABLE topic_models (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(128) UNIQUE NOT NULL,
    model_type VARCHAR(32) NOT NULL,  -- lda, lsa, hdp, bertopic
    corpus_version_id INTEGER REFERENCES corpus_versions(id),
    num_topics INTEGER,               -- NULL for HDP/BERTopic (auto-discovered)
    discovered_topics INTEGER,        -- Actual topics found
    coherence_cv FLOAT,              -- C_v coherence score
    minio_path TEXT NOT NULL,
    training_params JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_topic_models_type ON topic_models(model_type);
CREATE INDEX idx_topic_models_created ON topic_models(created_at DESC);

COMMENT ON TABLE topic_models IS 'Trained topic models (LDA, LSA, HDP, BERTopic) with lineage';

-- Scoring rubrics for paper selection
CREATE TABLE scoring_rubrics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    version VARCHAR(32) NOT NULL,
    config JSONB NOT NULL,           -- Full rubric definition
    model_preference VARCHAR(32) DEFAULT 'ensemble',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, version)
);

CREATE INDEX idx_scoring_rubrics_name ON scoring_rubrics(name);

COMMENT ON TABLE scoring_rubrics IS 'Versioned scoring rubrics for LLM paper evaluation';

-- Paper scores with lineage to rubric and model
CREATE TABLE paper_scores (
    id SERIAL PRIMARY KEY,
    arxiv_id VARCHAR(64) NOT NULL,
    rubric_id INTEGER REFERENCES scoring_rubrics(id),
    overall_score FLOAT NOT NULL,
    criteria_scores JSONB NOT NULL,  -- {criterion_name: score}
    model_used VARCHAR(64) NOT NULL,
    reasoning TEXT,
    confidence FLOAT,
    metaflow_run_id VARCHAR(128),    -- Link to Metaflow run
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_paper_scores_arxiv ON paper_scores(arxiv_id);
CREATE INDEX idx_paper_scores_overall ON paper_scores(overall_score DESC);
CREATE INDEX idx_paper_scores_run ON paper_scores(metaflow_run_id);

COMMENT ON TABLE paper_scores IS 'LLM-scored paper relevance with rubric lineage';

-- Document-topic assignments from topic model inference
CREATE TABLE document_topics (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(256) NOT NULL,  -- KB path or arxiv_id
    model_id INTEGER REFERENCES topic_models(id),
    topics JSONB NOT NULL,               -- [{topic_id, weight}, ...]
    top_words JSONB,                     -- {topic_id: [words], ...}
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_document_topics_doc ON document_topics(document_id);
CREATE INDEX idx_document_topics_model ON document_topics(model_id);

COMMENT ON TABLE document_topics IS 'Topic assignments for documents';

-- migrate:down
DROP TABLE IF EXISTS document_topics;
DROP TABLE IF EXISTS paper_scores;
DROP TABLE IF EXISTS scoring_rubrics;
DROP TABLE IF EXISTS topic_models;
DROP TABLE IF EXISTS corpus_versions;
