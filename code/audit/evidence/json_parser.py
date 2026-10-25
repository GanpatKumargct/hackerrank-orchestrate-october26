"""JSON evidence parser (plan C.1).

A recursive walker emits one Observation per dict that carries a `resource_id`,
inheriting context (snapshot captured_at, data_store, collection, service export
keys) from its ancestors. Nested dicts that are themselves records (e.g. search
hits) become separate observations and keep the parent query as a QUERY_KEY.
Bundle snapshot entries declare COLLECTION-level coverage (C.8.1).
"""
import json

from .. import config
from ..models import CoverageUnit, FileExtraction, IdentifierHit
from .common import make_observation
from .normalize import classify_value, flatten


def _is_record(d):
    return isinstance(d, dict) and isinstance(d.get("resource_id"), str)


def _path_str(path):
    out = ""
    for p in path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else p)
    return out or "$"


def parse_json(manifest_row):
    fid = manifest_row["file_id"]
    rep = FileExtraction(file_id=fid, path=manifest_row["file_path"], fmt="json")
    try:
        doc = json.loads(manifest_row["_path"].read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        rep.status = "FAILED"
        rep.reasons.append(f"json load error: {exc}")
        return [], rep
    obs = []

    def emit(node, ctx, path):
        locator = _path_str(path)
        fields = flatten(node, stop=_is_record)
        # own time > parent record's time (nested hits were observed by the parent query)
        # > enclosing snapshot capture; never the file capture (that is time_basis="file")
        observed_raw = (node.get("observed_at") or node.get("recorded_at")
                        or ctx.get("parent_observed") or ctx.get("captured_at"))
        if node.get("system"):
            system, system_field = node["system"], "system"
        elif ctx.get("service"):
            system, system_field = ctx["service"], "service_exports"
        elif ctx.get("data_store"):
            system, system_field = ctx["data_store"], "data_store"
        elif ctx.get("collection") in config.COLLECTION_OWNERS:
            system, system_field = config.COLLECTION_OWNERS[ctx["collection"]], "collection"
        else:
            system, system_field = None, None
        context = {k: v for k, v in ctx.items() if k in ("data_store", "collection", "service",
                                                          "parent_resource", "parent_query",
                                                          "captured_at")}
        extra = ()
        if ctx.get("parent_query"):
            c = classify_value(ctx["parent_query"])
            if c:
                extra = (IdentifierHit(c[0], ctx["parent_query"], c[1], "parent.query",
                                       "QUERY_KEY", locator),)
        obs.append(make_observation(
            manifest_row=manifest_row, fmt="json", locator=locator,
            resource_id=node["resource_id"], fields=fields, observed_raw=observed_raw,
            system_id=system, system_field=system_field,
            record_type=node.get("record_type"),
            collection=ctx.get("collection"), copy_location="primary",
            context=context, extra_keys=extra))

    def walk(node, ctx, path):
        if isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, ctx, path + [i])
            return
        if not isinstance(node, dict):
            return
        c = dict(ctx)
        if isinstance(node.get("captured_at"), str):
            c["captured_at"] = node["captured_at"]
        for k in ("data_store", "collection"):
            if isinstance(node.get(k), str):
                c[k] = node[k]
        if len(path) >= 3 and path[0] == "service_exports" and isinstance(path[1], str) \
                and isinstance(path[2], str):
            c["service"], c["collection"] = path[1], path[2]
        if {"data_store", "collection", "records"} <= set(node) and isinstance(node["records"], list):
            rep.coverage.append(CoverageUnit(
                file_id=fid, level="COLLECTION", system=node["data_store"],
                collection=node["collection"], copy="primary",
                observed_raw=node.get("captured_at"),
                resource_ids=frozenset(r["resource_id"] for r in node["records"] if _is_record(r)),
                locator=_path_str(path)))
        if _is_record(node):
            emit(node, c, path)
            child = dict(c, parent_resource=node["resource_id"])
            parent_time = node.get("observed_at") or node.get("recorded_at")
            if isinstance(parent_time, str):
                child["parent_observed"] = parent_time
            if isinstance(node.get("query"), str):
                child["parent_query"] = node["query"]
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    walk(v, child, path + [k])
            return
        for k, v in node.items():
            walk(v, c, path + [k])

    walk(doc, {}, [])
    rep.observations = len(obs)
    if not obs and not rep.coverage:
        rep.unparsed_units += 1
        rep.unparsed_samples.append("no record with resource_id found")
    return obs, rep.finalize()
