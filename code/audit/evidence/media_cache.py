"""Local media-cache reader (plan B.1.3). Read-only; never calls any API.

A PNG becomes observations only through a cache entry `<cache_dir>/<file_id>.json`
whose image SHA-256, prompt SHA-256 and schema version all verify. Anything else is
a FAILED extraction (EVIDENCE_GAP) with the reason — never an empty file.
Generating cache entries is a separate, explicitly authorized tool (Stage 12).
"""
import hashlib
import json
from pathlib import Path

from .. import config
from ..models import FileExtraction
from .common import make_observation
from .normalize import flatten

REQUIRED_KEYS = ("file_id", "sha256", "prompt_sha256", "extractor", "extracted_at",
                 "schema_version", "records")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_png(manifest_row, cache_dir=None, prompt_path=None):
    fid = manifest_row["file_id"]
    rep = FileExtraction(file_id=fid, path=manifest_row["file_path"], fmt="png")
    cache_dir = Path(cache_dir or config.MEDIA_CACHE_DIR)
    prompt_path = Path(prompt_path or config.MEDIA_PROMPT_PATH)
    entry_path = cache_dir / f"{fid}.json"

    def fail(reason):
        rep.status = "FAILED"
        msg = f"{reason} (EVIDENCE_GAP)"
        if not config.MEDIA_TRANSMISSION_AUTHORIZED:
            msg += "; screenshot transmission not authorized (A.8.1 Q-MEDIA-PROVIDER)"
        rep.reasons.append(msg)
        return [], rep

    if not entry_path.is_file():
        return fail("no media-cache entry")
    try:
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return fail(f"media-cache entry unreadable: {exc}")
    missing = [k for k in REQUIRED_KEYS if k not in entry]
    if missing:
        return fail(f"media-cache entry missing keys {missing}")
    if entry["file_id"] != fid:
        return fail("media-cache entry file_id mismatch")
    if str(entry["schema_version"]) not in config.MEDIA_SCHEMA_VERSIONS:
        return fail(f"unsupported media-cache schema_version {entry['schema_version']!r}")
    if entry["sha256"] != _sha256(manifest_row["_path"]):
        return fail("image SHA-256 does not match media-cache entry")
    if not prompt_path.is_file():
        return fail("extraction prompt file missing; prompt hash cannot be verified")
    if entry["prompt_sha256"] != _sha256(prompt_path):
        return fail("prompt SHA-256 does not match media-cache entry")
    if not isinstance(entry["records"], list):
        return fail("media-cache records is not a list")

    obs = []
    for i, rec in enumerate(entry["records"]):
        if not isinstance(rec, dict) or not isinstance(rec.get("resource_id"), str):
            rep.unparsed_units += 1
            rep.unparsed_samples.append(f"records[{i}] has no resource_id")
            continue
        fields = flatten({k: v for k, v in rec.items() if k not in ("resource_id", "observed_at")})
        obs.append(make_observation(
            manifest_row=manifest_row, fmt="image", locator=f"cache:{fid}#records[{i}]",
            resource_id=rec["resource_id"], fields=fields, observed_raw=rec.get("observed_at"),
            context={"origin": manifest_row.get("origin"), "extractor": entry["extractor"],
                     "extracted_at": entry["extracted_at"], "review_status": entry.get("review_status"),
                     "cache_entry": entry_path.name}))
    rep.observations = len(obs)
    return obs, rep.finalize()
