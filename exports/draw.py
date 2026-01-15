"""
Generate TourRAG System Architecture Diagram and World Map

Creates:
1. Visual diagram showing the system framework for the methodology section
2. World map showing geographic distribution of viewpoints from database
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle
import matplotlib.patches as mpatches
import numpy as np

# Database imports
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    print("Warning: psycopg2 not installed. Database features will be unavailable.")

# Geospatial imports
try:
    import geopandas as gpd
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False
    gpd = None
    print("Warning: geopandas not installed. World map features will be limited.")

from app.config import settings

def setup_chinese_font():
    """Setup Chinese font for matplotlib"""
    import platform
    import matplotlib.font_manager as fm
    
    system = platform.system()
    chinese_fonts = []
    
    if system == 'Darwin':  # macOS
        chinese_fonts = ['PingFang SC', 'STHeiti', 'Arial Unicode MS', 'Heiti SC']
    elif system == 'Windows':
        chinese_fonts = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi']
    elif system == 'Linux':
        chinese_fonts = ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC']
    
    for font_name in chinese_fonts:
        try:
            font_path = fm.findfont(fm.FontProperties(family=font_name))
            if font_path:
                plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
                plt.rcParams['axes.unicode_minus'] = False
                return True
        except:
            continue
    
    print("Warning: No Chinese font found. Using English labels.")
    return False


def create_system_architecture_diagram(output_path: str = 'tourrag_architecture.png'):
    """
    Create TourRAG system architecture diagram
    """
    has_chinese_font = setup_chinese_font()
    
    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(14, 10))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')
    
    # Define colors
    color_input = '#E3F2FD'  # Light blue
    color_extract = '#FFF3E0'  # Light orange
    color_retrieval = '#E8F5E9'  # Light green
    color_enrichment = '#F3E5F5'  # Light purple
    color_llm = '#FFEBEE'  # Light red
    color_output = '#E0F2F1'  # Light teal
    color_border = '#424242'  # Dark gray
    
    # Define box styles
    box_style = dict(boxstyle="round,pad=0.5", facecolor='white', edgecolor=color_border, linewidth=2)
    input_style = dict(boxstyle="round,pad=0.6", facecolor=color_input, edgecolor=color_border, linewidth=2)
    process_style = dict(boxstyle="round,pad=0.5", facecolor='white', edgecolor=color_border, linewidth=1.5)
    
    # Layer 1: User Input (top)
    input_y = 9
    ax.text(5, input_y + 0.3, 'User Input', ha='center', va='bottom', fontsize=16, fontweight='bold')
    
    # Input boxes
    text_input = FancyBboxPatch((2, input_y - 0.4), 1.5, 0.6, **input_style)
    ax.add_patch(text_input)
    ax.text(2.75, input_y - 0.1, 'Text Query', ha='center', va='center', fontsize=11)
    
    image_input = FancyBboxPatch((6.5, input_y - 0.4), 1.5, 0.6, **input_style)
    ax.add_patch(image_input)
    ax.text(7.25, input_y - 0.1, 'Image', ha='center', va='center', fontsize=11)
    
    # Layer 2: Query Intent Extraction
    extract_y = 7.5
    extract_box = FancyBboxPatch((3.5, extract_y - 0.5), 3, 0.8, **process_style)
    extract_box.set_facecolor(color_extract)
    ax.add_patch(extract_box)
    ax.text(5, extract_y, 'Query Intent Extraction\n(MCP Tool)', ha='center', va='center', 
            fontsize=12, fontweight='bold')
    ax.text(5, extract_y - 0.35, 'name_candidates, query_tags, season_hint, geo_hints', 
            ha='center', va='center', fontsize=9, style='italic')
    
    # Arrows from input to extraction
    arrow1 = FancyArrowPatch((2.75, input_y - 0.4), (4.5, extract_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow1)
    arrow2 = FancyArrowPatch((7.25, input_y - 0.4), (5.5, extract_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow2)
    
    # Layer 3: In-DB Retrieval
    retrieval_y = 5.8
    retrieval_box = FancyBboxPatch((1, retrieval_y - 0.5), 2.5, 0.8, **process_style)
    retrieval_box.set_facecolor(color_retrieval)
    ax.add_patch(retrieval_box)
    ax.text(2.25, retrieval_y, 'In-DB Retrieval', ha='center', va='center', 
            fontsize=12, fontweight='bold')
    ax.text(2.25, retrieval_y - 0.35, 'SQL Queries\nPostgreSQL', 
            ha='center', va='center', fontsize=9, style='italic')
    
    # Arrow from extraction to retrieval
    arrow3 = FancyArrowPatch((4.5, extract_y - 0.5), (3, retrieval_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow3)
    
    # Layer 3: External Enrichment (parallel to retrieval)
    enrichment_y = 5.8
    enrichment_box = FancyBboxPatch((6.5, enrichment_y - 0.5), 2.5, 0.8, **process_style)
    enrichment_box.set_facecolor(color_enrichment)
    ax.add_patch(enrichment_box)
    ax.text(7.75, enrichment_y, 'External Enrichment', ha='center', va='center', 
            fontsize=12, fontweight='bold')
    ax.text(7.75, enrichment_y - 0.35, 'Wikipedia\nWikidata\nCommons', 
            ha='center', va='center', fontsize=9, style='italic')
    
    # Arrow from extraction to enrichment
    arrow4 = FancyArrowPatch((5.5, extract_y - 0.5), (7, enrichment_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow4)
    
    # Layer 4: LLM Fusion & Ranking
    llm_y = 4
    llm_box = FancyBboxPatch((3.5, llm_y - 0.5), 3, 0.8, **process_style)
    llm_box.set_facecolor(color_llm)
    ax.add_patch(llm_box)
    ax.text(5, llm_y, 'LLM Fusion & Ranking', ha='center', va='center', 
            fontsize=12, fontweight='bold')
    ax.text(5, llm_y - 0.35, 'Tag overlap, Season matching, Confidence scoring', 
            ha='center', va='center', fontsize=9, style='italic')
    
    # Arrows from retrieval and enrichment to LLM
    arrow5 = FancyArrowPatch((2.25, retrieval_y - 0.5), (4.5, llm_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow5)
    arrow6 = FancyArrowPatch((7.75, enrichment_y - 0.5), (5.5, llm_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow6)
    
    # Layer 5: Output
    output_y = 2.2
    output_box = FancyBboxPatch((3.5, output_y - 0.5), 3, 0.8, **process_style)
    output_box.set_facecolor(color_output)
    ax.add_patch(output_box)
    ax.text(5, output_y, 'Final Results', ha='center', va='center', 
            fontsize=12, fontweight='bold')
    ax.text(5, output_y - 0.35, 'Top-K Viewpoints\nwith Evidence & Confidence', 
            ha='center', va='center', fontsize=9, style='italic')
    
    # Arrow from LLM to output
    arrow7 = FancyArrowPatch((5, llm_y - 0.5), (5, output_y + 0.3), 
                            arrowstyle='->', mutation_scale=20, color='black', linewidth=1.5)
    ax.add_patch(arrow7)
    
    # Add database icon/box on the side
    db_box = FancyBboxPatch((0.2, retrieval_y - 0.3), 0.6, 0.6, 
                           boxstyle="round,pad=0.1", facecolor='#BBDEFB', 
                           edgecolor=color_border, linewidth=1.5)
    ax.add_patch(db_box)
    ax.text(0.5, retrieval_y, 'DB', ha='center', va='center', fontsize=10, fontweight='bold')
    
    # Add connection line from DB to retrieval
    db_line = FancyArrowPatch((0.8, retrieval_y), (1, retrieval_y), 
                             arrowstyle='->', mutation_scale=15, color='gray', linewidth=1)
    ax.add_patch(db_line)
    
    # Add title
    ax.text(5, 9.8, 'TourRAG System Architecture', ha='center', va='top', 
            fontsize=18, fontweight='bold')
    
    # Add legend/notes at bottom
    notes_y = 0.5
    ax.text(5, notes_y, 
            'All data sources are pre-fetched and stored locally | Tag-driven retrieval | Full explainability', 
            ha='center', va='center', fontsize=9, style='italic', 
            bbox=dict(boxstyle="round,pad=0.3", facecolor='#FAFAFA', edgecolor='gray', alpha=0.5))
    
    # Save figure
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Architecture diagram saved to: {output_file.absolute()}")
    plt.close()


def get_viewpoints_from_database(limit: int = None):
    """
    Query database to get all viewpoints with geographic coordinates
    
    Returns:
        List of dicts with keys: viewpoint_id, name_primary, longitude, latitude
    """
    if not HAS_PSYCOPG2:
        print("Error: psycopg2 not installed. Cannot query database.")
        return []
    
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
        SELECT 
            viewpoint_id,
            name_primary,
            ST_X(geom::geometry) as longitude,
            ST_Y(geom::geometry) as latitude,
            category_norm,
            popularity
        FROM viewpoint_entity
        WHERE geom IS NOT NULL
        ORDER BY viewpoint_id
        """
        
        params = []
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error querying database: {e}")
        return []


def get_world_map_data():
    """
    Get world map data from Natural Earth or use a simple approach
    """
    if not HAS_GEOPANDAS:
        print("Note: geopandas not installed. World map will not be generated.")
        print("Install with: pip install geopandas")
        return None
    
    try:
        # Try to use Natural Earth data via geopandas
        # Method 1: Try new geopandas.datasets API (geopandas >= 0.13)
        try:
            import geopandas.datasets
            path = geopandas.datasets.get_path('naturalearth_lowres')
            world = gpd.read_file(path)
            print("Successfully loaded Natural Earth data via geopandas.datasets")
            return world
        except Exception as e1:
            print(f"Method 1 failed: {e1}")
            # Method 2: Try deprecated gpd.datasets API
            try:
                path = gpd.datasets.get_path('naturalearth_lowres')
                world = gpd.read_file(path)
                print("Successfully loaded Natural Earth data via gpd.datasets")
                return world
            except Exception as e2:
                print(f"Method 2 failed: {e2}")
                # Method 3: Try to download Natural Earth data manually
                try:
                    import urllib.request
                    import tempfile
                    import zipfile
                    import os
                    
                    # Try to download Natural Earth 110m countries data
                    # Use the direct download link from Natural Earth
                    ne_url = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
                    
                    # Check if we have a cached version
                    cache_dir = Path.home() / '.local' / 'share' / 'geopandas'
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cached_shp = cache_dir / 'ne_110m_admin_0_countries.shp'
                    
                    if cached_shp.exists():
                        print(f"Using cached Natural Earth data from {cached_shp}")
                        world = gpd.read_file(str(cached_shp))
                        return world
                    
                    # Download to temp directory
                    print("Downloading Natural Earth data from Natural Earth CDN...")
                    with tempfile.TemporaryDirectory() as tmpdir:
                        zip_path = Path(tmpdir) / "ne_countries.zip"
                        try:
                            # Create a request with proper headers
                            req = urllib.request.Request(ne_url)
                            req.add_header('User-Agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
                            with urllib.request.urlopen(req) as response:
                                with open(zip_path, 'wb') as out_file:
                                    out_file.write(response.read())
                            
                            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                zip_ref.extractall(tmpdir)
                            
                            shp_path = Path(tmpdir) / "ne_110m_admin_0_countries.shp"
                            if shp_path.exists():
                                # Cache it for future use
                                import shutil
                                for ext in ['.shp', '.shx', '.dbf', '.prj']:
                                    src = Path(tmpdir) / f"ne_110m_admin_0_countries{ext}"
                                    if src.exists():
                                        dst = cache_dir / f"ne_110m_admin_0_countries{ext}"
                                        shutil.copy2(src, dst)
                                
                                world = gpd.read_file(str(shp_path))
                                print("Successfully downloaded and loaded Natural Earth data")
                                return world
                        except Exception as download_error:
                            print(f"Could not download Natural Earth data: {download_error}")
                            return None
                except Exception as e3:
                    print(f"Error in download attempt: {e3}")
                    return None
                            
    except Exception as e:
        print(f"Could not load Natural Earth data: {e}")
        print("Note: World map visualization requires geopandas with Natural Earth data.")
        print("      Falling back to scatter plot without map background.")
        return None


def create_world_map_from_database(output_path: str = 'viewpoint_world_map.png', limit: int = None):
    """
    Create world map showing geographic distribution of viewpoints from database
    
    Args:
        output_path: Output file path
        limit: Optional limit on number of viewpoints to plot (for performance)
    """
    has_chinese_font = setup_chinese_font()
    
    # Get viewpoints from database
    print("Querying database for viewpoint coordinates...")
    viewpoints = get_viewpoints_from_database(limit=limit)
    
    if not viewpoints:
        print("No viewpoints found in database or database connection failed.")
        return
    
    print(f"Found {len(viewpoints)} viewpoints with coordinates")
    
    # Extract coordinates
    lons = [v['longitude'] for v in viewpoints]
    lats = [v['latitude'] for v in viewpoints]
    
    # Get world map
    world = get_world_map_data()
    
    # Try to use cartopy for better world map visualization
    use_cartopy = False
    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        use_cartopy = True
    except ImportError:
        pass
    
    # Create figure
    if use_cartopy:
        fig = plt.figure(figsize=(16, 10))
        ax = plt.axes(projection=ccrs.PlateCarree())
        
        # Add map features
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5, color='gray')
        ax.add_feature(cfeature.BORDERS, linewidth=0.3, color='gray')
        ax.add_feature(cfeature.LAND, facecolor='#F0F0F0', alpha=0.5)
        ax.add_feature(cfeature.OCEAN, facecolor='#E3F2FD', alpha=0.5)
        
        # Set global extent
        ax.set_global()
        
        # Plot viewpoints with cartopy transform
        scatter = ax.scatter(lons, lats, 
                           c='#FF5722',  # Orange-red color
                           s=8,  # Point size
                           alpha=0.6,
                           edgecolors='#D32F2F',
                           linewidths=0.3,
                           zorder=5,
                           transform=ccrs.PlateCarree())
        
        # Add grid
        ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
        
        # Title
        title = 'TourRAG Viewpoint Geographic Distribution'
        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
        
    elif world is not None and isinstance(world, gpd.GeoDataFrame):
        fig, ax = plt.subplots(1, 1, figsize=(16, 10))
        
        # Plot world map first (background)
        world.plot(ax=ax, color='#F0F0F0', edgecolor='#CCCCCC', linewidth=0.5, zorder=1)
        
        # Plot viewpoints on top of world map
        scatter = ax.scatter(lons, lats, 
                           c='#FF5722',  # Orange-red color
                           s=8,  # Point size
                           alpha=0.6,
                           edgecolors='#D32F2F',
                           linewidths=0.3,
                           zorder=5)
        
        # Set map bounds
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        
        # Add grid
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        ax.set_xlabel('Longitude', fontsize=12)
        ax.set_ylabel('Latitude', fontsize=12)
        
        # Title
        title = 'TourRAG Viewpoint Geographic Distribution'
        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
        
    else:
        # Fallback: Simple scatter plot without world map
        fig, ax = plt.subplots(1, 1, figsize=(16, 10))
        
        # Plot viewpoints
        scatter = ax.scatter(lons, lats, 
                           c='#FF5722',
                           s=8,
                           alpha=0.6,
                           edgecolors='#D32F2F',
                           linewidths=0.3)
        
        # Set bounds
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        ax.set_aspect('equal')
        
        # Add grid
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        ax.set_xlabel('Longitude', fontsize=12)
        ax.set_ylabel('Latitude', fontsize=12)
        
        # Title
        title = 'TourRAG Viewpoint Geographic Distribution'
        ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
        
        # Note about missing world map
        ax.text(0.5, 0.02, 
                'Note: World map background not available. Install geopandas for full map visualization.',
                transform=ax.transAxes, ha='center', fontsize=9, style='italic',
                bbox=dict(boxstyle="round,pad=0.3", facecolor='#FFF9C4', edgecolor='gray', alpha=0.7))
    
    # Add statistics text box
    stats_text = (
        f"Longitude Range: {min(lons):.2f}° to {max(lons):.2f}°\n"
        f"Latitude Range: {min(lats):.2f}° to {max(lats):.2f}°"
    )
    
    ax.text(0.02, 0.98, stats_text,
            transform=ax.transAxes,
            fontsize=10,
            verticalalignment='top',
            bbox=dict(boxstyle="round,pad=0.5", facecolor='white', edgecolor='gray', alpha=0.8))
    
    # Save figure
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"World map saved to: {output_file.absolute()}")
    plt.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate TourRAG diagrams')
    parser.add_argument('--type', '-t', choices=['architecture', 'worldmap', 'both'], 
                       default='both',
                       help='Type of diagram to generate (default: both)')
    parser.add_argument('--output', '-o', default=None,
                       help='Output file path (default: auto-generated)')
    parser.add_argument('--limit', '-l', type=int, default=None,
                       help='Limit number of viewpoints for world map (for performance)')
    
    args = parser.parse_args()
    
    if args.type in ['architecture', 'both']:
        arch_output = args.output or 'tourrag_architecture.png'
        if args.type == 'both' and args.output:
            # If both and output specified, use different names
            arch_output = args.output.replace('.png', '_architecture.png')
        create_system_architecture_diagram(arch_output)
    
    if args.type in ['worldmap', 'both']:
        map_output = args.output or 'viewpoint_world_map.png'
        if args.type == 'both' and args.output:
            # If both and output specified, use different names
            map_output = args.output.replace('.png', '_worldmap.png')
        create_world_map_from_database(map_output, limit=args.limit)