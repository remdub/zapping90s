#!/usr/bin/env python3
"""Normalize audio loudness of all MP4s in static/videos/ to EBU R128 (-23 LUFS)."""
import json
import subprocess
import sys
from pathlib import Path

VIDEOS_DIR = Path(__file__).parent.parent / "static" / "videos"
TARGET_I = -23  # LUFS integrated loudness
TARGET_TP = -1  # dBTP true peak
TARGET_LRA = 7  # LU loudness range


def analyze(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffmpeg", "-i", str(path),
            "-filter:a", f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json",
            "-f", "null", "/dev/null",
        ],
        capture_output=True,
        text=True,
    )
    stderr = result.stderr
    start = stderr.rfind("{")
    end = stderr.rfind("}") + 1
    if start == -1 or end == 0:
        raise RuntimeError(f"No JSON in ffmpeg output:\n{stderr[-500:]}")
    return json.loads(stderr[start:end])


def normalize(input_path: Path, stats: dict, output_path: Path) -> None:
    filter_str = (
        f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}"
        f":measured_I={stats['input_i']}"
        f":measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}"
        f":measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}"
        f":linear=true"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-c:v", "copy",
            "-filter:a", filter_str,
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


def main() -> None:
    videos = sorted(VIDEOS_DIR.glob("*.mp4"))
    total = len(videos)
    print(f"Normalizing {total} videos in {VIDEOS_DIR}")
    errors = []

    for i, video in enumerate(videos, 1):
        tmp = video.with_suffix(".normalized.mp4")
        print(f"[{i}/{total}] {video.name} ...", end=" ", flush=True)
        try:
            stats = analyze(video)
            normalize(video, stats, tmp)
            tmp.replace(video)
            print("ok")
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append(video.name)
            if tmp.exists():
                tmp.unlink()

    if errors:
        print(f"\nFailed ({len(errors)}):", file=sys.stderr)
        for name in errors:
            print(f"  {name}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\nAll {total} videos normalized.")


if __name__ == "__main__":
    main()
