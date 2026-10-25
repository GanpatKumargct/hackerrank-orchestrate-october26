"""Standard-library PDF text extractor (plan B.1.2, C.1).

Supports what the participant PDFs use (verified in Stage 1–3 probes): an object
table, a page tree, content streams filtered by ASCII85Decode/FlateDecode, literal
or hex text strings drawn with Tj/TJ/'/", and per-font ToUnicode CMaps (falling
back to WinAnsi for simple fonts without one). Anything else is reported as a
FAILED extraction with a reason — text is never guessed, and a failed extraction
never means "no records" (B.3.2).

Observations: one per (page, resource ID named on that page). The page text is
kept as `visible_text`, so identifiers in it are FREE_TEXT_MENTION hits. The
document's own capture/issue time (if printed) is the observation time; event
times printed inside the document (recorded, received, …) stay as fields.
"""
import base64
import re
import zlib
from datetime import datetime, timezone

from .. import config
from ..models import FileExtraction
from .common import make_observation

OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")
RESOURCE_ID_RE = re.compile(
    r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|cache|"
    r"email_delivery|marketing|object|legal_hold|telemetry)_\d+\b")
MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
LABEL_TIME_RE = re.compile(
    r"\b(%s)\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})\s+(\d{2})\s*:?\s*(\d{2})\s*UTC" %
    "|".join(re.escape(l) for l in config.PDF_OBSERVATION_LABELS + config.PDF_EVENT_LABELS), re.I)
ESCAPES = {ord("n"): "\n", ord("r"): "\r", ord("t"): "\t", ord("b"): "\b", ord("f"): "\f"}


class PdfError(Exception):
    pass


def _split(body):
    if b"stream" in body:
        head, _, rest = body.partition(b"stream")
        rest = rest.lstrip(b"\r\n")
        data = rest[:rest.rfind(b"endstream")] if b"endstream" in rest else rest
        return head, data
    return body, None


def _decode_stream(head, data):
    filters = re.findall(rb"/(ASCII85Decode|FlateDecode|[A-Za-z0-9]+Decode)", head)
    for f in filters:
        if f == b"ASCII85Decode":
            raw = data.strip()
            if raw.endswith(b"~>"):
                raw = raw[:-2]
            data = base64.a85decode(raw, adobe=False)
        elif f == b"FlateDecode":
            data = zlib.decompressobj().decompress(data)
        else:
            raise PdfError(f"unsupported stream filter {f.decode()}")
    return data


def _literal_strings(data, start):
    """Parse a PDF literal string starting at data[start] == '('. Returns (bytes, end)."""
    depth, i, out = 1, start + 1, bytearray()
    while i < len(data) and depth:
        c = data[i]
        if c == 0x5C:                                    # backslash escape
            n = data[i + 1] if i + 1 < len(data) else 0
            if 0x30 <= n <= 0x37:
                m = re.match(rb"[0-7]{1,3}", data[i + 1:i + 4]).group(0)
                out.append(int(m, 8) & 0xFF)
                i += 1 + len(m)
                continue
            if n in (0x0A, 0x0D):                        # line continuation
                i += 2
                continue
            out += ESCAPES.get(n, chr(n)).encode("latin-1")
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                break
        out.append(c)
        i += 1
    return bytes(out), i + 1


def _parse_cmap(data):
    cmap = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            cmap[int(src, 16)] = bytes.fromhex(dst.decode()).decode("utf-16-be", "replace")
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            base = int(dst, 16)
            for k, code in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
                cmap[code] = chr(base + k)
    return cmap


class _Doc:
    def __init__(self, raw):
        if not raw.startswith(b"%PDF-"):
            raise PdfError("malformed: missing %PDF header")
        trailer = raw[raw.rfind(b"trailer"):] if b"trailer" in raw else raw[-2048:]
        if b"/Encrypt" in trailer or b"/Encrypt" in raw[-4096:]:
            raise PdfError("encrypted PDF is not supported")
        self.objs = {}
        for m in OBJ_RE.finditer(raw):
            self.objs[int(m.group(1))] = _split(m.group(3))
        if not self.objs:
            raise PdfError("malformed: no objects found")
        root = re.search(rb"/Root\s+(\d+)\s+\d+\s+R", trailer) or re.search(rb"/Root\s+(\d+)\s+\d+\s+R", raw)
        if not root or int(root.group(1)) not in self.objs:
            raise PdfError("malformed: no document catalog")
        self.root = int(root.group(1))
        self._cmaps = {}

    def head(self, num):
        if num not in self.objs:
            raise PdfError(f"malformed: missing object {num}")
        return self.objs[num][0]

    def stream(self, num):
        head, data = self.objs.get(num, (b"", None))
        if data is None:
            raise PdfError(f"malformed: object {num} has no stream")
        return _decode_stream(head, data)

    def pages(self):
        pages_ref = re.search(rb"/Pages\s+(\d+)\s+\d+\s+R", self.head(self.root))
        if not pages_ref:
            raise PdfError("malformed: catalog has no /Pages")
        out, seen = [], set()

        def walk(num):
            if num in seen:
                raise PdfError("malformed: cyclic page tree")
            seen.add(num)
            head = self.head(num)
            if re.search(rb"/Type\s*/Pages\b", head):
                kids = re.search(rb"/Kids\s*\[(.*?)\]", head, re.S)
                for k in REF_RE.findall(kids.group(1) if kids else b""):
                    walk(int(k))
            elif re.search(rb"/Type\s*/Page\b", head):
                out.append(num)
        walk(int(pages_ref.group(1)))
        return out

    def _resource_dict(self, page_head):
        m = re.search(rb"/Resources\s+(\d+)\s+\d+\s+R", page_head)
        return self.head(int(m.group(1))) if m else page_head

    def fonts(self, page_head):
        res = self._resource_dict(page_head)
        m = re.search(rb"/Font\s+(\d+)\s+\d+\s+R", res)
        font_dict = self.head(int(m.group(1))) if m else (
            re.search(rb"/Font\s*<<(.*?)>>", res, re.S).group(1) if re.search(rb"/Font\s*<<", res) else b"")
        fonts = {}
        for name, ref in re.findall(rb"/([A-Za-z0-9+_.\-]+)\s+(\d+)\s+\d+\s+R", font_dict):
            fonts[name.decode()] = self._font_map(int(ref))
        return fonts

    def _font_map(self, num):
        if num in self._cmaps:
            return self._cmaps[num]
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", self.head(num))
        cmap = _parse_cmap(self.stream(int(tu.group(1)))) if tu else None   # None => WinAnsi
        self._cmaps[num] = cmap
        return cmap

    def has_images(self, page_head):
        res = self._resource_dict(page_head)
        return b"/XObject" in res or b"/Image" in res

    def contents(self, page_head):
        m = re.search(rb"/Contents\s*(\[.*?\]|\d+\s+\d+\s+R)", page_head, re.S)
        if not m:
            return b""
        return b"\n".join(self.stream(int(r)) for r in REF_RE.findall(m.group(1)))


def _decode_text(raw, cmap):
    if cmap is None:
        return raw.decode("cp1252", "replace")
    return "".join(cmap.get(b, "") if cmap.get(b, "") != "\x00" else "" for b in raw)


def _page_runs(content, fonts):
    """Text runs in stream order. Hex strings without a CMap are refused."""
    runs, font, i, n = [], None, 0, len(content)
    while i < n:
        c = content[i:i + 1]
        if c == b"(":
            raw, i = _literal_strings(content, i)
            runs.append((raw, font, "literal"))
            continue
        if c == b"<" and content[i:i + 2] != b"<<":
            end = content.find(b">", i)
            hx = re.sub(rb"\s", b"", content[i + 1:end])
            if len(hx) % 2:
                hx += b"0"
            runs.append((bytes.fromhex(hx.decode()), font, "hex"))
            i = end + 1
            continue
        if c == b"/":
            m = re.match(rb"/([A-Za-z0-9+_.\-]+)\s+[\d.]+\s+Tf", content[i:i + 64])
            if m:
                font = m.group(1).decode()
                i += m.end()
                continue
        i += 1
    # Decode every string operand in text order (generated PDFs use strings only as text).
    shown = []
    for raw, fname, kind in runs:
        cmap = fonts.get(fname) if fname else None
        if kind == "hex" and cmap is None:
            raise PdfError("hex text string without ToUnicode CMap is not supported")
        shown.append(_decode_text(raw, cmap))
    return [s for s in (t.strip() for t in shown) if s]


def _labelled_times(text):
    out = {}
    for label, d, mon, y, hh, mm in LABEL_TIME_RE.findall(text):
        month = MONTHS.get(mon.lower()[:3])
        if not month:
            continue
        try:
            iso = datetime(int(y), month, int(d), int(hh), int(mm), tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        out.setdefault(label.lower(), [])
        if iso not in out[label.lower()]:
            out[label.lower()].append(iso)
    return out


def parse_pdf(manifest_row):
    fid = manifest_row["file_id"]
    rep = FileExtraction(file_id=fid, path=manifest_row["file_path"], fmt="pdf")
    try:
        raw = manifest_row["_path"].read_bytes()
        doc = _Doc(raw)
        page_nums = doc.pages()
        if not page_nums:
            raise PdfError("malformed: page tree has no pages")
        pages = []
        for no, num in enumerate(page_nums, start=1):
            head = doc.head(num)
            runs = _page_runs(doc.contents(head), doc.fonts(head))
            if not runs:
                if doc.has_images(head) or b" Do" in doc.contents(head):
                    raise PdfError(f"page {no}: image-only page, no extractable text (needs OCR; not available)")
                rep.warnings.append(f"page {no}: no text")
            pages.append((no, " ".join(runs), runs[0] if runs else ""))
    except (PdfError, ValueError, zlib.error, OSError) as exc:
        rep.status = "FAILED"
        rep.reasons.append(f"pdf extraction failed: {exc}")
        return [], rep

    rep.pages = [(no, text) for no, text, _ in pages]
    full = " ".join(t for _, t, _ in pages)
    times = _labelled_times(full)
    observed_raw = None
    for label in config.PDF_OBSERVATION_LABELS:
        vals = times.get(label, [])
        if len(vals) == 1:
            observed_raw = vals[0]
            break
        if len(vals) > 1:
            rep.warnings.append(f"multiple '{label}' times {vals}; observation time left to file capture")
            break
    event_times = {k: v for k, v in times.items() if k not in config.PDF_OBSERVATION_LABELS}

    obs = []
    for no, text, heading in pages:
        for rid in sorted(set(RESOURCE_ID_RE.findall(text))):
            fields = {"visible_text": text, "page": no, "page_heading": heading[:120]}
            for label, vals in event_times.items():
                fields[f"event_time.{label}"] = vals
            obs.append(make_observation(
                manifest_row=manifest_row, fmt="pdf", locator=f"page{no}#{rid}", resource_id=rid,
                fields=fields, observed_raw=observed_raw,
                context={"origin": manifest_row.get("origin"), "page": no}))
    if not obs:
        rep.reasons.append("no resource identifiers in document text; kept as page context only")
    rep.observations = len(obs)
    return obs, rep.finalize()
