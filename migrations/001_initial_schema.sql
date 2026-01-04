-- TourRAG Database Schema
-- PostgreSQL 14+ with PostGIS extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 1. 景点主表（OSM 实体层）
-- ============================================
CREATE TABLE viewpoint_entity (
    viewpoint_id BIGSERIAL PRIMARY KEY,
    osm_type VARCHAR(20) NOT NULL CHECK (osm_type IN ('node', 'way', 'relation')),
    osm_id BIGINT NOT NULL,
    name_primary VARCHAR(500) NOT NULL,
    name_variants JSONB DEFAULT '{}'::jsonb,  -- {name:en, name:zh, alt_name, short_name, ...}
    category_osm JSONB DEFAULT '{}'::jsonb,  -- OSM原始标签
    category_norm VARCHAR(100),              -- 标准化类别
    geom GEOMETRY(GEOMETRY, 4326),          -- PostGIS geometry
    admin_area_ids JSONB DEFAULT '[]'::jsonb, -- 行政区关联
    popularity FLOAT DEFAULT 0.0,            -- 派生热度指标
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(osm_type, osm_id)
);

-- Indexes for viewpoint_entity
CREATE INDEX idx_viewpoint_entity_name_primary ON viewpoint_entity USING gin(name_primary gin_trgm_ops);
CREATE INDEX idx_viewpoint_entity_name_variants ON viewpoint_entity USING gin(name_variants);
CREATE INDEX idx_viewpoint_entity_category_norm ON viewpoint_entity(category_norm);
CREATE INDEX idx_viewpoint_entity_geom ON viewpoint_entity USING gist(geom);
CREATE INDEX idx_viewpoint_entity_popularity ON viewpoint_entity(popularity DESC);

-- ============================================
-- 2. 历史信息表（百科本地镜像）
-- ============================================
CREATE TABLE viewpoint_wiki (
    viewpoint_id BIGINT PRIMARY KEY REFERENCES viewpoint_entity(viewpoint_id) ON DELETE CASCADE,
    wikipedia_title VARCHAR(500) NOT NULL,
    wikipedia_lang VARCHAR(10) NOT NULL DEFAULT 'en',
    extract_text TEXT,                       -- 摘要文本
    sections JSONB DEFAULT '[]'::jsonb,      -- 章节结构
    citations JSONB DEFAULT '[]'::jsonb,     -- 引用信息
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_viewpoint_wiki_title ON viewpoint_wiki(wikipedia_title);
CREATE INDEX idx_viewpoint_wiki_lang ON viewpoint_wiki(wikipedia_lang);

CREATE TABLE viewpoint_wikidata (
    viewpoint_id BIGINT PRIMARY KEY REFERENCES viewpoint_entity(viewpoint_id) ON DELETE CASCADE,
    wikidata_qid VARCHAR(20) NOT NULL,       -- Q12345
    claims JSONB DEFAULT '{}'::jsonb,        -- Wikidata claims
    sitelinks_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_viewpoint_wikidata_qid ON viewpoint_wikidata(wikidata_qid);

-- ============================================
-- 3. 视觉特点表（核心设计）
-- ============================================
CREATE TABLE viewpoint_visual_tags (
    id BIGSERIAL PRIMARY KEY,
    viewpoint_id BIGINT NOT NULL REFERENCES viewpoint_entity(viewpoint_id) ON DELETE CASCADE,
    season VARCHAR(20) NOT NULL CHECK (season IN ('spring', 'summer', 'autumn', 'winter', 'unknown')),
    tags JSONB NOT NULL DEFAULT '[]'::jsonb, -- Array of tag strings
    confidence FLOAT DEFAULT 0.0 CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSONB DEFAULT '{}'::jsonb,     -- {source, file_id, sentence_hash, ...}
    tag_source VARCHAR(50) NOT NULL CHECK (tag_source IN (
        'commons_vision',
        'wiki_weak_supervision',
        'user_image',
        'manual'
    )),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(viewpoint_id, season, tag_source)
);

CREATE INDEX idx_viewpoint_visual_tags_viewpoint ON viewpoint_visual_tags(viewpoint_id);
CREATE INDEX idx_viewpoint_visual_tags_season ON viewpoint_visual_tags(season);
CREATE INDEX idx_viewpoint_visual_tags_tags ON viewpoint_visual_tags USING gin(tags);
CREATE INDEX idx_viewpoint_visual_tags_source ON viewpoint_visual_tags(tag_source);

-- ============================================
-- 4. Commons 图像元信息表（不存图）
-- ============================================
CREATE TABLE viewpoint_commons_assets (
    id BIGSERIAL PRIMARY KEY,
    viewpoint_id BIGINT NOT NULL REFERENCES viewpoint_entity(viewpoint_id) ON DELETE CASCADE,
    commons_file_id VARCHAR(500) NOT NULL,   -- File:Example.jpg
    commons_page VARCHAR(500),
    caption TEXT,
    categories JSONB DEFAULT '[]'::jsonb,
    depicts_wikidata JSONB DEFAULT '[]'::jsonb, -- Array of QIDs
    timestamp TIMESTAMP WITH TIME ZONE,
    hash VARCHAR(64),                       -- SHA256 hash
    license VARCHAR(100),
    local_path_or_blob_ref VARCHAR(1000),   -- 如允许的本地引用
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(viewpoint_id, commons_file_id)
);

CREATE INDEX idx_viewpoint_commons_viewpoint ON viewpoint_commons_assets(viewpoint_id);
CREATE INDEX idx_viewpoint_commons_file_id ON viewpoint_commons_assets(commons_file_id);
CREATE INDEX idx_viewpoint_commons_categories ON viewpoint_commons_assets USING gin(categories);
CREATE INDEX idx_viewpoint_commons_hash ON viewpoint_commons_assets(hash);

-- ============================================
-- 5. Tag 词表版本管理
-- ============================================
CREATE TABLE tag_schema_version (
    version VARCHAR(50) PRIMARY KEY,
    schema_definition JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 6. 查询日志表（用于审计和回归测试）
-- ============================================
CREATE TABLE query_log (
    id BIGSERIAL PRIMARY KEY,
    user_text TEXT,
    user_images JSONB DEFAULT '[]'::jsonb,
    query_intent JSONB NOT NULL,
    sql_queries JSONB DEFAULT '[]'::jsonb,
    tool_calls JSONB DEFAULT '[]'::jsonb,
    results JSONB,
    execution_time_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_query_log_created_at ON query_log(created_at DESC);

-- ============================================
-- 7. 辅助函数：更新 updated_at 时间戳
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_viewpoint_entity_updated_at BEFORE UPDATE ON viewpoint_entity
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_viewpoint_visual_tags_updated_at BEFORE UPDATE ON viewpoint_visual_tags
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 8. 辅助函数：名称相似度搜索
-- ============================================
CREATE OR REPLACE FUNCTION name_similarity_score(query_text TEXT, entity_name TEXT, variants JSONB)
RETURNS FLOAT AS $$
DECLARE
    max_score FLOAT := 0.0;
    variant_value TEXT;
BEGIN
    -- Check primary name
    max_score := GREATEST(max_score, similarity(query_text, entity_name));
    
    -- Check variants
    FOR variant_value IN SELECT jsonb_array_elements_text(variants)
    LOOP
        max_score := GREATEST(max_score, similarity(query_text, variant_value));
    END LOOP;
    
    RETURN max_score;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

