"""Shared helpers for building Observations with preserved provenance (C.2)."""
from ..models import Observation
from ..timeutil import try_parse_ts
from . import normalize
from .. import config


def make_observation(*, manifest_row, fmt, locator, resource_id, fields, observed_raw=None,
                     system_id=None, system_field=None, reporter_service=None,
                     record_type=None, collection=None, copy_location=None, context=None,
                     extra_keys=(), related_ids=()):
    file_id = manifest_row["file_id"]
    captured = manifest_row["_captured_at"]
    observed = try_parse_ts(observed_raw) if observed_raw else None
    anomalies = []
    if observed_raw and observed is None:
        anomalies.append("unparsed_inner_time")
    if observed is not None and observed > captured:
        anomalies.append("observed_after_capture")
    fields = dict(fields)
    identifiers = normalize.identifier_hits(fields, locator)
    keys = normalize.key_hits(fields, locator, config.TRACE_KEY_FIELDS, "TRACE_KEY")
    keys += normalize.key_hits(fields, locator, config.QUERY_KEY_FIELDS, "QUERY_KEY")
    keys += tuple(extra_keys)
    return Observation(
        obs_id=f"{file_id}#{locator}",
        file_id=file_id,
        file_captured_at=captured,
        file_captured_raw=manifest_row["captured_at"],
        observed_at=observed,
        observed_raw=observed_raw,
        time_basis="inner" if observed is not None else "file",
        source_format=fmt,
        locator=locator,
        resource_id=resource_id,
        system_id=system_id,
        system_field=system_field,
        reporter_service=reporter_service,
        record_type=record_type,
        collection=collection,
        copy_location=copy_location,
        fields=fields,
        context=dict(context or {}),
        identifiers=identifiers,
        keys=keys,
        related_ids=tuple(related_ids),
        anomalies=tuple(anomalies),
    )
