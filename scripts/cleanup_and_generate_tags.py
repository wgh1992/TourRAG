#!/usr/bin/env python3
"""
Complete workflow: Generate tags for all viewpoints, then cleanup incomplete ones

This script:
1. Generates visual tags for viewpoints missing tags (using gpt-4o-mini)
2. Cleans up viewpoints that still don't have history or tags
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    """Main workflow"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate tags and cleanup incomplete viewpoints')
    parser.add_argument('--generate-tags', action='store_true',
                       help='Generate visual tags first')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit number of viewpoints to process for tag generation')
    parser.add_argument('--cleanup', action='store_true',
                       help='Clean up incomplete viewpoints after tag generation')
    parser.add_argument('--execute', action='store_true',
                       help='Actually delete viewpoints (default is dry-run)')
    parser.add_argument('--require-history-only', action='store_true',
                       help='Only require history, not tags')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Complete Workflow: Generate Tags & Cleanup")
    print("=" * 60)
    
    # Step 1: Generate tags if requested
    if args.generate_tags:
        print("\n" + "=" * 60)
        print("Step 1: Generating Visual Tags")
        print("=" * 60)
        
        cmd = ["python", "scripts/generate_visual_tags_from_wiki.py"]
        if args.limit:
            cmd.extend(["--limit", str(args.limit)])
        
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)
        
        if result.returncode != 0:
            print("⚠️  Tag generation had errors, but continuing...")
    else:
        print("\n⏭️  Skipping tag generation (use --generate-tags to enable)")
    
    # Step 2: Cleanup if requested
    if args.cleanup:
        print("\n" + "=" * 60)
        print("Step 2: Cleaning Up Incomplete Viewpoints")
        print("=" * 60)
        
        cmd = ["python", "scripts/cleanup_incomplete_viewpoints.py"]
        if args.execute:
            cmd.append("--execute")
        if args.require_history_only:
            cmd.append("--require-history-only")
        
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)
        
        if result.returncode != 0:
            print("⚠️  Cleanup had errors")
    else:
        print("\n⏭️  Skipping cleanup (use --cleanup to enable)")
    
    # Final status
    print("\n" + "=" * 60)
    print("Final Status Check")
    print("=" * 60)
    
    result = subprocess.run(
        ["python", "scripts/ensure_complete_data.py"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True
    )
    print(result.stdout)
    
    print("=" * 60)


if __name__ == "__main__":
    main()

