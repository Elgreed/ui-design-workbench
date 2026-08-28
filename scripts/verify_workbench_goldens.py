"""Render and compare the approved workbench review-panel golden states."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from quality_common import write_json
from visual_regression import compare_geometry, compare_images


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "golden" / "workbench-review"
CASES = {
    "summary-wide": {
        "section": "summary",
        "view": "single",
        "width": 1440,
        "height": 960,
        "left": "closed",
    },
    "summary-compact": {
        "section": "summary",
        "view": "single",
        "width": 760,
        "height": 900,
        "left": "closed",
    },
    "problems-wide": {
        "section": "problems",
        "view": "single",
        "width": 1440,
        "height": 960,
        "left": "closed",
    },
    "changes-wide": {
        "section": "changes",
        "view": "compare",
        "width": 1440,
        "height": 960,
        "left": "closed",
    },
}


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def capture(case_name: str, case: dict[str, object], workspace: Path, preview: Path) -> tuple[Path, Path]:
    screenshot = workspace / f"{case_name}.png"
    geometry = workspace / f"{case_name}.geometry.json"
    diagnostics = workspace / f"{case_name}.diagnostics.json"
    print(f"Capture {case_name}...", flush=True)
    run(
        [
            "node",
            str(ROOT / "scripts" / "smoke_preview.js"),
            str(preview),
            "--mode",
            "review",
            "--capture-only",
            "--output",
            str(diagnostics),
            "--screenshot",
            str(screenshot),
            "--geometry-output",
            str(geometry),
            "--capture-view",
            str(case["view"]),
            "--capture-screen",
            "overview",
            "--capture-left-panel",
            str(case["left"]),
            "--capture-right-panel",
            "open",
            "--capture-inspector-tab",
            "review",
            "--capture-review-section",
            str(case["section"]),
            "--viewport-width",
            str(case["width"]),
            "--viewport-height",
            str(case["height"]),
        ]
    )
    return screenshot, geometry


def compare(case_name: str, screenshot: Path, geometry: Path, workspace: Path) -> dict[str, object]:
    image = compare_images(str(FIXTURE / f"{case_name}.png"), str(screenshot), 12, str(workspace / f"{case_name}.diff.png"))
    geometry_report = compare_geometry(
        str(FIXTURE / f"{case_name}.geometry.json"),
        str(geometry),
        1.0,
    )
    passed = (
        image.get("status") == "pass"
        and image.get("changedRatio", 1) <= 0.005
        and image.get("meanAbsoluteError", float("inf")) <= 1.0
        and geometry_report.get("status") == "pass"
    )
    return {
        "status": "pass" if passed else "fail",
        "image": image,
        "geometry": geometry_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve", action="store_true", help="Replace approved PNG and geometry baselines")
    parser.add_argument("--case", choices=sorted(CASES), action="append", help="Run only selected state; repeatable")
    parser.add_argument("--output", help="Optional comparison report path")
    args = parser.parse_args()
    selected = args.case or list(CASES)

    with tempfile.TemporaryDirectory(prefix="uidw-golden-") as temporary:
        workspace = Path(temporary)
        preview = workspace / "ui-preview.html"
        run(
            [
                sys.executable,
                str(ROOT / "scripts" / "render_preview.py"),
                str(FIXTURE / "ui-ir.json"),
                "--output",
                str(preview),
                "--allow-draft",
            ]
        )
        reports: dict[str, object] = {}
        for case_name in selected:
            screenshot, geometry = capture(case_name, CASES[case_name], workspace, preview)
            if args.approve:
                shutil.copy2(screenshot, FIXTURE / screenshot.name)
                shutil.copy2(geometry, FIXTURE / geometry.name)
                reports[case_name] = {"status": "approved"}
            else:
                reports[case_name] = compare(case_name, screenshot, geometry, workspace)
                print(f"{case_name}: {reports[case_name]['status']}", flush=True)

        overall = "approved" if args.approve else ("pass" if all(report["status"] == "pass" for report in reports.values()) else "fail")
        result = {"version": 1, "status": overall, "cases": reports}
        if args.output:
            write_json(args.output, result)
        print(f"Workbench goldens: {overall} ({len(selected)} states)", flush=True)
        return 0 if overall in {"approved", "pass"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
