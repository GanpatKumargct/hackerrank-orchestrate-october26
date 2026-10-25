"""Command-line entry point.

Stages 0–3 only: `python code/main.py inspect` loads and validates the inputs and
parses evidence, printing a coverage summary (counts only, no personal values).
No predictions and no output.csv are produced at this stage.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit import config                      # noqa: E402
from audit.errors import SchemaError          # noqa: E402
from audit.evidence.extract import extract_all  # noqa: E402
from audit.loader import load_dataset         # noqa: E402


def cmd_inspect(args):
    try:
        ds = load_dataset(args.dataset)
    except SchemaError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"inputs: requests={len(ds.requests)} sample_requests={len(ds.sample_requests)} "
          f"identities={len(ds.identities)} audit_log={len(ds.audit_log)} "
          f"activities={len(ds.activities)} rules={len(ds.rules)} evidence_files={len(ds.manifest)}")
    print(f"loader warnings: {len(ds.warnings)}")
    observations, reports = extract_all(ds)
    status = Counter((r.fmt, r.status) for r in reports.values())
    print("extraction status by format:", dict(sorted(status.items())))
    print(f"observations: {len(observations)}  coverage units: {sum(len(r.coverage) for r in reports.values())}")
    for r in sorted(reports.values(), key=lambda r: r.file_id):
        if r.status != "OK" or r.warnings:
            print(f"  {r.file_id} {r.fmt} {r.status} reasons={r.reasons} warnings={r.warnings} "
                  f"unparsed={r.unparsed_units}")
    anomalies = Counter(a for o in observations for a in o.anomalies)
    print("anomalies:", dict(anomalies))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists — deletion audit (Stages 0–3)")
    parser.add_argument("command", choices=["inspect"])
    parser.add_argument("--dataset", default=str(config.DATASET_DIR))
    args = parser.parse_args(argv)
    return cmd_inspect(args)


if __name__ == "__main__":
    sys.exit(main())
