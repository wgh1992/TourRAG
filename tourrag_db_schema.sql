--
-- PostgreSQL database dump
--

-- Dumped from database version 17.5 (Homebrew)
-- Dumped by pg_dump version 17.5 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: name_similarity_score(text, text, jsonb); Type: FUNCTION; Schema: public; Owner: z3548881
--

CREATE FUNCTION public.name_similarity_score(query_text text, entity_name text, variants jsonb) RETURNS double precision
    LANGUAGE plpgsql IMMUTABLE
    AS $$
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
$$;


ALTER FUNCTION public.name_similarity_score(query_text text, entity_name text, variants jsonb) OWNER TO z3548881;

--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: z3548881
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_updated_at_column() OWNER TO z3548881;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: query_log; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.query_log (
    id bigint NOT NULL,
    user_text text,
    user_images jsonb DEFAULT '[]'::jsonb,
    query_intent jsonb NOT NULL,
    sql_queries jsonb DEFAULT '[]'::jsonb,
    tool_calls jsonb DEFAULT '[]'::jsonb,
    results jsonb,
    execution_time_ms integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.query_log OWNER TO z3548881;

--
-- Name: query_log_id_seq; Type: SEQUENCE; Schema: public; Owner: z3548881
--

CREATE SEQUENCE public.query_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.query_log_id_seq OWNER TO z3548881;

--
-- Name: query_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: z3548881
--

ALTER SEQUENCE public.query_log_id_seq OWNED BY public.query_log.id;


--
-- Name: tag_schema_version; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.tag_schema_version (
    version character varying(50) NOT NULL,
    schema_definition jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.tag_schema_version OWNER TO z3548881;

--
-- Name: viewpoint_commons_assets; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.viewpoint_commons_assets (
    id bigint NOT NULL,
    viewpoint_id bigint NOT NULL,
    commons_file_id character varying(500) NOT NULL,
    commons_page character varying(500),
    caption text,
    categories jsonb DEFAULT '[]'::jsonb,
    depicts_wikidata jsonb DEFAULT '[]'::jsonb,
    "timestamp" timestamp with time zone,
    hash character varying(64),
    license character varying(100),
    local_path_or_blob_ref character varying(1000),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.viewpoint_commons_assets OWNER TO z3548881;

--
-- Name: viewpoint_commons_assets_id_seq; Type: SEQUENCE; Schema: public; Owner: z3548881
--

CREATE SEQUENCE public.viewpoint_commons_assets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.viewpoint_commons_assets_id_seq OWNER TO z3548881;

--
-- Name: viewpoint_commons_assets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: z3548881
--

ALTER SEQUENCE public.viewpoint_commons_assets_id_seq OWNED BY public.viewpoint_commons_assets.id;


--
-- Name: viewpoint_entity; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.viewpoint_entity (
    viewpoint_id bigint NOT NULL,
    osm_type character varying(20) NOT NULL,
    osm_id bigint NOT NULL,
    name_primary character varying(500) NOT NULL,
    name_variants jsonb DEFAULT '{}'::jsonb,
    category_osm jsonb DEFAULT '{}'::jsonb,
    category_norm character varying(100),
    geom public.geometry(Geometry,4326),
    admin_area_ids jsonb DEFAULT '[]'::jsonb,
    popularity double precision DEFAULT 0.0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT viewpoint_entity_osm_type_check CHECK (((osm_type)::text = ANY ((ARRAY['node'::character varying, 'way'::character varying, 'relation'::character varying])::text[])))
);


ALTER TABLE public.viewpoint_entity OWNER TO z3548881;

--
-- Name: viewpoint_entity_viewpoint_id_seq; Type: SEQUENCE; Schema: public; Owner: z3548881
--

CREATE SEQUENCE public.viewpoint_entity_viewpoint_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.viewpoint_entity_viewpoint_id_seq OWNER TO z3548881;

--
-- Name: viewpoint_entity_viewpoint_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: z3548881
--

ALTER SEQUENCE public.viewpoint_entity_viewpoint_id_seq OWNED BY public.viewpoint_entity.viewpoint_id;


--
-- Name: viewpoint_visual_tags; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.viewpoint_visual_tags (
    id bigint NOT NULL,
    viewpoint_id bigint NOT NULL,
    season character varying(20) NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    confidence double precision DEFAULT 0.0,
    evidence jsonb DEFAULT '{}'::jsonb,
    tag_source character varying(50) NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT viewpoint_visual_tags_confidence_check CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision))),
    CONSTRAINT viewpoint_visual_tags_season_check CHECK (((season)::text = ANY ((ARRAY['spring'::character varying, 'summer'::character varying, 'autumn'::character varying, 'winter'::character varying, 'unknown'::character varying])::text[]))),
    CONSTRAINT viewpoint_visual_tags_tag_source_check CHECK (((tag_source)::text = ANY ((ARRAY['commons_vision'::character varying, 'wiki_weak_supervision'::character varying, 'user_image'::character varying, 'manual'::character varying])::text[])))
);


ALTER TABLE public.viewpoint_visual_tags OWNER TO z3548881;

--
-- Name: viewpoint_visual_tags_id_seq; Type: SEQUENCE; Schema: public; Owner: z3548881
--

CREATE SEQUENCE public.viewpoint_visual_tags_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.viewpoint_visual_tags_id_seq OWNER TO z3548881;

--
-- Name: viewpoint_visual_tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: z3548881
--

ALTER SEQUENCE public.viewpoint_visual_tags_id_seq OWNED BY public.viewpoint_visual_tags.id;


--
-- Name: viewpoint_wiki; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.viewpoint_wiki (
    viewpoint_id bigint NOT NULL,
    wikipedia_title character varying(500) NOT NULL,
    wikipedia_lang character varying(10) DEFAULT 'en'::character varying NOT NULL,
    extract_text text,
    sections jsonb DEFAULT '[]'::jsonb,
    citations jsonb DEFAULT '[]'::jsonb,
    last_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.viewpoint_wiki OWNER TO z3548881;

--
-- Name: viewpoint_wikidata; Type: TABLE; Schema: public; Owner: z3548881
--

CREATE TABLE public.viewpoint_wikidata (
    viewpoint_id bigint NOT NULL,
    wikidata_qid character varying(20) NOT NULL,
    claims jsonb DEFAULT '{}'::jsonb,
    sitelinks_count integer DEFAULT 0,
    last_updated timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.viewpoint_wikidata OWNER TO z3548881;

--
-- Name: query_log id; Type: DEFAULT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.query_log ALTER COLUMN id SET DEFAULT nextval('public.query_log_id_seq'::regclass);


--
-- Name: viewpoint_commons_assets id; Type: DEFAULT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_commons_assets ALTER COLUMN id SET DEFAULT nextval('public.viewpoint_commons_assets_id_seq'::regclass);


--
-- Name: viewpoint_entity viewpoint_id; Type: DEFAULT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_entity ALTER COLUMN viewpoint_id SET DEFAULT nextval('public.viewpoint_entity_viewpoint_id_seq'::regclass);


--
-- Name: viewpoint_visual_tags id; Type: DEFAULT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_visual_tags ALTER COLUMN id SET DEFAULT nextval('public.viewpoint_visual_tags_id_seq'::regclass);


--
-- Name: query_log query_log_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.query_log
    ADD CONSTRAINT query_log_pkey PRIMARY KEY (id);


--
-- Name: tag_schema_version tag_schema_version_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.tag_schema_version
    ADD CONSTRAINT tag_schema_version_pkey PRIMARY KEY (version);


--
-- Name: viewpoint_commons_assets viewpoint_commons_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_commons_assets
    ADD CONSTRAINT viewpoint_commons_assets_pkey PRIMARY KEY (id);


--
-- Name: viewpoint_commons_assets viewpoint_commons_assets_viewpoint_id_commons_file_id_key; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_commons_assets
    ADD CONSTRAINT viewpoint_commons_assets_viewpoint_id_commons_file_id_key UNIQUE (viewpoint_id, commons_file_id);


--
-- Name: viewpoint_entity viewpoint_entity_osm_type_osm_id_key; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_entity
    ADD CONSTRAINT viewpoint_entity_osm_type_osm_id_key UNIQUE (osm_type, osm_id);


--
-- Name: viewpoint_entity viewpoint_entity_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_entity
    ADD CONSTRAINT viewpoint_entity_pkey PRIMARY KEY (viewpoint_id);


--
-- Name: viewpoint_visual_tags viewpoint_visual_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_visual_tags
    ADD CONSTRAINT viewpoint_visual_tags_pkey PRIMARY KEY (id);


--
-- Name: viewpoint_visual_tags viewpoint_visual_tags_viewpoint_id_season_tag_source_key; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_visual_tags
    ADD CONSTRAINT viewpoint_visual_tags_viewpoint_id_season_tag_source_key UNIQUE (viewpoint_id, season, tag_source);


--
-- Name: viewpoint_wiki viewpoint_wiki_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_wiki
    ADD CONSTRAINT viewpoint_wiki_pkey PRIMARY KEY (viewpoint_id);


--
-- Name: viewpoint_wikidata viewpoint_wikidata_pkey; Type: CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_wikidata
    ADD CONSTRAINT viewpoint_wikidata_pkey PRIMARY KEY (viewpoint_id);


--
-- Name: idx_query_log_created_at; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_query_log_created_at ON public.query_log USING btree (created_at DESC);


--
-- Name: idx_viewpoint_commons_categories; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_commons_categories ON public.viewpoint_commons_assets USING gin (categories);


--
-- Name: idx_viewpoint_commons_file_id; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_commons_file_id ON public.viewpoint_commons_assets USING btree (commons_file_id);


--
-- Name: idx_viewpoint_commons_hash; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_commons_hash ON public.viewpoint_commons_assets USING btree (hash);


--
-- Name: idx_viewpoint_commons_viewpoint; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_commons_viewpoint ON public.viewpoint_commons_assets USING btree (viewpoint_id);


--
-- Name: idx_viewpoint_entity_category_norm; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_entity_category_norm ON public.viewpoint_entity USING btree (category_norm);


--
-- Name: idx_viewpoint_entity_geom; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_entity_geom ON public.viewpoint_entity USING gist (geom);


--
-- Name: idx_viewpoint_entity_name_primary; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_entity_name_primary ON public.viewpoint_entity USING gin (name_primary public.gin_trgm_ops);


--
-- Name: idx_viewpoint_entity_name_variants; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_entity_name_variants ON public.viewpoint_entity USING gin (name_variants);


--
-- Name: idx_viewpoint_entity_popularity; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_entity_popularity ON public.viewpoint_entity USING btree (popularity DESC);


--
-- Name: idx_viewpoint_visual_tags_season; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_visual_tags_season ON public.viewpoint_visual_tags USING btree (season);


--
-- Name: idx_viewpoint_visual_tags_source; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_visual_tags_source ON public.viewpoint_visual_tags USING btree (tag_source);


--
-- Name: idx_viewpoint_visual_tags_tags; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_visual_tags_tags ON public.viewpoint_visual_tags USING gin (tags);


--
-- Name: idx_viewpoint_visual_tags_viewpoint; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_visual_tags_viewpoint ON public.viewpoint_visual_tags USING btree (viewpoint_id);


--
-- Name: idx_viewpoint_wiki_lang; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_wiki_lang ON public.viewpoint_wiki USING btree (wikipedia_lang);


--
-- Name: idx_viewpoint_wiki_title; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_wiki_title ON public.viewpoint_wiki USING btree (wikipedia_title);


--
-- Name: idx_viewpoint_wikidata_qid; Type: INDEX; Schema: public; Owner: z3548881
--

CREATE INDEX idx_viewpoint_wikidata_qid ON public.viewpoint_wikidata USING btree (wikidata_qid);


--
-- Name: viewpoint_entity update_viewpoint_entity_updated_at; Type: TRIGGER; Schema: public; Owner: z3548881
--

CREATE TRIGGER update_viewpoint_entity_updated_at BEFORE UPDATE ON public.viewpoint_entity FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: viewpoint_visual_tags update_viewpoint_visual_tags_updated_at; Type: TRIGGER; Schema: public; Owner: z3548881
--

CREATE TRIGGER update_viewpoint_visual_tags_updated_at BEFORE UPDATE ON public.viewpoint_visual_tags FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: viewpoint_commons_assets viewpoint_commons_assets_viewpoint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_commons_assets
    ADD CONSTRAINT viewpoint_commons_assets_viewpoint_id_fkey FOREIGN KEY (viewpoint_id) REFERENCES public.viewpoint_entity(viewpoint_id) ON DELETE CASCADE;


--
-- Name: viewpoint_visual_tags viewpoint_visual_tags_viewpoint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_visual_tags
    ADD CONSTRAINT viewpoint_visual_tags_viewpoint_id_fkey FOREIGN KEY (viewpoint_id) REFERENCES public.viewpoint_entity(viewpoint_id) ON DELETE CASCADE;


--
-- Name: viewpoint_wiki viewpoint_wiki_viewpoint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_wiki
    ADD CONSTRAINT viewpoint_wiki_viewpoint_id_fkey FOREIGN KEY (viewpoint_id) REFERENCES public.viewpoint_entity(viewpoint_id) ON DELETE CASCADE;


--
-- Name: viewpoint_wikidata viewpoint_wikidata_viewpoint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: z3548881
--

ALTER TABLE ONLY public.viewpoint_wikidata
    ADD CONSTRAINT viewpoint_wikidata_viewpoint_id_fkey FOREIGN KEY (viewpoint_id) REFERENCES public.viewpoint_entity(viewpoint_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

