#!/bin/bash
# Example script for downloading Commons images

echo "=== TourRAG Image Download Example ==="

# Step 1: Run database migration (if not already done)
echo "Step 1: Running database migration..."
psql -d tourrag_db -f migrations/002_add_image_storage.sql

# Step 2: Download images (limit to 10 for testing)
echo "Step 2: Downloading first 10 images..."
python scripts/download_commons_images.py --limit 10 --skip-downloaded

# Step 3: Check downloaded images
echo "Step 3: Checking downloaded images..."
psql -d tourrag_db -c "
SELECT 
    COUNT(*) as total_assets,
    COUNT(image_blob) as images_downloaded,
    COUNT(image_geometry) as images_with_location
FROM viewpoint_commons_assets;
"

echo "=== Done ==="

