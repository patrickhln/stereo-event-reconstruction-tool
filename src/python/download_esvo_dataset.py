#!/usr/bin/env python3
import sys
import os
import subprocess
import shutil
import gdown

# mapping of profiles to Google Drive Folder IDs
DATASET_IDS = {
    "rpg": "14WKGDGSLVqQYX2hrxrPvOrfOh6n2R1FM",
    "upenn": "1FbABakLVcWAGsA7E5CN11vVovdWQfDEx",
    "hkust": "1LCeM_rlw2LIDN147tulZn52MHJMp1WtX"
}

def download_dataset(profile, output_dir):
    if profile not in DATASET_IDS:
        print(f"Error: Unknown profile '{profile}'. Available: {list(DATASET_IDS.keys())}")
        sys.exit(1)

    folder_id = DATASET_IDS[profile]
    url = f'https://drive.google.com/drive/folders/{folder_id}'
    
    print(f"Downloading {profile} dataset from {url}...")
    print(f"Output directory: {output_dir}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    gdown.download_folder(url, output=output_dir, quiet=False, remaining_ok=True)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 download_esvo_dataset.py <profile> <output_dir>")
        sys.exit(1)

    profile = sys.argv[1]
    output_dir = sys.argv[2]
    
    download_dataset(profile, output_dir)
