"""Command-line entry point.

Stages 0–4 only: `python code/main.py inspect` validates the inputs, parses all
evidence into an ObservationIndex and prints a coverage summary (counts and file
IDs only, no personal values). No predictions and no output.csv are produced.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit import config                          # noqa: E402
from audit.errors import SchemaError              # noqa: E402
from audit.evidence.extract import build_index    # noqa: E402
from audit.loader import load_dataset             # noqa: E402


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
    index = build_index(ds)
    reports = index.reports
    status = Counter((r.fmt, r.status) for r in reports.values())
    print("extraction status by format:", dict(sorted(status.items())))
    print(f"observations: {len(index)}  resources: {len(index.resources())}  "
          f"coverage units: {sum(len(r.coverage) for r in reports.values())}")
    print("observations by format:", dict(sorted(Counter(o.source_format for o in index.all()).items())))
    for r in sorted(reports.values(), key=lambda r: r.file_id):
        if r.status != "OK" or r.warnings or r.fmt == "pdf":
            print(f"  {r.file_id} {r.fmt} {r.status} pages={len(r.pages)} obs={r.observations} "
                  f"reasons={r.reasons} warnings={r.warnings}")
    print("anomalies:", dict(Counter(a for o in index.all() for a in o.anomalies)))
    owners = Counter(index.owner(rid).basis for rid in index.resources())
    print("owner resolution by basis:", dict(sorted(owners.items())))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ghost Data Still Exists — deletion audit (Stages 0–4)")
    parser.add_argument("command", choices=["inspect"])
    parser.add_argument("--dataset", default=str(config.DATASET_DIR))
    args = parser.parse_args(argv)
    return cmd_inspect(args)


if __name__ == "__main__":
    sys.exit(main())
