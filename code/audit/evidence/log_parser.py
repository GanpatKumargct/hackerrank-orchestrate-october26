"""Log parser (plan C.1): seven line shapes, trace grouping, trace keys.

Shapes (all start with an ISO-8601 Z timestamp):
  kv       TS level=L service=S k=v ...
  kvinfo   TS LEVEL service=S k=v ...
  json     TS {"severity": ..., "service": ..., ...}
  syslog   TS <pri>1 host service trace - - k="v" ...
  cloud    TS requestId=T level=L function=S message="k=\"v\" ..."
  pipe     TS | LEVEL | service | trace | event | k="v" ...
  bracket  TS [LEVEL] [service] [trace] event: k="v" ...

A state-bearing line (has resource_id, event not *_started, not noise) becomes one
Observation timed at that line. Identifier-shaped values of lookup/subject/match/
scan/correlation keys anywhere in the same trace are attached as TRACE_KEY hits.
Log level words carry no state.
"""
import json
import re

from .. import config
from ..models import FileExtraction
from ..timeutil import TS_PATTERN
from .common import make_observation
from .normalize import classify_value
from ..models import IdentifierHit

KV = re.compile(r'([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|\S+)')
SHAPES = [
    ("syslog", re.compile(rf"^({TS_PATTERN}) <\d+>1 (\S+) (\S+) (\S+) - - (.*)$")),
    ("cloud", re.compile(rf"^({TS_PATTERN}) (requestId=.*)$")),
    ("pipe", re.compile(rf"^({TS_PATTERN}) \| (\w+) \| (\S+) \| (\S+) \| (\S+) \| ?(.*)$")),
    ("bracket", re.compile(rf"^({TS_PATTERN}) \[(\w+)\] \[(\S+)\] \[(\S+)\] (\S+?): ?(.*)$")),
    ("json", re.compile(rf"^({TS_PATTERN}) (\{{.*\}})\s*$")),
    ("kv", re.compile(rf"^({TS_PATTERN}) (level=.*)$")),
    ("kvinfo", re.compile(rf"^({TS_PATTERN}) (INFO|DEBUG|WARN|WARNING|ERROR|TRACE) (.*)$")),
]


def _unquote(v):
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return v


def parse_kv(text):
    return {k: _unquote(v) for k, v in KV.findall(text)}


def parse_line(line):
    """Return dict(ts, shape, level, service, trace, event, kv) or None if unrecognised."""
    for shape, rx in SHAPES:
        m = rx.match(line)
        if not m:
            continue
        g = m.groups()
        if shape == "syslog":
            kv = parse_kv(g[4])
            return dict(ts=g[0], shape=shape, level=kv.get("level"), service=g[2],
                        trace=g[3], event=kv.get("event"), kv=kv)
        if shape == "cloud":
            top = parse_kv(g[1])
            inner = parse_kv(top.get("message", ""))
            kv = dict(inner)
            return dict(ts=g[0], shape=shape, level=top.get("level"), service=top.get("function"),
                        trace=top.get("requestId"), event=inner.get("event"), kv=kv)
        if shape in ("pipe", "bracket"):
            kv = parse_kv(g[5])
            return dict(ts=g[0], shape=shape, level=g[1], service=g[2], trace=g[3],
                        event=g[4], kv=kv)
        if shape == "json":
            try:
                obj = json.loads(g[1])
            except ValueError:
                return None
            kv = {k: (v if isinstance(v, str) or v is None else json.dumps(v)) for k, v in obj.items()}
            return dict(ts=g[0], shape=shape, level=obj.get("severity"),
                        service=obj.get("service") or obj.get("logger"),
                        trace=obj.get("trace_id"), event=obj.get("event"), kv=kv)
        if shape == "kv":
            kv = parse_kv(g[1])
            return dict(ts=g[0], shape=shape, level=kv.get("level"), service=kv.get("service"),
                        trace=kv.get("trace_id"), event=kv.get("event"), kv=kv)
        if shape == "kvinfo":
            kv = parse_kv(g[2])
            return dict(ts=g[0], shape=shape, level=g[1], service=kv.get("service"),
                        trace=kv.get("trace_id"), event=kv.get("event"), kv=kv)
    return None


ENVELOPE = ("level", "severity", "logger", "service", "trace_id", "instance", "pod", "region")


def parse_log(manifest_row, fmt="log"):
    fid = manifest_row["file_id"]
    rep = FileExtraction(file_id=fid, path=manifest_row["file_path"], fmt=fmt)
    try:
        lines = manifest_row["_path"].read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError) as exc:
        rep.status = "FAILED"
        rep.reasons.append(f"log read error: {exc}")
        return [], rep

    parsed = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        p = parse_line(line)
        if p is None:
            rep.unparsed_units += 1
            if len(rep.unparsed_samples) < 3:
                rep.unparsed_samples.append(f"line {n}: unrecognised shape")
            continue
        p["n"] = n
        parsed.append(p)

    groups = {}
    for p in parsed:
        trace = p["trace"] if p["trace"] not in (None, "", "-") else None
        groups.setdefault(trace or f"line{p['n']}", []).append(p)

    obs = []
    for gkey, plines in groups.items():
        trace_keys = []
        for p in plines:
            for name in config.TRACE_KEY_FIELDS:
                if name in p["kv"]:
                    c = classify_value(p["kv"][name])
                    if c:
                        trace_keys.append(IdentifierHit(c[0], p["kv"][name], c[1], name,
                                                        "TRACE_KEY", f"line{p['n']}"))
        for p in plines:
            event = p["event"] or ""
            rid = p["kv"].get("resource_id")
            if not rid:
                rep.noise_units += 1          # requests, envelopes, noise events
                continue
            if event.endswith("_started") or event in config.NOISE_EVENTS:
                rep.noise_units += 1
                if event in config.NOISE_EVENTS:
                    # keep the mention visible instead of dropping it silently (B.3.2)
                    rep.warnings.append(f"line {p['n']}: noise event {event!r} names a resource; not an observation")
                continue
            fields = {k: v for k, v in p["kv"].items() if k not in ENVELOPE}
            locator = f"{gkey}@line{p['n']}"
            obs.append(make_observation(
                manifest_row=manifest_row, fmt=fmt, locator=locator, resource_id=rid,
                fields=fields, observed_raw=p["ts"],
                system_id=p["kv"].get("system"), system_field="system" if p["kv"].get("system") else None,
                reporter_service=p["service"], record_type=p["kv"].get("record_type"),
                context={"trace_id": gkey if not gkey.startswith("line") else None,
                         "event": event, "level": p["level"], "shape": p["shape"]},
                extra_keys=tuple(h for h in trace_keys
                                 if not (h.locator == f"line{p['n']}" and h.field in fields))))
    rep.observations = len(obs)
    return obs, rep.finalize()
