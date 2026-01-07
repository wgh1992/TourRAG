#!/usr/bin/env python3
"""
Download images from Wikimedia Commons and store them in the database with geolocation information.

This script:
1. Fetches Commons assets metadata from the database
2. Downloads images from Wikimedia Commons
3. Extracts EXIF metadata including GPS coordinates
4. Stores images and geolocation in the database
"""
#!/usr/bin/env python3
import sys
import json
import hashlib
import time
import io
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import exifread
from psycopg2.extras import RealDictCursor
from psycopg2 import Binary

from app.services.database import db


def get_commons_image_url(file_id: str, size: str = "original") -> str:
    """
    Get the download URL for a Wikimedia Commons image.
    
    Args:
        file_id: Commons file ID (e.g., "File:Example.jpg")
        size: Image size ("original", "800px", "640px", etc.)
    
    Returns:
        Direct download URL
    """
    # Remove "File:" prefix if present
    filename = file_id.replace("File:", "").replace("file:", "")
    filename_encoded = quote(filename.replace(" ", "_"))
    
    if size == "original":
        # Direct URL to original image
        url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename_encoded}"
    else:
        # Thumbnail URL
        url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename_encoded}?width={size}"
    
    return url


def download_image(url: str, timeout: int = 30) -> Optional[bytes]:
    """
    Download an image from a URL.
    
    Args:
        url: Image URL
        timeout: Request timeout in seconds
    
    Returns:
        Image binary data or None if download fails
    """
    try:
        headers = {
            "User-Agent": "TourRAG/1.0 (https://github.com/your-repo/tourrag; contact@example.com)"
        }
        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"Error downloading image from {url}: {e}")
        return None


def extract_exif_metadata(image_data: bytes) -> Dict[str, Any]:
    """
    Extract EXIF metadata from image data, including GPS coordinates.
    
    Args:
        image_data: Image binary data
    
    Returns:
        Dictionary with EXIF metadata including GPS coordinates
    """
    exif_data = {}
    gps_data = {}
    
    try:
        # Method 1: Using exifread (more reliable for GPS)
        tags = exifread.process_file(io.BytesIO(image_data), details=False)
        
        for tag in tags.keys():
            if tag.startswith('GPS'):
                gps_data[tag] = str(tags[tag])
            else:
                exif_data[tag] = str(tags[tag])
        
        # Extract GPS coordinates if available
        if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
            lat_ref = str(tags.get('GPS GPSLatitudeRef', 'N'))
            lon_ref = str(tags.get('GPS GPSLongitudeRef', 'E'))
            
            lat = _convert_to_degrees(tags['GPS GPSLatitude'].values)
            lon = _convert_to_degrees(tags['GPS GPSLongitude'].values)
            
            if lat_ref == 'S':
                lat = -lat
            if lon_ref == 'W':
                lon = -lon
            
            gps_data['latitude'] = lat
            gps_data['longitude'] = lon
            gps_data['coordinates'] = [lon, lat]  # GeoJSON format [lng, lat]
        
        # Extract image dimensions
        img = Image.open(io.BytesIO(image_data))
        exif_data['width'] = img.width
        exif_data['height'] = img.height
        exif_data['format'] = img.format
        
        # Extract timestamp if available
        if 'EXIF DateTimeOriginal' in tags:
            exif_data['datetime_original'] = str(tags['EXIF DateTimeOriginal'])
        elif 'Image DateTime' in tags:
            exif_data['datetime'] = str(tags['Image DateTime'])
        
    except Exception as e:
        print(f"Error extracting EXIF metadata: {e}")
        # Fallback: try to get at least image dimensions
        try:
            img = Image.open(io.BytesIO(image_data))
            exif_data['width'] = img.width
            exif_data['height'] = img.height
            exif_data['format'] = img.format
        except:
            pass
    
    return {
        'exif': exif_data,
        'gps': gps_data
    }


def _convert_to_degrees(value) -> float:
    """
    Convert GPS coordinate from EXIF format (degrees, minutes, seconds) to decimal degrees.
    
    Args:
        value: EXIF GPS coordinate value (e.g., [35, 21, 30.5])
    
    Returns:
        Decimal degrees
    """
    d = float(value[0])
    m = float(value[1])
    s = float(value[2])
    return d + (m / 60.0) + (s / 3600.0)


def get_commons_geotag(file_id: str) -> Optional[Tuple[float, float]]:
    """
    Get geolocation from Wikimedia Commons API if EXIF doesn't have GPS data.
    
    Args:
        file_id: Commons file ID
    
    Returns:
        Tuple of (latitude, longitude) or None
    """
    try:
        # Remove "File:" prefix
        filename = file_id.replace("File:", "").replace("file:", "")
        
        # Commons API endpoint
        api_url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "extmetadata",
            "format": "json"
        }
        
        response = requests.get(api_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        pages = data.get('query', {}).get('pages', {})
        for page_id, page_data in pages.items():
            imageinfo = page_data.get('imageinfo', [])
            if imageinfo:
                extmetadata = imageinfo[0].get('extmetadata', {})
                
                # Check for GPS coordinates in metadata
                if 'GPSLatitude' in extmetadata and 'GPSLongitude' in extmetadata:
                    lat = float(extmetadata['GPSLatitude']['value'])
                    lon = float(extmetadata['GPSLongitude']['value'])
                    return (lat, lon)
        
        return None
    except Exception as e:
        print(f"Error fetching geotag from Commons API for {file_id}: {e}")
        return None


def calculate_image_hash(image_data: bytes) -> str:
    """Calculate SHA256 hash of image data."""
    return hashlib.sha256(image_data).hexdigest()


def update_commons_asset_with_image(
    asset_id: int,
    image_data: bytes,
    exif_metadata: Dict[str, Any],
    latitude: Optional[float] = None,
    longitude: Optional[float] = None
) -> bool:
    """
    Update a Commons asset record with downloaded image and metadata.
    
    Args:
        asset_id: Database ID of the Commons asset
        image_data: Image binary data
        exif_metadata: EXIF metadata dictionary
        latitude: Latitude from GPS or Commons geotag
        longitude: Longitude from GPS or Commons geotag
    
    Returns:
        True if update successful, False otherwise
    """
    try:
        # Prepare image geometry if coordinates are available
        image_geometry = None
        if latitude is not None and longitude is not None:
            # Create PostGIS Point geometry (lng, lat for GeoJSON/WGS84)
            image_geometry = f"POINT({longitude} {latitude})"
        
        # Extract image dimensions and format
        width = exif_metadata.get('exif', {}).get('width')
        height = exif_metadata.get('exif', {}).get('height')
        image_format = exif_metadata.get('exif', {}).get('format', 'JPEG')
        
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE viewpoint_commons_assets
                    SET 
                        image_blob = %s,
                        image_geometry = ST_GeomFromText(%s, 4326),
                        image_exif = %s,
                        image_width = %s,
                        image_height = %s,
                        image_format = %s,
                        file_size_bytes = %s,
                        downloaded_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    Binary(image_data),
                    image_geometry,
                    json.dumps(exif_metadata),
                    width,
                    height,
                    image_format,
                    len(image_data),
                    asset_id
                ))
                conn.commit()
                return True
    except Exception as e:
        print(f"Error updating asset {asset_id} with image: {e}")
        return False


def main():
    """Main function to download and store Commons images."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Download images from Wikimedia Commons')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of images to download')
    parser.add_argument('--viewpoint-id', type=int, default=None, help='Only download images for specific viewpoint')
    parser.add_argument('--skip-downloaded', action='store_true', help='Skip images that are already downloaded')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of images to process in each batch')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Wikimedia Commons Image Download Script")
    print("=" * 60)
    
    # Fetch Commons assets that need images downloaded
    with db.get_cursor() as cursor:
        query = """
            SELECT 
                id,
                viewpoint_id,
                commons_file_id,
                hash
            FROM viewpoint_commons_assets
            WHERE 1=1
        """
        params = []
        
        if args.viewpoint_id:
            query += " AND viewpoint_id = %s"
            params.append(args.viewpoint_id)
        
        if args.skip_downloaded:
            query += " AND downloaded_at IS NULL"
        
        query += " ORDER BY viewpoint_id, id"
        
        if args.limit:
            query += " LIMIT %s"
            params.append(args.limit)
        
        cursor.execute(query, params)
        assets = cursor.fetchall()
    
    print(f"\nFound {len(assets)} Commons assets to process")
    
    if not assets:
        print("No assets to process. Exiting.")
        return
    
    downloaded = 0
    failed = 0
    start_time = time.time()
    
    for i, asset in enumerate(assets):
        asset_id = asset['id']
        file_id = asset['commons_file_id']
        viewpoint_id = asset['viewpoint_id']
        
        print(f"\n[{i+1}/{len(assets)}] Processing: {file_id} (Viewpoint ID: {viewpoint_id})")
        
        # Get image URL
        image_url = get_commons_image_url(file_id)
        print(f"  Downloading from: {image_url}")
        
        # Download image
        image_data = download_image(image_url)
        if not image_data:
            print(f"  ❌ Failed to download image")
            failed += 1
            continue
        
        print(f"  ✓ Downloaded {len(image_data)} bytes")
        
        # Extract EXIF metadata
        exif_metadata = extract_exif_metadata(image_data)
        gps_data = exif_metadata.get('gps', {})
        
        # Get coordinates from EXIF GPS or Commons API
        latitude = gps_data.get('latitude')
        longitude = gps_data.get('longitude')
        
        if latitude is None or longitude is None:
            print(f"  No GPS in EXIF, checking Commons API...")
            coords = get_commons_geotag(file_id)
            if coords:
                latitude, longitude = coords
                print(f"  ✓ Found coordinates from Commons: ({latitude}, {longitude})")
            else:
                print(f"  ⚠ No geolocation found")
        else:
            print(f"  ✓ Found GPS coordinates: ({latitude}, {longitude})")
        
        # Update database
        success = update_commons_asset_with_image(
            asset_id,
            image_data,
            exif_metadata,
            latitude,
            longitude
        )
        
        if success:
            print(f"  ✓ Stored image and metadata in database")
            downloaded += 1
        else:
            print(f"  ❌ Failed to store in database")
            failed += 1
        
        # Rate limiting - be respectful to Commons servers
        if (i + 1) % args.batch_size == 0:
            print(f"\n  [Batch complete] Processed {i+1}/{len(assets)}")
            time.sleep(1)  # Brief pause between batches
    
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 60)
    print("Download Summary")
    print("=" * 60)
    print(f"Total assets processed: {len(assets)}")
    print(f"Successfully downloaded: {downloaded}")
    print(f"Failed: {failed}")
    print(f"Time elapsed: {elapsed:.1f}s")
    print(f"Average time per image: {elapsed/len(assets):.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()

