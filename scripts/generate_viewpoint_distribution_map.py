"""
Generate viewpoint distribution map similar to SA-1B geographic distribution visualization
Creates a world map and bar chart showing viewpoint distribution by country
"""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd
try:
    import geopandas as gpd
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False
    gpd = None
from typing import Dict, List, Tuple
import os

# Optional imports for enhanced visualization
try:
    import contextily as ctx
    HAS_CTX = True
except ImportError:
    HAS_CTX = False

from app.config import settings


def setup_chinese_font():
    """
    Setup Chinese font for matplotlib to avoid missing glyph warnings
    Tries common Chinese fonts on different platforms
    """
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
    
    # Try to find and set a Chinese font
    for font_name in chinese_fonts:
        try:
            # Check if font exists
            font_path = fm.findfont(fm.FontProperties(family=font_name))
            if font_path:
                plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
                plt.rcParams['axes.unicode_minus'] = False  # Fix minus sign display
                return True
        except:
            continue
    
    # If no Chinese font found, use English labels instead
    print("Warning: No Chinese font found. Using English labels.")
    return False


def get_viewpoint_count_by_country() -> pd.DataFrame:
    """
    Query database to get viewpoint count per country
    Returns DataFrame with columns: country, count
    
    Tries multiple strategies:
    1. First tries viewpoint_commons_assets.viewpoint_country (if populated)
    2. Falls back to extracting country from viewpoint_entity using reverse geocoding
    3. If no country info available, shows total count
    """
    conn = psycopg2.connect(settings.DATABASE_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Strategy 1: Try to get country from viewpoint_commons_assets
    query1 = """
    SELECT 
        viewpoint_country as country,
        COUNT(DISTINCT viewpoint_id) as count
    FROM viewpoint_commons_assets
    WHERE viewpoint_country IS NOT NULL AND viewpoint_country != ''
    GROUP BY viewpoint_country
    ORDER BY count DESC;
    """
    
    cursor.execute(query1)
    results = cursor.fetchall()
    
    # Convert to DataFrame
    df = pd.DataFrame(results)
    
    if not df.empty:
        cursor.close()
        conn.close()
        return df
    
    # Strategy 2: Check if there are any viewpoints in viewpoint_entity at all
    # admin_area_ids typically contains OSM relation IDs (numbers), not country names
    # To get country names, we need to use reverse geocoding (via download script)
    print("No country data in viewpoint_commons_assets.")
    print("Note: admin_area_ids contains OSM relation IDs, not country names.")
    print("To get country distribution, country information needs to be populated via reverse geocoding.")
    
    # Strategy 3: If no country info available, at least show total count
    print("Could not extract country information from admin_area_ids.")
    print("Showing total viewpoint count...")
    
    query3 = """
    SELECT COUNT(*) as total_count
    FROM viewpoint_entity;
    """
    
    cursor.execute(query3)
    total_result = cursor.fetchone()
    total_count = total_result['total_count'] if total_result else 0
    
    cursor.close()
    conn.close()
    
    if total_count > 0:
        print(f"Found {total_count} viewpoints in database, but no country information available.")
        print("To get country distribution, please run:")
        print("  python scripts/download_all_viewpoint_images.py")
        print("This will populate the viewpoint_country field using reverse geocoding.")
        
        # Return a single row with "Unknown" country
        return pd.DataFrame([{'country': 'Unknown (Run download script to get country data)', 'count': total_count}])
    
    return pd.DataFrame(columns=['country', 'count'])


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
        # First try the deprecated method (still works in most cases)
        try:
            world = gpd.read_file(gpd.datasets.get_path('naturalearth_lowres'))
            return world
        except (AttributeError, FileNotFoundError):
            # If deprecated method fails, try direct download
            import urllib.request
            import tempfile
            import zipfile
            
            # Download Natural Earth data directly
            ne_url = "https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/110m/cultural/ne_110m_admin_0_countries.zip"
            
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = Path(tmpdir) / "ne_countries.zip"
                urllib.request.urlretrieve(ne_url, zip_path)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                
                shp_path = Path(tmpdir) / "ne_110m_admin_0_countries.shp"
                if shp_path.exists():
                    world = gpd.read_file(str(shp_path))
                    return world
    except Exception as e:
        print(f"Could not load Natural Earth data: {e}")
        print("Note: World map visualization requires geopandas with Natural Earth data.")
        print("The bar chart will still be generated.")
        return None


def get_country_iso_code(country: str) -> str:
    """
    Get ISO 3166-1 alpha-3 code for country name
    Returns country name if ISO code not found
    """
    if not country or pd.isna(country):
        return ''
    
    # ISO 3166-1 alpha-3 code mapping
    iso_mapping = {
        'United States': 'USA', 'USA': 'USA', 'US': 'USA',
        'United States of America': 'USA',
        'Japan': 'JPN',
        'Italy': 'ITA',
        'United Kingdom': 'GBR', 'UK': 'GBR',
        'Germany': 'DEU',
        'Spain': 'ESP',
        'Indonesia': 'IDN',
        'Ukraine': 'UKR',
        'France': 'FRA',
        'Thailand': 'THA',
        'Malaysia': 'MYS',
        'Turkey': 'TUR',
        'India': 'IND',
        'China': 'CHN',
        'Poland': 'POL',
        'Netherlands': 'NLD',
        'Vietnam': 'VNM',
        'Brazil': 'BRA',
        'Canada': 'CAN',
        'Greece': 'GRC',
        'Australia': 'AUS',
        'Portugal': 'PRT',
        'Czech Republic': 'CZE', 'Czechia': 'CZE',
        'Belarus': 'BLR',
        'Romania': 'ROU',
        'South Korea': 'KOR', 'Korea': 'KOR',
        'United Arab Emirates': 'ARE', 'UAE': 'ARE',
        'Austria': 'AUT',
        'Sweden': 'SWE',
        'Taiwan': 'TWN',
        'Hong Kong': 'HKG',
        'Switzerland': 'CHE',
        'Israel': 'ISR',
        'Singapore': 'SGP',
        'Hungary': 'HUN',
        'Belgium': 'BEL',
        'Croatia': 'HRV',
        'Bulgaria': 'BGR',
        'Philippines': 'PHL',
        'Kazakhstan': 'KAZ',
        'Mexico': 'MEX',
        'Norway': 'NOR',
        'Myanmar': 'MMR',
        'South Africa': 'ZAF',
        'Serbia': 'SRB',
        'Denmark': 'DNK',
        'Morocco': 'MAR',
        'Finland': 'FIN',
        'Latvia': 'LVA',
        'Russia': 'RUS', 'Russian Federation': 'RUS',
        'New Zealand': 'NZL',
        'Argentina': 'ARG',
        'Chile': 'CHL',
        'Peru': 'PER',
        'Colombia': 'COL',
        'Egypt': 'EGY',
        'Kenya': 'KEN',
        'Tanzania': 'TZA',
        'Ethiopia': 'ETH',
        'Ghana': 'GHA',
        'Nigeria': 'NGA',
        'Algeria': 'DZA',
        'Tunisia': 'TUN',
        'Zimbabwe': 'ZWE',
        'Uganda': 'UGA',
        'Bangladesh': 'BGD',
        'Pakistan': 'PAK',
        'Sri Lanka': 'LKA',
        'Cambodia': 'KHM',
        'Laos': 'LAO',
        'Nepal': 'NPL',
        'Mongolia': 'MNG',
        'Ireland': 'IRL',
    }
    
    country = str(country).strip()
    return iso_mapping.get(country, country[:3].upper() if len(country) >= 3 else country)


def normalize_country_name(country: str) -> str:
    """
    Normalize country names to match map data
    """
    if not country or pd.isna(country):
        return ''
    
    # Common name mappings to match Natural Earth dataset
    mappings = {
        'United States': 'United States of America',
        'USA': 'United States of America',
        'US': 'United States of America',
        'UK': 'United Kingdom',
        'Russia': 'Russian Federation',
        'South Korea': 'South Korea',
        'North Korea': 'North Korea',
        'Czech Republic': 'Czechia',
        'Myanmar': 'Myanmar',
        'Macedonia': 'North Macedonia',
    }
    
    country = str(country).strip()
    return mappings.get(country, country)


def categorize_count(count: int) -> str:
    """
    Categorize count into bins similar to the reference image
    """
    if count >= 100000:
        return '≥ 100k'
    elif count >= 10000:
        return '10k-100k'
    elif count >= 1000:
        return '1k-10k'
    else:
        return '< 1k'


def get_color_for_category(category: str) -> str:
    """
    Get color for each category (similar to reference image)
    """
    colors = {
        '≥ 100k': '#2E7D32',      # Dark green
        '10k-100k': '#FF9800',    # Orange
        '1k-10k': '#9CCC65',      # Light green/yellow-green
        '< 1k': '#9E9E9E',        # Grey
    }
    return colors.get(category, '#9E9E9E')


def get_continent_color(country: str) -> str:
    """
    Get color by continent (for bar chart)
    """
    # Simple continent mapping (can be expanded)
    asia_oceania = ['China', 'Japan', 'India', 'Thailand', 'Indonesia', 'Malaysia', 
                    'Vietnam', 'South Korea', 'Philippines', 'Australia', 'New Zealand',
                    'Singapore', 'Taiwan', 'Hong Kong', 'Bangladesh', 'Pakistan',
                    'Sri Lanka', 'Myanmar', 'Cambodia', 'Laos', 'Nepal', 'Mongolia']
    
    africa = ['South Africa', 'Egypt', 'Morocco', 'Kenya', 'Tanzania', 'Ethiopia',
              'Ghana', 'Nigeria', 'Algeria', 'Tunisia', 'Zimbabwe', 'Uganda']
    
    europe = ['Russia', 'United Kingdom', 'France', 'Germany', 'Italy', 'Spain',
              'Poland', 'Netherlands', 'Greece', 'Portugal', 'Sweden', 'Norway',
              'Denmark', 'Finland', 'Belgium', 'Austria', 'Switzerland', 'Czech Republic',
              'Ukraine', 'Romania', 'Hungary', 'Ireland', 'Croatia', 'Bulgaria']
    
    north_america = ['United States of America', 'United States', 'USA', 'Canada', 'Mexico']
    
    latin_america = ['Brazil', 'Argentina', 'Chile', 'Peru', 'Colombia', 'Venezuela',
                     'Ecuador', 'Uruguay', 'Paraguay', 'Bolivia', 'Costa Rica', 'Panama']
    
    country_normalized = normalize_country_name(country)
    
    if country_normalized in asia_oceania:
        return '#2196F3'  # Blue
    elif country_normalized in africa:
        return '#FF9800'  # Orange
    elif country_normalized in europe:
        return '#4CAF50'  # Green
    elif country_normalized in north_america:
        return '#F44336'  # Red
    elif country_normalized in latin_america:
        return '#9C27B0'  # Purple
    else:
        return '#757575'  # Grey (unknown)


def create_viewpoint_distribution_visualization(output_path: str = 'viewpoint_distribution.png'):
    """
    Create visualization similar to SA-1B geographic distribution figure
    """
    # Setup Chinese font support
    has_chinese_font = setup_chinese_font()
    
    # Get data
    print("Querying database for viewpoint distribution...")
    df = get_viewpoint_count_by_country()
    
    if df.empty:
        print("No data found. Please ensure you have populated the database with viewpoint data.")
        return
    
    # Check if we only have "Unknown" country data
    if len(df) == 1 and 'Unknown' in str(df.iloc[0]['country']):
        print("\n" + "="*60)
        print("注意：数据库中没有国家信息")
        print("="*60)
        print(f"找到 {df.iloc[0]['count']} 个景点，但没有国家信息。")
        print("\n要生成国家分布图，请运行以下命令来获取国家信息：")
        print("  python scripts/download_all_viewpoint_images.py")
        print("\n这将使用反向地理编码从坐标中提取国家信息。")
        print("="*60 + "\n")
        
        # Still create a simple visualization showing total count
        fig = plt.figure(figsize=(10, 6))
        ax = plt.subplot(1, 1, 1)
        
        # Create a simple bar chart showing total count
        ax.barh([0], [df.iloc[0]['count']], color='#757575')
        ax.set_yticks([0])
        
        # Use Chinese labels if font is available, otherwise use English
        if has_chinese_font:
            ax.set_yticklabels(['所有景点'])
            ax.set_xlabel('景点数量', fontsize=12)
            ax.set_title('景点总数（无国家信息）', fontsize=14, fontweight='bold')
            fig.suptitle('TourRAG 景点统计', fontsize=16, fontweight='bold')
            fig.text(0.5, 0.02, 
                    f"数据库中共有 {df.iloc[0]['count']} 个景点，但缺少国家信息。\n"
                    "请运行下载脚本来获取国家分布数据。",
                    ha='center', fontsize=10, style='italic')
        else:
            ax.set_yticklabels(['All Viewpoints'])
            ax.set_xlabel('Number of Viewpoints', fontsize=12)
            ax.set_title('Total Viewpoints (No Country Data)', fontsize=14, fontweight='bold')
            fig.suptitle('TourRAG Viewpoint Statistics', fontsize=16, fontweight='bold')
            fig.text(0.5, 0.02, 
                    f"Database contains {df.iloc[0]['count']} viewpoints, but country information is missing.\n"
                    "Please run the download script to get country distribution data.",
                    ha='center', fontsize=10, style='italic')
        
        ax.grid(axis='x', alpha=0.3, linestyle='--')
        
        plt.tight_layout(rect=[0, 0.05, 1, 0.96])
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        print(f"已生成统计图: {output_file.absolute()}")
        plt.close()
        return
    
    print(f"Found {len(df)} countries with viewpoint data")
    print(f"Total viewpoints: {df['count'].sum()}")
    
    # Normalize country names
    df['country_normalized'] = df['country'].apply(normalize_country_name)
    
    # Get world map
    print("Loading world map data...")
    world = get_world_map_data()
    
    # Create figure with subplots
    # If world map is available, use two subplots; otherwise just bar chart
    if world is not None:
        fig = plt.figure(figsize=(16, 8))
        # Left subplot: World map
        ax1 = plt.subplot(1, 2, 1)
    else:
        # Create figure with better layout for bar chart only
        fig = plt.figure(figsize=(14, 10))
        # Only bar chart
        ax1 = None
    
    if world is not None and ax1 is not None:
        # Merge world map with viewpoint data
        # Try multiple merge strategies for better country name matching
        merged = world.merge(
            df,
            left_on='name',
            right_on='country_normalized',
            how='left'
        )
        
        # If merge didn't work well, try alternative name matching
        if merged['count'].isna().sum() > len(df) * 0.5:
            # Try matching with ISO_A3 codes if available
            if 'iso_a3' in world.columns:
                # This would require ISO code mapping, skip for now
                pass
        
        # Categorize counts
        merged['category'] = merged['count'].apply(
            lambda x: categorize_count(x) if pd.notna(x) and x > 0 else 'No data'
        )
        merged['color'] = merged['category'].apply(
            lambda cat: get_color_for_category(cat) if cat != 'No data' else '#E0E0E0'
        )
        
        # Plot map
        merged.plot(ax=ax1, color=merged['color'], edgecolor='white', linewidth=0.3)
        
        # Set title and labels
        ax1.set_title('Per country viewpoint count', fontsize=14, fontweight='bold')
        ax1.set_xlabel('Longitude', fontsize=10)
        ax1.set_ylabel('Latitude', fontsize=10)
        ax1.axis('off')
        
        # Create legend
        legend_elements = [
            mpatches.Patch(facecolor='#2E7D32', label='≥ 100k'),
            mpatches.Patch(facecolor='#FF9800', label='10k-100k'),
            mpatches.Patch(facecolor='#9CCC65', label='1k-10k'),
            mpatches.Patch(facecolor='#9E9E9E', label='< 1k'),
        ]
        ax1.legend(handles=legend_elements, loc='upper right', fontsize=9, framealpha=0.9)
    
    # Right subplot: Bar chart (or main plot if no map)
    if world is not None:
        ax2 = plt.subplot(1, 2, 2)
    else:
        # Use full figure for bar chart when no map
        ax2 = plt.subplot(1, 1, 1)
    
    # Get top 50 countries (or all if less than 50)
    n_countries = min(50, len(df))
    top_countries = df.nlargest(n_countries, 'count')
    
    # Sort by count ascending for horizontal bar chart
    top_countries = top_countries.sort_values('count', ascending=True)
    
    # Get colors for bars
    bar_colors = [get_continent_color(country) for country in top_countries['country']]
    
    # Get ISO codes for y-axis labels (like in reference image)
    iso_codes = [get_country_iso_code(country) for country in top_countries['country']]
    
    # Create horizontal bar chart
    bars = ax2.barh(range(len(top_countries)), top_countries['count'], color=bar_colors)
    
    # Set y-axis labels using ISO codes (like reference image)
    ax2.set_yticks(range(len(top_countries)))
    ax2.set_yticklabels(iso_codes, fontsize=9)
    
    # Set x-axis
    max_count = top_countries['count'].max()
    ax2.set_xlabel('Number of viewpoints per country', fontsize=11)
    ax2.set_xlim(0, max_count * 1.1)
    
    # Format x-axis ticks (similar to reference image with 0-800k scale)
    if max_count >= 100000:
        # Use k notation for large numbers
        ax2.set_xticks(range(0, int(max_count * 1.1) + 100000, max(100000, int(max_count / 8))))
        ax2.set_xticklabels([f'{int(x/1000)}k' if x >= 1000 else str(int(x)) 
                            for x in ax2.get_xticks()], fontsize=9)
    elif max_count >= 10000:
        ax2.set_xticks(range(0, int(max_count * 1.1) + 10000, max(10000, int(max_count / 8))))
        ax2.set_xticklabels([f'{int(x/1000)}k' if x >= 1000 else str(int(x)) 
                            for x in ax2.get_xticks()], fontsize=9)
    else:
        ax2.tick_params(axis='x', labelsize=9)
    
    title_text = f'{n_countries} most common countries' if n_countries < 50 else '50 most common countries'
    ax2.set_title(title_text, fontsize=12, fontweight='bold')
    ax2.grid(axis='x', alpha=0.3, linestyle='--')
    
    # Create legend for continents
    continent_legend = [
        mpatches.Patch(facecolor='#2196F3', label='Asia & Oceania'),
        mpatches.Patch(facecolor='#FF9800', label='Africa'),
        mpatches.Patch(facecolor='#4CAF50', label='Europe'),
        mpatches.Patch(facecolor='#F44336', label='North America'),
        mpatches.Patch(facecolor='#9C27B0', label='Latin America & Caribbean'),
    ]
    ax2.legend(handles=continent_legend, loc='upper right', fontsize=8)
    
    # Overall title
    fig.suptitle('Estimated geographic distribution of TourRAG viewpoints', 
                fontsize=16, fontweight='bold', y=0.98)
    
    # Add caption
    total_countries = len(df[df['count'] >= 1000])
    top_three = top_countries.tail(3)['country'].tolist()
    caption = (f"Most of the world's countries have more than 1000 viewpoints in TourRAG, "
              f"and the three countries with the most viewpoints are: {', '.join(reversed(top_three))}")
    
    fig.text(0.5, 0.02, caption, ha='center', fontsize=10, style='italic', wrap=True)
    
    # Adjust layout
    plt.tight_layout(rect=[0, 0.05, 1, 0.96])
    
    # Save figure
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Visualization saved to: {output_file.absolute()}")
    
    # Also save data to CSV
    csv_path = output_file.with_suffix('.csv')
    df.to_csv(csv_path, index=False)
    print(f"Data exported to: {csv_path.absolute()}")
    
    plt.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate viewpoint distribution map')
    parser.add_argument('--output', '-o', default='viewpoint_distribution.png',
                       help='Output file path (default: viewpoint_distribution.png)')
    parser.add_argument('--csv-only', action='store_true',
                       help='Only generate CSV file, skip visualization')
    parser.add_argument('--csv-output', default=None,
                       help='CSV output file path (default: same as output with .csv extension)')
    
    args = parser.parse_args()
    
    if args.csv_only:
        # Only generate CSV
        df = get_viewpoint_count_by_country()
        csv_path = args.csv_output or args.output.replace('.png', '.csv').replace('.jpg', '.csv')
        csv_file = Path(csv_path)
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        
        if df.empty or (len(df) == 1 and 'Unknown' in str(df.iloc[0]['country'])):
            print("⚠️  No country data found in database.")
            print("\nTo get country information, run:")
            print("  python scripts/get_country_info_only.py")
            print("or")
            print("  python scripts/download_all_viewpoint_images.py")
            print("\nGenerating CSV with total count only...")
        
        # Add percentage and rank columns
        total = df['count'].sum() if not df.empty else 0
        if not df.empty:
            df['percentage'] = (df['count'] / total * 100).round(2)
            df.insert(0, 'rank', range(1, len(df) + 1))
        
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"\n✅ CSV file generated: {csv_file.absolute()}")
        print(f"   Total countries: {len(df)}")
        print(f"   Total viewpoints: {total}")
        
        if not df.empty and not (len(df) == 1 and 'Unknown' in str(df.iloc[0]['country'])):
            # Show top 10
            print("\nTop 10 countries:")
            for idx, row in df.head(10).iterrows():
                print(f"  {row['rank']}. {row['country']}: {row['count']} ({row['percentage']}%)")
    else:
        # Generate visualization (which also generates CSV)
        create_viewpoint_distribution_visualization(args.output)
