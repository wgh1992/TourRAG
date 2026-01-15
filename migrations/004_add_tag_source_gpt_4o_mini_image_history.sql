-- Add gpt_4o_mini_image_history to tag_source check constraint
DO $$
DECLARE
    def text;
    new_def text;
    constraint_name text := 'viewpoint_visual_tags_tag_source_check';
BEGIN
    SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
    JOIN pg_class t ON c.conrelid = t.oid
    WHERE t.relname = 'viewpoint_visual_tags'
      AND c.conname = constraint_name;

    IF def IS NULL THEN
        RAISE NOTICE 'Constraint % not found; skipping', constraint_name;
        RETURN;
    END IF;

    IF def LIKE '%gpt_4o_mini_image_history%' THEN
        RAISE NOTICE 'Constraint already includes gpt_4o_mini_image_history';
        RETURN;
    END IF;

    new_def := regexp_replace(
        def,
        'ARRAY\[(.*)\]\)\)',
        'ARRAY[\1, ''gpt_4o_mini_image_history''::text]))',
        1, 1, 'n'
    );

    IF new_def = def THEN
        RAISE EXCEPTION 'Failed to update constraint definition: %', def;
    END IF;

    EXECUTE format('ALTER TABLE viewpoint_visual_tags DROP CONSTRAINT %I', constraint_name);
    EXECUTE format('ALTER TABLE viewpoint_visual_tags ADD CONSTRAINT %I %s', constraint_name, new_def);
END $$;
