"""Evidence extraction dispatcher (M2, Stages 2–4).

PNG evidence is read only from the local, hash-verified media cache; without a
valid entry it is a FAILED coverage gap, never an empty file (B.3.2).
"""
from ..models import FileExtraction
from .index import ObservationIndex
from .json_parser import parse_json
from .log_parser import parse_log
from .media_cache import parse_png
from .pdf_parser import parse_pdf
from .sql_parser import parse_sql
from .text_parser import parse_text


def extract_file(manifest_row, media_cache_dir=None, media_prompt_path=None):
    suffix = manifest_row["_path"].suffix.lower()
    if suffix == ".sql":
        return parse_sql(manifest_row)
    if suffix == ".json":
        return parse_json(manifest_row)
    if suffix == ".log":
        return parse_log(manifest_row)
    if suffix == ".txt":
        return parse_text(manifest_row)
    if suffix == ".pdf":
        return parse_pdf(manifest_row)
    if suffix == ".png":
        return parse_png(manifest_row, media_cache_dir, media_prompt_path)
    rep = FileExtraction(file_id=manifest_row["file_id"], path=manifest_row["file_path"],
                         fmt=suffix.lstrip("."), status="FAILED")
    rep.reasons.append(f"unsupported evidence format {suffix!r} (EVIDENCE_GAP)")
    return [], rep


def extract_all(dataset, media_cache_dir=None, media_prompt_path=None):
    observations, reports = [], {}
    for row in sorted(dataset.manifest, key=lambda r: r["file_id"]):
        obs, rep = extract_file(row, media_cache_dir, media_prompt_path)
        observations.extend(obs)
        reports[row["file_id"]] = rep
    return observations, reports


def build_index(dataset, media_cache_dir=None, media_prompt_path=None):
    observations, reports = extract_all(dataset, media_cache_dir, media_prompt_path)
    return ObservationIndex(observations, reports)
