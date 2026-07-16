"""CLI entry point for the Chapter 7 quantitative-analysis report.

Runs the existing RL redesign pipeline on an as-is process JSON file, then
runs the full quantitative-analysis suite (flow analysis, CTE, cost, and
resource-utilization/Little's Law) on the as-is and RL-generated to-be
graphs, and writes both a Markdown report and the contract-shaped JSON to
disk.

Usage:
    python report.py app/data/asIsProcess.json
    python report.py app/data/asIsProcess.json --out-dir out --seed 42
"""

import argparse
import json
import sys
from pathlib import Path

from app.core.quantitative_analysis import compare, to_markdown


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("as_is_path", help="Path to the as-is process JSON file.")
    parser.add_argument(
        "--out-dir", default=".", help="Directory to write the report files into (default: current directory)."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for the RL redesign search, for a reproducible to-be process (default: 42). "
        "Pass -1 for fully stochastic (unseeded) behavior.",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Base filename for the output files (default: derived from process_code, falls back to the input filename).",
    )
    args = parser.parse_args(argv)

    seed = None if args.seed == -1 else args.seed

    try:
        report = compare(args.as_is_path, seed=seed)
    except FileNotFoundError:
        print(f"error: no such file: {args.as_is_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = args.name or report.get("process_code") or Path(args.as_is_path).stem

    json_path = out_dir / f"{base_name}_analysis.json"
    md_path = out_dir / f"{base_name}_report.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")

    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
