-- Database Schema Export
-- Exported at: 2026-01-15T16:20:20.582355


-- Table: query_log
CREATE TABLE query_log (id bigint NOT NULL, user_text text, user_images jsonb, query_intent jsonb NOT NULL, sql_queries jsonb, tool_calls jsonb, results jsonb, execution_time_ms integer, created_at timestamp with time zone);


-- Table: spatial_ref_sys
CREATE TABLE spatial_ref_sys (srid integer NOT NULL, auth_name character varying, auth_srid integer, srtext character varying, proj4text character varying);


-- Table: tag_schema_version
CREATE TABLE tag_schema_version (version character varying NOT NULL, schema_definition jsonb NOT NULL, created_at timestamp with time zone);


-- Table: viewpoint_ai_summaries
CREATE TABLE viewpoint_ai_summaries (id bigint NOT NULL, viewpoint_id bigint NOT NULL, history_summary text, search_summary text, season_info jsonb, visual_tags jsonb, source character varying NOT NULL, created_at timestamp with time zone, updated_at timestamp with time zone);


-- Table: viewpoint_commons_assets
CREATE TABLE viewpoint_commons_assets (id bigint NOT NULL, viewpoint_id bigint NOT NULL, commons_file_id character varying NOT NULL, commons_page character varying, caption text, categories jsonb, depicts_wikidata jsonb, "timestamp" timestamp with time zone, hash character varying, license character varying, local_path_or_blob_ref character varying, created_at timestamp with time zone, image_blob bytea, image_geometry geometry, image_exif jsonb, image_width integer, image_height integer, image_format character varying, file_size_bytes bigint, downloaded_at timestamp with time zone, viewpoint_boundary geometry, viewpoint_area_sqm double precision, viewpoint_category_norm character varying, viewpoint_category_osm jsonb, viewpoint_country character varying, viewpoint_region character varying, viewpoint_admin_areas jsonb);


-- Table: viewpoint_entity
CREATE TABLE viewpoint_entity (viewpoint_id bigint NOT NULL, osm_type character varying NOT NULL, osm_id bigint NOT NULL, name_primary character varying NOT NULL, name_variants jsonb, category_osm jsonb, category_norm character varying, geom geometry, admin_area_ids jsonb, popularity double precision, created_at timestamp with time zone, updated_at timestamp with time zone);


-- Table: viewpoint_visual_tags
CREATE TABLE viewpoint_visual_tags (id bigint NOT NULL, viewpoint_id bigint NOT NULL, season character varying NOT NULL, tags jsonb NOT NULL, confidence double precision, evidence jsonb, tag_source character varying NOT NULL, updated_at timestamp with time zone, created_at timestamp with time zone);


-- Table: viewpoint_wiki
CREATE TABLE viewpoint_wiki (viewpoint_id bigint NOT NULL, wikipedia_title character varying NOT NULL, wikipedia_lang character varying NOT NULL, extract_text text, sections jsonb, citations jsonb, last_updated timestamp with time zone, created_at timestamp with time zone);


-- Table: viewpoint_wikidata
CREATE TABLE viewpoint_wikidata (viewpoint_id bigint NOT NULL, wikidata_qid character varying NOT NULL, claims jsonb, sitelinks_count integer, last_updated timestamp with time zone, created_at timestamp with time zone);

