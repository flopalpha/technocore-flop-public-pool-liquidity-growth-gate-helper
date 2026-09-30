"""Command line for FLOP pool liquidity-growth gate helper."""

import argparse
from pathlib import Path

import pool_gate


def build_parser():
    p = argparse.ArgumentParser(description="Screen public pool snapshots")
    p.add_argument("input", help="input .csv or .json file")
    p.add_argument("--window", type=float, default=15.0)
    p.add_argument("--min-liquidity", type=float, default=1000.0)
    p.add_argument("--min-delta", type=float, default=100.0)
    p.add_argument("--pass-score", type=float, default=60.0)
    p.add_argument("--review-score", type=float, default=40.0)
    p.add_argument("--top-n", type=int, default=5)
    p.add_argument("--json-out", default="")
    p.add_argument("--md-out", default="")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    snapshots = pool_gate.load_snapshots(args.input)
    report = pool_gate.build_report(
        snapshots,
        window_minutes=args.window,
        min_liquidity=args.min_liquidity,
        min_delta=args.min_delta,
        pass_score=args.pass_score,
        review_score=args.review_score,
        top_n=args.top_n,
    )
    if args.json_out:
        pool_gate.write_json_report(report, args.json_out)
        print("wrote json: " + args.json_out)
    if args.md_out:
        pool_gate.write_markdown_report(report, args.md_out)
        print("wrote markdown: " + args.md_out)
    print("snapshots: " + str(report["snapshot_count"]))
    print("pools: " + str(report["pool_count"]))
    print("checksum: " + str(report["checksum"]))
    comp = report["bucket_comparison"]
    print("note: " + str(comp["note"]))
    print("earliest top: " + ", ".join(comp["earliest_top"]))
    print("weighted top: " + ", ".join(comp["weighted_top"]))
    for item in report["pools"][:args.top_n]:
        line = str(item["pool_id"]) + " score=" + str(item["score"]) + " gate=" + str(item["gate"])
        print(line)
    return report


if __name__ == "__main__":
    main()
