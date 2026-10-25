"""Plain-text handover parser (plan C.1).

Rows look like: `- TS | system | resource_id | record_type | result | subject`.
The subject column may be an identifier or a literal such as "no direct identifier";
it is kept raw in `fields["subject"]`.
"""
import re

from ..models import FileExtraction
from ..timeutil import TS_PATTERN
from .common import make_observation

ROW = re.compile(rf"^-\s*({TS_PATTERN})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*$")


def parse_text(manifest_row):
    fid = manifest_row["file_id"]
    rep = FileExtraction(file_id=fid, path=manifest_row["file_path"], fmt="text")
    try:
        lines = manifest_row["_path"].read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError) as exc:
        rep.status = "FAILED"
        rep.reasons.append(f"text read error: {exc}")
        return [], rep
    obs = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        m = ROW.match(line)
        if not m:
            if line.lstrip().startswith("-"):
                rep.unparsed_units += 1
                rep.unparsed_samples.append(f"line {n}: row not in expected shape")
            else:
                rep.noise_units += 1          # titles, headings, snapshot line
            continue
        ts, system, rid, rtype, result, subject = m.groups()
        fields = {"system": system, "resource_id": rid, "record_type": rtype,
                  "result": result, "subject": subject}
        obs.append(make_observation(
            manifest_row=manifest_row, fmt="text", locator=f"line{n}", resource_id=rid,
            fields=fields, observed_raw=ts, system_id=system, system_field="system",
            record_type=rtype))
    rep.observations = len(obs)
    return obs, rep.finalize()
