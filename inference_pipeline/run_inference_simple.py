#!/usr/bin/env python3
"""
Minimal wrapper around inference_final.py.

Defaults:
  Input:  vids/hog_2_6_start.mp4
  Video:  outputs/preprocessed/<stem>_processed.mp4
  JSON:   outputs/tracks/<stem>_tracks.json

Usage:
  python3 run_inference_simple.py
  python3 run_inference_simple.py vids/my_other_clip.mp4
  python3 run_inference_simple.py vids/foo.mp4 --model_path finetuned_clash.pt
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = Path(__file__).resolve().parent
DEFAULT_VIDEO = REPO_ROOT / "vids" / "hog_2_6_start.mp4"
OUTPUT_DIR = REPO_ROOT / "outputs" / "preprocessed"
JSON_DIR = REPO_ROOT / "outputs" / "tracks"
DEFAULT_MODEL = REPO_ROOT / "clash_yolo_4_13.pt"
INFERENCE_SCRIPT = PIPELINE_DIR / "inference_final.py"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run inference with fixed output folders.")
    parser.add_argument(
        "input_video",
        nargs="?",
        default=str(DEFAULT_VIDEO),
        help=f"Raw input .mp4 (default: {DEFAULT_VIDEO.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--model_path",
        default=str(DEFAULT_MODEL),
        help=f"YOLO weights (default: {DEFAULT_MODEL.name})",
    )
    args = parser.parse_args()

    input_path = Path(args.input_video).expanduser().resolve()
    if not input_path.is_file():
        sys.exit(f"Input video not found: {input_path}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    stem = input_path.stem
    processed_mp4 = OUTPUT_DIR / f"{stem}_processed.mp4"
    tracks_json = JSON_DIR / f"{stem}_tracks.json"

    cmd = [
        sys.executable,
        str(INFERENCE_SCRIPT),
        str(input_path),
        str(processed_mp4),
        str(tracks_json),
        "--model_path",
        str(Path(args.model_path).expanduser().resolve()),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print("\nDone.")
    print(f"  Processed video: {processed_mp4}")
    print(f"  Tracks JSON:     {tracks_json}")


if __name__ == "__main__":
    main()
