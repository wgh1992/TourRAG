-- Migration: Add image storage and geolocation support to viewpoint_commons_assets
-- This migration extends the table to support storing raw images and geolocation information

-- Add columns for image storage and geolocation
ALTER TABLE viewpoint_commons_assets 
ADD COLUMN IF NOT EXISTS image_blob BYTEA,  -- Store raw image binary data
ADD COLUMN IF NOT EXISTS image_geometry GEOMETRY(Point, 4326),  -- Store image location (lat/lng from EXIF or Commons geotags)
ADD COLUMN IF NOT EXISTS image_exif JSONB,  -- Store EXIF metadata including GPS coordinates
ADD COLUMN IF NOT EXISTS image_width INTEGER,
ADD COLUMN IF NOT EXISTS image_height INTEGER,
ADD COLUMN IF NOT EXISTS image_format VARCHAR(20),
ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
ADD COLUMN IF NOT EXISTS downloaded_at TIMESTAMP WITH TIME ZONE;

-- Create index for spatial queries on image locations
CREATE INDEX IF NOT EXISTS idx_viewpoint_commons_image_geom 
ON viewpoint_commons_assets USING GIST(image_geometry);

-- Create index for EXIF metadata queries
CREATE INDEX IF NOT EXISTS idx_viewpoint_commons_exif 
ON viewpoint_commons_assets USING GIN(image_exif);

-- Create index for downloaded images
CREATE INDEX IF NOT EXISTS idx_viewpoint_commons_downloaded 
ON viewpoint_commons_assets(downloaded_at) WHERE downloaded_at IS NOT NULL;

-- Add comment to document the new columns
COMMENT ON COLUMN viewpoint_commons_assets.image_blob IS 'Raw image binary data stored in database';
COMMENT ON COLUMN viewpoint_commons_assets.image_geometry IS 'Image geolocation (Point geometry in WGS84) extracted from EXIF or Commons geotags';
COMMENT ON COLUMN viewpoint_commons_assets.image_exif IS 'EXIF metadata including GPS coordinates, camera info, timestamp, etc.';
COMMENT ON COLUMN viewpoint_commons_assets.image_width IS 'Image width in pixels';
COMMENT ON COLUMN viewpoint_commons_assets.image_height IS 'Image height in pixels';
COMMENT ON COLUMN viewpoint_commons_assets.image_format IS 'Image format (JPEG, PNG, etc.)';
COMMENT ON COLUMN viewpoint_commons_assets.file_size_bytes IS 'File size in bytes';
COMMENT ON COLUMN viewpoint_commons_assets.downloaded_at IS 'Timestamp when image was downloaded';

