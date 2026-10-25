"""Evidence extraction dispatcher (M2, Stages 2–3).

PDF (Stage 4) and PNG (media cache, Stage 4/12) are not parsed yet. They are
reported as FAILED coverage gaps, never as empty files (B.3.2).
"""
from .. import config
from ..models import FileExtraction
from .json_parser import parse_json
from .log_parser import parse_log
from .sql_parser import parse_sql
from .text_parser import parse_text


def extract_file(manifest_row):
    suffix = manifest_row["_path"].suffix.lower()
    if suffix == ".sql":
        return parse_sql(manifest_row)
    if suffix == ".json":
        return parse_json(manifest_row)
    if suffix == ".log":
        return parse_log(manifest_row)
    if suffix == ".txt":
        return parse_text(manifest_row)
    rep = FileExtraction(file_id=manifest_row["file_id"], path=manifest_row["file_path"],
                         fmt=suffix.lstrip("."), status="FAILED")
    if suffix == ".pdf":
        rep.reasons.append("PDF extractor not implemented until Stage 4 (EVIDENCE_GAP)")
    elif suffix == ".png":
        reason = "no verified media-cache entry (EVIDENCE_GAP)"
        if not config.MEDIA_TRANSMISSION_AUTHORIZED:
            reason += "; screenshot transmission not authorized (A.8.1 Q-MEDIA-PROVIDER)"
        rep.reasons.append(reason)
    else:
        rep.reasons.append(f"unsupported evidence format {suffix!r}")
    return [], rep


def extract_all(dataset):
    observations, reports = [], {}
    for row in sorted(dataset.manifest, key=lambda r: r["file_id"]):
        obs, rep = extract_file(row)
        observations.extend(obs)
        reports[row["file_id"]] = rep
    return observations, reports
