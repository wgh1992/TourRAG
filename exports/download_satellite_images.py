#!/usr/bin/env python3
"""
Download satellite images for viewpoints based on CSV data
根据CSV文件中的经纬度下载卫星图像
Usage: python scripts/download_satellite_images.py --id-range 40-200
"""
import os
import sys
import csv
import argparse
import time
from pathlib import Path
from typing import Tuple, Optional, List
from io import BytesIO

import requests
from PIL import Image

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def download_arcgis_imagery(bbox: Tuple[float, float, float, float], 
                           size: Tuple[int, int],
                           retry_count: int = 3) -> Optional[Image.Image]:
    """调用 ArcGIS World Imagery /export 获取卫星图"""
    
    # 多个服务端点
    services = [
        "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
    ]
    
    params = {
        "dpi": 96,
        "transparent": "false",
        "format": "png",
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{size[0]},{size[1]}",
        "f": "image",
    }
    
    for service in services:
        for attempt in range(retry_count):
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                resp = requests.get(service, params=params, headers=headers, timeout=60)
                resp.raise_for_status()
                
                # 验证内容
                if len(resp.content) < 1000:
                    continue
                
                img = Image.open(BytesIO(resp.content))
                
                # 验证尺寸
                if img.size[0] < 256 or img.size[1] < 256:
                    continue
                
                return img
                
            except Exception as e:
                if attempt < retry_count - 1:
                    time.sleep(2)
                    
    return None


def create_bbox_from_point(lon: float, lat: float, buffer_km: float = 1.0) -> Tuple[float, float, float, float]:
    """
    根据一个点创建边界框
    Args:
        lon: 经度
        lat: 纬度
        buffer_km: 缓冲区大小（公里），默认1公里
    Returns:
        (min_lon, min_lat, max_lon, max_lat)
    """
    import math
    
    # 1度纬度约等于111公里
    km_per_deg_lat = 111.0
    # 1度经度随纬度变化
    km_per_deg_lon = 111.321 * math.cos(math.radians(lat))
    
    # 计算缓冲区的度数
    buffer_lat = buffer_km / km_per_deg_lat
    buffer_lon = buffer_km / km_per_deg_lon
    
    return (
        lon - buffer_lon,  # min_lon
        lat - buffer_lat,  # min_lat
        lon + buffer_lon,  # max_lon
        lat + buffer_lat   # max_lat
    )


def parse_id_range(id_range_str: str) -> Tuple[int, int]:
    """解析ID范围字符串，例如 '40-200' 或 '40'"""
    if '-' in id_range_str:
        parts = id_range_str.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid ID range format: {id_range_str}. Expected format: 'start-end' or 'id'")
        return int(parts[0].strip()), int(parts[1].strip())
    else:
        # 单个ID
        id_val = int(id_range_str.strip())
        return id_val, id_val


def load_viewpoints_from_csv(csv_file: str, id_start: int = None, id_end: int = None) -> List[dict]:
    """从CSV文件加载景点数据"""
    viewpoints = []
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            viewpoint_id = int(row['viewpoint_id'])
            
            # 过滤ID范围
            if id_start is not None and viewpoint_id < id_start:
                continue
            if id_end is not None and viewpoint_id > id_end:
                continue
            
            # 检查必需的字段
            try:
                lon = float(row['longitude'])
                lat = float(row['latitude'])
                name = row.get('name_primary', f'viewpoint_{viewpoint_id}')
            except (ValueError, KeyError) as e:
                print(f"⚠️  跳过 viewpoint_id={viewpoint_id}: 缺少必需字段 ({e})")
                continue
            
            viewpoints.append({
                'viewpoint_id': viewpoint_id,
                'name': name,
                'longitude': lon,
                'latitude': lat
            })
    
    return viewpoints


def download_satellite_images(
    csv_file: str,
    output_dir: str,
    id_range: str = None,
    buffer_km: float = 1.0,
    image_size: Tuple[int, int] = (1024, 1024),
    delay: float = 0.5
):
    """下载卫星图像"""
    
    # 解析ID范围
    id_start = None
    id_end = None
    if id_range:
        id_start, id_end = parse_id_range(id_range)
        print(f"📋 ID范围: {id_start} - {id_end}")
    
    # 加载景点数据
    print(f"📖 正在读取CSV文件: {csv_file}")
    viewpoints = load_viewpoints_from_csv(csv_file, id_start, id_end)
    
    if not viewpoints:
        print("❌ 没有找到符合条件的景点")
        return
    
    print(f"✓ 找到 {len(viewpoints)} 个景点")
    print(f"📁 输出目录: {output_dir}")
    print(f"🖼️  图像尺寸: {image_size[0]}×{image_size[1]}px")
    print(f"📏 缓冲区: {buffer_km}km")
    print()
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    success_count = 0
    failed_count = 0
    failed_list = []
    
    for idx, vp in enumerate(viewpoints, 1):
        viewpoint_id = vp['viewpoint_id']
        name = vp['name']
        lon = vp['longitude']
        lat = vp['latitude']
        
        print(f"[{idx}/{len(viewpoints)}] 处理 viewpoint_id={viewpoint_id}: {name}")
        print(f"  位置: ({lon:.6f}, {lat:.6f})")
        
        # 创建边界框
        bbox = create_bbox_from_point(lon, lat, buffer_km)
        print(f"  BBox: ({bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f})")
        
        # 下载图像
        print(f"  正在下载卫星图像...")
        img = download_arcgis_imagery(bbox, image_size)
        
        if img:
            # 保存图像
            filename = f"{viewpoint_id}.png"
            filepath = os.path.join(output_dir, filename)
            img.save(filepath, 'PNG', quality=95)
            
            file_size = os.path.getsize(filepath)
            print(f"  ✅ 成功保存: {filename} ({file_size:,} bytes, {img.size[0]}×{img.size[1]}px)")
            success_count += 1
        else:
            print(f"  ❌ 下载失败")
            failed_count += 1
            failed_list.append({
                'viewpoint_id': viewpoint_id,
                'name': name,
                'longitude': lon,
                'latitude': lat
            })
        
        # 延迟（除了最后一个）
        if idx < len(viewpoints):
            print(f"  等待 {delay} 秒...")
            time.sleep(delay)
        print()
    
    # 保存失败列表
    if failed_list:
        failed_file = os.path.join(output_dir, 'failed_list.csv')
        with open(failed_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['viewpoint_id', 'name', 'longitude', 'latitude'])
            writer.writeheader()
            writer.writerows(failed_list)
        print(f"📝 失败列表已保存: {failed_file}")
    
    # 总结
    print("=" * 80)
    print("下载完成！")
    print(f"  总计: {len(viewpoints)} 个景点")
    print(f"  成功: {success_count}")
    print(f"  失败: {failed_count}")
    print(f"  输出目录: {os.path.abspath(output_dir)}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Download satellite images for viewpoints from CSV file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download images for IDs 62323-62325
  python exports/download_satellite_images.py --id-range 62323-62325 --delay 0.1
  
  # Download image for single ID
  python exports/download_satellite_images.py --id-range 62323
  
  # Download all images
  python exports/download_satellite_images.py
  
  # Custom CSV file and output directory
  python exports/download_satellite_images.py --csv viewpoints_info.csv --output images --id-range 62323-62325
        """
    )
    parser.add_argument(
        '--csv',
        type=str,
        default='viewpoints_info.csv',
        help='CSV file path (default: viewpoints_info.csv, relative to exports/)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='images',
        help='Output directory for images (default: images, relative to exports/)'
    )
    parser.add_argument(
        '--id-range',
        type=str,
        default=None,
        help='ID range to download, e.g., "40-200" or "100" (default: all)'
    )
    parser.add_argument(
        '--buffer',
        type=float,
        default=1.0,
        help='Buffer size in kilometers around the point (default: 1.0)'
    )
    parser.add_argument(
        '--size',
        type=int,
        nargs=2,
        default=[1024, 1024],
        metavar=('WIDTH', 'HEIGHT'),
        help='Image size in pixels (default: 1024 1024)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Delay between requests in seconds (default: 0.5)'
    )
    
    args = parser.parse_args()
    
    # 处理路径：如果路径不是绝对路径，则相对于exports目录
    script_dir = Path(__file__).parent
    csv_file = args.csv if os.path.isabs(args.csv) else script_dir / args.csv
    output_dir = args.output if os.path.isabs(args.output) else script_dir / args.output
    
    # 检查CSV文件是否存在
    if not os.path.exists(csv_file):
        print(f"❌ 错误: CSV文件不存在: {csv_file}")
        sys.exit(1)
    
    download_satellite_images(
        csv_file=str(csv_file),
        output_dir=str(output_dir),
        id_range=args.id_range,
        buffer_km=args.buffer,
        image_size=tuple(args.size),
        delay=args.delay
    )


if __name__ == '__main__':
    main()
