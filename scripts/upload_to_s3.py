#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量上传图片到AWS S3并更新数据库

使用方法:
1. 配置AWS凭证（使用以下方式之一）:
   - 环境变量: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
   - AWS配置文件: ~/.aws/credentials
   - IAM角色（如果在EC2上运行）

2. 运行上传脚本:
python scripts/upload_to_s3.py \
    --image-dir exports/images/all_image \
    --bucket my-image-bucket-liuyu-cv \
    --region us-east-1 \
    --limit 10 \
    --delay 1.0
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
import argparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor

# AWS S3
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False
    print("Warning: AWS SDK (boto3) not available.")
    print("Install with: pip install boto3")


class S3Uploader:
    """AWS S3上传器"""
    
    def __init__(self, bucket_name: str, region: str = "us-east-1"):
        """
        初始化S3上传器
        
        Args:
            bucket_name: S3 bucket名称
            region: AWS区域（默认: us-east-1）
        """
        if not AWS_AVAILABLE:
            raise ImportError("AWS SDK (boto3) not available. Install required packages.")
        
        self.bucket_name = bucket_name
        self.region = region
        
        try:
            # 初始化S3客户端
            self.s3_client = boto3.client('s3', region_name=region)
            
            # 验证bucket是否存在
            self.s3_client.head_bucket(Bucket=bucket_name)
            print(f"✓ S3 client initialized")
            print(f"  Bucket: {bucket_name}")
            print(f"  Region: {region}")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                raise ValueError(f"Bucket '{bucket_name}' not found. Please create it first.")
            elif error_code == '403':
                raise ValueError(f"Access denied to bucket '{bucket_name}'. Check your AWS credentials.")
            else:
                raise
        except NoCredentialsError:
            raise ValueError(
                "AWS credentials not found. Please configure:\n"
                "1. Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY\n"
                "2. AWS config file: ~/.aws/credentials\n"
                "3. IAM role (if running on EC2)"
            )
    
    def upload_file(self, file_path: str, object_key: Optional[str] = None) -> Optional[str]:
        """
        上传文件到S3，返回公开URL
        
        Args:
            file_path: 本地文件路径
            object_key: S3对象键（可选，默认使用文件名）
        
        Returns:
            公开访问URL或None（如果失败）
        """
        try:
            if object_key is None:
                object_key = os.path.basename(file_path)
            
            # 上传文件
            # 注意：如果bucket配置为"Bucket owner enforced"（ACL disabled），
            # 则不能设置ACL，应该使用bucket policy来控制访问
            self.s3_client.upload_file(
                file_path,
                self.bucket_name,
                object_key,
                ExtraArgs={
                    'ContentType': 'image/png'
                    # 不设置ACL，依赖bucket policy控制访问（适用于ACL disabled的bucket）
                }
            )
            
            # 生成公开URL
            # 格式: https://<bucket-name>.s3.amazonaws.com/<object-key>
            # 或: https://<bucket-name>.s3.<region>.amazonaws.com/<object-key>
            if self.region == 'us-east-1':
                # us-east-1使用特殊格式（不带region）
                url = f"https://{self.bucket_name}.s3.amazonaws.com/{object_key}"
            else:
                url = f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{object_key}"
            
            return url
        
        except ClientError as e:
            print(f"  ✗ Upload failed for {file_path}: {e}")
            return None
        except Exception as e:
            print(f"  ✗ Upload failed for {file_path}: {e}")
            return None
    
    def update_database_url(self, viewpoint_id: int, s3_url: str) -> bool:
        """
        Update database with S3 URL for a viewpoint
        
        Args:
            viewpoint_id: Viewpoint ID
            s3_url: S3 URL
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with db.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    # Check if record exists
                    cursor.execute("""
                        SELECT id FROM viewpoint_commons_assets
                        WHERE viewpoint_id = %s
                        LIMIT 1
                    """, (viewpoint_id,))
                    existing = cursor.fetchone()
                    
                    if existing:
                        # Update existing record
                        cursor.execute("""
                            UPDATE viewpoint_commons_assets
                            SET local_path_or_blob_ref = %s
                            WHERE viewpoint_id = %s
                            AND (local_path_or_blob_ref IS NULL OR local_path_or_blob_ref NOT LIKE 'https://%.s3.%')
                        """, (s3_url, viewpoint_id))
                    else:
                        # Insert new record
                        cursor.execute("""
                            INSERT INTO viewpoint_commons_assets (
                                viewpoint_id, commons_file_id, local_path_or_blob_ref
                            ) VALUES (%s, %s, %s)
                        """, (viewpoint_id, f"viewpoint_{viewpoint_id}", s3_url))
                    
                    conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            print(f"  ✗ Database update failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def batch_upload_viewpoint_images(self,
                                     image_dir: str,
                                     prefix: str = "viewpoints",
                                     limit: Optional[int] = None,
                                     delay: float = 1.0) -> Dict:
        """
        Batch upload viewpoint images to S3 and update database
        
        Args:
            image_dir: Directory containing images (filename format: {viewpoint_id}.png)
            prefix: S3 object key prefix (default: "viewpoints")
            limit: Maximum number of images to upload (for testing)
            delay: Upload interval in seconds
            
        Returns:
            Dictionary with upload statistics
        """
        image_path = Path(image_dir)
        if not image_path.exists():
            raise FileNotFoundError(f"Directory not found: {image_dir}")
        
        # Get all PNG files
        image_files = sorted([
            f for f in image_path.glob("*.png")
            if not f.name.startswith('._') and not f.name.startswith('.')
        ])
        
        if limit:
            image_files = image_files[:limit]
        
        print("="*70)
        print(f"AWS S3批量上传景点图片")
        print(f"  目录: {image_dir}")
        print(f"  文件数: {len(image_files)}")
        print(f"  Bucket: {self.bucket_name}")
        print(f"  前缀: {prefix}")
        print("="*70)
        
        uploaded_count = 0
        updated_count = 0
        skipped_count = 0
        failed_list = []
        
        for idx, img_file in enumerate(image_files, 1):
            # Extract viewpoint_id from filename (e.g., "62323.png" -> 62323)
            try:
                viewpoint_id = int(img_file.stem)
            except ValueError:
                print(f"\n[{idx}/{len(image_files)}] {img_file.name}")
                print(f"  ⊘ 跳过: 无法从文件名提取viewpoint_id")
                skipped_count += 1
                continue
            
            print(f"\n[{idx}/{len(image_files)}] {img_file.name} (viewpoint_id: {viewpoint_id})")
            
            # Check if already uploaded (check database)
            try:
                with db.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT local_path_or_blob_ref
                        FROM viewpoint_commons_assets
                        WHERE viewpoint_id = %s
                        AND local_path_or_blob_ref LIKE 'https://%.s3.%'
                        LIMIT 1
                    """, (viewpoint_id,))
                    existing = cursor.fetchone()
                    if existing and existing.get('local_path_or_blob_ref'):
                        print(f"  ⊘ 跳过: 数据库中已有S3 URL")
                        skipped_count += 1
                        continue
            except Exception as e:
                # If check fails, continue with upload anyway
                pass
            
            # Generate S3 object key
            object_key = f"{prefix.rstrip('/')}/{viewpoint_id}.png"
            
            # Upload file
            url = self.upload_file(str(img_file), object_key)
            
            if url:
                # Update database
                if self.update_database_url(viewpoint_id, url):
                    print(f"  ✓ 成功: {url}")
                    print(f"  ✓ 数据库已更新")
                    uploaded_count += 1
                    updated_count += 1
                else:
                    print(f"  ⚠ 上传成功但数据库更新失败: {url}")
                    uploaded_count += 1
            else:
                failed_list.append((img_file.name, viewpoint_id))
                print(f"  ✗ 上传失败")
            
            # Delay between uploads
            if idx < len(image_files):
                time.sleep(delay)
        
        print(f"\n{'='*70}")
        print(f"上传完成!")
        print(f"  成功上传: {uploaded_count}/{len(image_files)}")
        print(f"  数据库更新: {updated_count}")
        print(f"  跳过: {skipped_count}")
        print(f"  失败: {len(failed_list)}")
        print(f"{'='*70}")
        
        if failed_list:
            print(f"\n失败列表:")
            for filename, vp_id in failed_list[:10]:
                print(f"  - {filename} (viewpoint_id: {vp_id})")
            if len(failed_list) > 10:
                print(f"  ... and {len(failed_list) - 10} more")
        
        return {
            'uploaded': uploaded_count,
            'updated': updated_count,
            'skipped': skipped_count,
            'failed': len(failed_list)
        }
    
    def batch_upload(self, 
                    image_dir: str,
                    output_mapping: str = "url_mapping.json",
                    category: str = "attraction",
                    prefix: str = "",
                    delay: float = 1.0) -> Dict:
        """
        批量上传图片到S3
        
        Args:
            image_dir: 图片目录路径
            output_mapping: URL映射文件路径
            category: 图片类别 ("attraction" 或 "whole")
            prefix: S3对象键前缀（可选，用于组织文件）
            delay: 上传间隔（秒）
        
        Returns:
            更新后的URL映射字典
        """
        image_path = Path(image_dir)
        if not image_path.exists():
            raise FileNotFoundError(f"Directory not found: {image_dir}")
        
        # Load existing mapping
        if os.path.exists(output_mapping):
            with open(output_mapping, 'r', encoding='utf-8') as f:
                url_mapping = json.load(f)
        else:
            url_mapping = {"attraction": {}, "whole": {}}
        
        # Get all image files
        image_files = sorted([
            f for f in image_path.glob("*.png")
            if not f.name.startswith('._') and not f.name.startswith('.')
        ])
        
        print("="*70)
        print(f"AWS S3批量上传")
        print(f"  目录: {image_dir}")
        print(f"  类别: {category}")
        print(f"  文件数: {len(image_files)}")
        print(f"  Bucket: {self.bucket_name}")
        print(f"  前缀: {prefix if prefix else '(无)'}")
        print("="*70)
        
        uploaded_count = 0
        skipped_count = 0
        failed_list = []
        
        for idx, img_file in enumerate(image_files, 1):
            print(f"\n[{idx}/{len(image_files)}] {img_file.name}")
            
            # Check if already exists in mapping
            if category in url_mapping and img_file.name in url_mapping[category]:
                existing_url = url_mapping[category][img_file.name]
                if existing_url and not existing_url.startswith("YOUR_") and "s3.amazonaws.com" in existing_url:
                    print(f"  ⊘ 跳过: 已存在映射")
                    skipped_count += 1
                    continue
            
            # Generate S3 object key
            if prefix:
                object_key = f"{prefix.rstrip('/')}/{img_file.name}"
            else:
                object_key = img_file.name
            
            # Upload file
            url = self.upload_file(str(img_file), object_key)
            
            if url:
                if category not in url_mapping:
                    url_mapping[category] = {}
                url_mapping[category][img_file.name] = url
                
                # Save mapping after each upload (in case of interruption)
                with open(output_mapping, 'w', encoding='utf-8') as f:
                    json.dump(url_mapping, f, ensure_ascii=False, indent=2)
                
                print(f"  ✓ 成功: {url}")
                uploaded_count += 1
            else:
                failed_list.append(img_file.name)
                print(f"  ✗ 失败")
            
            # Delay between uploads
            if idx < len(image_files):
                time.sleep(delay)
        
        print(f"\n{'='*70}")
        print(f"上传完成!")
        print(f"  成功: {uploaded_count}/{len(image_files)}")
        print(f"  跳过: {skipped_count}")
        print(f"  失败: {len(failed_list)}")
        print(f"  映射文件: {output_mapping}")
        print(f"{'='*70}")
        
        if failed_list:
            print(f"\n失败列表:")
            for filename in failed_list[:10]:  # Show first 10
                print(f"  - {filename}")
            if len(failed_list) > 10:
                print(f"  ... and {len(failed_list) - 10} more")
        
        return url_mapping


def main():
    parser = argparse.ArgumentParser(
        description="批量上传景点图片到AWS S3并更新数据库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 上传景点图片（测试10个）
  python scripts/upload_to_s3.py \\
      --image-dir exports/images/all_image \\
      --bucket my-image-bucket-liuyu-cv \\
      --region us-east-1 \\
      --limit 10 \\
      --delay 1.0

  # 上传所有图片
  python scripts/upload_to_s3.py \\
      --image-dir exports/images/all_image \\
      --bucket my-image-bucket-liuyu-cv \\
      --region us-east-1 \\
      --prefix viewpoints \\
      --delay 1.0

AWS凭证配置:
  1. 环境变量:
     export AWS_ACCESS_KEY_ID=your_access_key
     export AWS_SECRET_ACCESS_KEY=your_secret_key
  
  2. AWS配置文件 (~/.aws/credentials):
     [default]
     aws_access_key_id = your_access_key
     aws_secret_access_key = your_secret_key
  
  3. IAM角色（如果在EC2上运行）
        """
    )
    
    parser.add_argument("--image-dir", required=True, 
                       help="图片目录路径（图片文件名格式: {viewpoint_id}.png）")
    parser.add_argument("--bucket", required=True,
                       help="S3 bucket名称（必需）")
    parser.add_argument("--region", default="us-east-1",
                       help="AWS区域（默认: us-east-1）")
    parser.add_argument("--prefix", default="viewpoints",
                       help="S3对象键前缀（默认: viewpoints）")
    parser.add_argument("--limit", type=int, default=None,
                       help="限制上传数量（用于测试，默认: 无限制）")
    parser.add_argument("--delay", type=float, default=1.0,
                       help="上传间隔秒数（默认: 1.0）")
    
    args = parser.parse_args()
    
    if not AWS_AVAILABLE:
        print("Error: AWS SDK (boto3) not available.")
        print("Please install: pip install boto3")
        return
    
    try:
        uploader = S3Uploader(
            bucket_name=args.bucket,
            region=args.region
        )
        
        uploader.batch_upload_viewpoint_images(
            image_dir=args.image_dir,
            prefix=args.prefix,
            limit=args.limit,
            delay=args.delay
        )
    
    except ValueError as e:
        print(f"\nError: {e}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

