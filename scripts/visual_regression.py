#!/usr/bin/env python3
"""Compare preview screenshots and optional geometry snapshots with explicit tolerances."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the selected workspace runtime
    Image = None

from quality_common import read_json, write_json


def compare_images(baseline_path: str, candidate_path: str, channel_tolerance: int, diff_path: str | None) -> dict[str, Any]:
    baseline = Image.open(baseline_path).convert("RGBA")
    candidate = Image.open(candidate_path).convert("RGBA")
    if baseline.size != candidate.size:
        return {"status": "fail", "baselineSize": list(baseline.size), "candidateSize": list(candidate.size), "reason": "image-size-mismatch"}

    total = baseline.width * baseline.height
    changed = 0
    absolute_sum = 0
    maximum = 0
    bounds = [baseline.width, baseline.height, -1, -1]
    overlay = Image.new("RGBA", baseline.size, (0, 0, 0, 0)) if diff_path else None
    overlay_pixels = overlay.load() if overlay else None

    baseline_data = baseline.get_flattened_data() if hasattr(baseline, "get_flattened_data") else baseline.getdata()
    candidate_data = candidate.get_flattened_data() if hasattr(candidate, "get_flattened_data") else candidate.getdata()
    for index, (before, after) in enumerate(zip(baseline_data, candidate_data)):
        differences = tuple(abs(int(before[channel]) - int(after[channel])) for channel in range(4))
        pixel_max = max(differences)
        absolute_sum += sum(differences)
        maximum = max(maximum, pixel_max)
        if pixel_max <= channel_tolerance:
            continue
        changed += 1
        x = index % baseline.width
        y = index // baseline.width
        bounds[0] = min(bounds[0], x)
        bounds[1] = min(bounds[1], y)
        bounds[2] = max(bounds[2], x)
        bounds[3] = max(bounds[3], y)
        if overlay_pixels is not None:
            overlay_pixels[x, y] = (239, 68, 68, 220)

    if overlay and diff_path:
        target = Path(diff_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        highlighted = candidate.copy()
        highlighted.alpha_composite(overlay)
        highlighted.save(target)

    return {
        "status": "pass",
        "baselineSize": list(baseline.size),
        "candidateSize": list(candidate.size),
        "channelTolerance": channel_tolerance,
        "changedPixels": changed,
        "changedRatio": round(changed / total, 8) if total else 0,
        "meanAbsoluteError": round(absolute_sum / (total * 4), 5) if total else 0,
        "maximumChannelError": maximum,
        "changedBounds": None if changed == 0 else bounds,
    }


def compare_geometry(baseline_path: str, candidate_path: str, tolerance: float) -> dict[str, Any]:
    baseline = read_json(baseline_path)
    candidate = read_json(candidate_path)
    before = baseline.get("elements", {})
    after = candidate.get("elements", {})
    missing = sorted(set(before) - set(after))
    unexpected = sorted(set(after) - set(before))
    changes: list[dict[str, Any]] = []
    for key in sorted(set(before) & set(after)):
        first, second = before[key], after[key]
        if first is None or second is None:
            if first != second:
                changes.append({"element": key, "field": "presence", "before": first, "after": second})
            continue
        for field in ("x", "y", "width", "height"):
            a, b = first.get(field), second.get(field)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.fabs(a - b) > tolerance:
                changes.append({"element": key, "field": field, "before": a, "after": b, "delta": round(b - a, 3)})
        for field in ("visible", "overflowX", "overflowY"):
            if first.get(field) != second.get(field):
                changes.append({"element": key, "field": field, "before": first.get(field), "after": second.get(field)})
    overlaps = candidate.get("overlaps", [])
    return {
        "status": "fail" if missing or unexpected or changes or overlaps else "pass",
        "toleranceCssPx": tolerance,
        "missingElements": missing,
        "unexpectedElements": unexpected,
        "changes": changes,
        "candidateOverlaps": overlaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Approved PNG screenshot")
    parser.add_argument("--candidate", required=True, help="Candidate PNG screenshot")
    parser.add_argument("--output", required=True, help="Path for visual-regression.json")
    parser.add_argument("--diff-image", help="Optional highlighted PNG output")
    parser.add_argument("--baseline-geometry", help="Approved geometry JSON from smoke_preview.js")
    parser.add_argument("--candidate-geometry", help="Candidate geometry JSON from smoke_preview.js")
    parser.add_argument("--channel-tolerance", type=int, default=12)
    parser.add_argument("--max-changed-ratio", type=float, default=.005)
    parser.add_argument("--max-mean-error", type=float, default=1.0)
    parser.add_argument("--geometry-tolerance", type=float, default=1.0)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when thresholds fail")
    args = parser.parse_args()
    if Image is None:
        parser.error("Pillow is required for pixel comparison; use a workspace Python runtime that provides PIL.")
    if bool(args.baseline_geometry) != bool(args.candidate_geometry):
        parser.error("Provide both --baseline-geometry and --candidate-geometry")

    image_report = compare_images(args.baseline, args.candidate, max(0, args.channel_tolerance), args.diff_image)
    image_pass = image_report.get("status") == "pass" and image_report.get("changedRatio", 1) <= args.max_changed_ratio and image_report.get("meanAbsoluteError", float("inf")) <= args.max_mean_error
    geometry_report = compare_geometry(args.baseline_geometry, args.candidate_geometry, max(0, args.geometry_tolerance)) if args.baseline_geometry else None
    geometry_pass = geometry_report is None or geometry_report.get("status") == "pass"
    report = {
        "version": 1,
        "status": "pass" if image_pass and geometry_pass else "fail",
        "thresholds": {"maxChangedRatio": args.max_changed_ratio, "maxMeanAbsoluteError": args.max_mean_error, "geometryToleranceCssPx": args.geometry_tolerance},
        "image": image_report,
        "geometry": geometry_report,
    }
    write_json(args.output, report)
    print(f"Visual regression: {report['status']} | changed={image_report.get('changedRatio', 1):.4%}")
    return 2 if args.strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    sys.exit(main())
