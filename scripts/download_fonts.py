#!/usr/bin/env python3
"""
Download Inter fonts for MoatDaily templates.
One-time setup script. Downloads from official Inter GitHub release.
"""

import io
import zipfile
import requests
from pathlib import Path


RELEASE_URL = "https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip"

# Files we need from the zip (they're inside Inter-4.1/extras/ttf/ or similar)
NEEDED = {
    "Inter-Black.ttf": ["InterDisplay-Black.ttf", "Inter-Black.ttf"],
    "Inter-Bold.ttf": ["InterDisplay-Bold.ttf", "Inter-Bold.ttf"],
    "Inter-Regular.ttf": ["InterDisplay-Regular.ttf", "Inter-Regular.ttf"],
}


def main():
    root = Path(__file__).parent.parent
    fonts_dir = root / "templates" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded
    all_exist = all((fonts_dir / f).exists() for f in NEEDED)
    if all_exist:
        print("✅ All fonts already downloaded")
        return

    print(f"⬇ Downloading Inter font pack from GitHub release...")
    try:
        resp = requests.get(RELEASE_URL, timeout=60, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Download failed: {e}")
        print("   Falling back to system fonts - posts will still render.")
        return

    print(f"  📦 Downloaded {len(resp.content) // 1024}KB, extracting...")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # List all TTF files in the zip
        ttf_files = {Path(n).name: n for n in zf.namelist() if n.endswith(".ttf")}

        for target_name, search_names in NEEDED.items():
            dest = fonts_dir / target_name
            if dest.exists():
                print(f"  ✓ {target_name} already exists")
                continue

            found = False
            for search in search_names:
                if search in ttf_files:
                    data = zf.read(ttf_files[search])
                    dest.write_bytes(data)
                    print(f"  ✅ {target_name} ← {search} ({len(data)//1024}KB)")
                    found = True
                    break

            if not found:
                # Try partial match
                for zip_name, zip_path in ttf_files.items():
                    key = target_name.replace("Inter-", "").replace(".ttf", "").lower()
                    if key in zip_name.lower():
                        data = zf.read(zip_path)
                        dest.write_bytes(data)
                        print(f"  ✅ {target_name} ← {zip_name} ({len(data)//1024}KB)")
                        found = True
                        break

            if not found:
                print(f"  ⚠️  {target_name} not found in zip. Available: {list(ttf_files.keys())[:10]}")

    print(f"\nFonts directory: {fonts_dir}")


if __name__ == "__main__":
    main()
