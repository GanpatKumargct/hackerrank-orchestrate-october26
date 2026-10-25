"""SQL snapshot parser (plan C.1). Each file runs in a fresh in-memory SQLite DB.

Shapes: inventory (snapshot_scope + typed tables, SYSTEM-level coverage),
topology extracts (record_json rows, no coverage), direct tables (COLLECTION-level
coverage). Observation time for SQL rows is the file capture (time_basis="file").
"""
import json
import re
import sqlite3

from .. import config
from ..models import CoverageUnit, FileExtraction
from .common import make_observation
from .normalize import flatten

HEADER_TIME = re.compile(r"^--\s*(?:Captured at:\s*|snapshot_completed_at=)(\S+)", re.M)


def _rows(con, table):
    cur = con.execute(f'SELECT * FROM "{table}"')
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def parse_sql(manifest_row):
    path = manifest_row["_path"]
    fid = manifest_row["file_id"]
    rep = FileExtraction(file_id=fid, path=manifest_row["file_path"], fmt="sql")
    obs = []
    try:
        text = path.read_text(encoding="utf-8")
        con = sqlite3.connect(":memory:")
        con.executescript(text)
    except (sqlite3.Error, UnicodeDecodeError, OSError) as exc:
        rep.status = "FAILED"
        rep.reasons.append(f"sql load error: {exc}")
        return [], rep

    m = HEADER_TIME.search(text)
    if not m:
        rep.warnings.append("no capture-time header")
    elif m.group(1) != manifest_row["captured_at"]:
        rep.warnings.append(f"header capture {m.group(1)} != manifest {manifest_row['captured_at']}")

    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    scope = set()
    if "snapshot_scope" in tables:
        scope = {r["origin_system"] for r in _rows(con, "snapshot_scope")}

    for table in tables:
        if table == "snapshot_scope":
            continue
        rows = _rows(con, table)
        if table in config.INVENTORY_TABLES:
            system = config.INVENTORY_TABLES[table]
            for i, row in enumerate(rows):
                obs.append(make_observation(
                    manifest_row=manifest_row, fmt="sql", locator=f"{table}[{i}]",
                    resource_id=row["resource_id"], fields=row, system_id=system,
                    system_field="table", collection=table, copy_location="primary"))
            if system in scope:
                rep.coverage.append(CoverageUnit(
                    file_id=fid, level="SYSTEM", system=system, collection=table, copy="primary",
                    observed_raw=None, resource_ids=frozenset(r["resource_id"] for r in rows),
                    locator=f"snapshot_scope:{system}/{table}"))
        elif table in config.DIRECT_TABLES:
            system, collection, copy = config.DIRECT_TABLES[table]
            for i, row in enumerate(rows):
                related = ()
                if row.get("source_resource_id"):
                    related = (("DERIVED_FROM", row["source_resource_id"]),)
                obs.append(make_observation(
                    manifest_row=manifest_row, fmt="sql", locator=f"{table}[{i}]",
                    resource_id=row["resource_id"], fields=row, system_id=system,
                    system_field="table", collection=collection, copy_location=copy,
                    related_ids=related))
            rep.coverage.append(CoverageUnit(
                file_id=fid, level="COLLECTION", system=system, collection=collection, copy=copy,
                observed_raw=None, resource_ids=frozenset(r["resource_id"] for r in rows),
                locator=f"table:{table}"))
        elif table.startswith(config.TOPOLOGY_TABLE_PREFIX) and rows and "record_json" in rows[0]:
            copy = table[len(config.TOPOLOGY_TABLE_PREFIX):]
            for i, row in enumerate(rows):
                try:
                    record = json.loads(row["record_json"])
                except (TypeError, ValueError):
                    rep.unparsed_units += 1
                    rep.unparsed_samples.append(f"{table}[{i}] record_json not JSON")
                    continue
                fields = flatten(record)
                fields["_row.updated_at"] = row.get("updated_at")
                obs.append(make_observation(
                    manifest_row=manifest_row, fmt="sql", locator=f"{table}[{i}]",
                    resource_id=row["resource_id"], fields=fields,
                    system_id=row.get("origin_system"), system_field="origin_system",
                    collection=row.get("collection_name"), copy_location=copy))
        elif rows and "resource_id" in rows[0]:
            rep.reasons.append(f"unknown table shape {table!r}: parsed generically without owner")
            for i, row in enumerate(rows):
                obs.append(make_observation(
                    manifest_row=manifest_row, fmt="sql", locator=f"{table}[{i}]",
                    resource_id=row["resource_id"], fields=row, collection=table))
        elif rows:
            rep.unparsed_units += len(rows)
            rep.unparsed_samples.append(f"table {table!r} has no resource_id column")
    con.close()
    rep.observations = len(obs)
    return obs, rep.finalize()
