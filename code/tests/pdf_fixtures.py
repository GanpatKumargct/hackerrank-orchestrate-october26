"""Builds small synthetic PDFs with the standard library (fictional content)."""
import base64
import zlib


def _a85_flate(data):
    return base64.a85encode(zlib.compress(data)) + b"~>"


def _cmap(extra=None):
    pairs = [(c, c) for c in range(0x20, 0x7F)] + [(0x01, 0x2026)] + list((extra or {}).items())
    body = "".join(f"<{s:02X}> <{d:04X}>\n" for s, d in pairs)
    return (f"/CIDInit /ProcSet findresource begin\nbegincmap\n1 begincodespacerange\n<00> <7F>\n"
            f"endcodespacerange\n{len(pairs)} beginbfchar\n{body}endbfchar\nendcmap\n").encode()


def build_pdf(pages, *, to_unicode=True, encrypt=False, header=True, content_filter="a85flate",
              image_pages=(), raw_content=None):
    """pages: list of lists of text runs (bytes or str). Returns PDF bytes."""
    objs = {}
    n_pages = len(pages)
    page_ids = [3 + i for i in range(n_pages)]
    font_id, cmap_id = 100, 101
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = b"<< /Type /Pages /Kids [ " + b" ".join(b"%d 0 R" % p for p in page_ids) + b" ] /Count %d >>" % n_pages
    font = b"<< /Type /Font /Subtype /TrueType /BaseFont /Fixture"
    if to_unicode:
        font += b" /ToUnicode %d 0 R" % cmap_id
        objs[cmap_id] = (b"<< /Filter [ /FlateDecode ] >>", zlib.compress(_cmap()))
    objs[font_id] = font + b" >>"
    for i, runs in enumerate(pages):
        content_id = 200 + i
        if raw_content is not None:
            content = raw_content
        else:
            ops = b"BT /F1+0 10 Tf "
            for run in runs:
                run = run.encode("latin-1") if isinstance(run, str) else run
                esc = run.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
                ops += b"(" + esc + b") Tj T* "
            ops += b"ET"
            if i in image_pages:
                ops = b"q 100 0 0 100 0 0 cm /Im1 Do Q"
            content = ops
        if content_filter == "a85flate":
            objs[content_id] = (b"<< /Filter [ /ASCII85Decode /FlateDecode ] >>", _a85_flate(content))
        elif content_filter == "flate":
            objs[content_id] = (b"<< /Filter [ /FlateDecode ] >>", zlib.compress(content))
        else:
            objs[content_id] = (b"<< /Filter [ /%s ] >>" % content_filter.encode(), content)
        res = b"/Font << /F1+0 %d 0 R >>" % font_id
        if i in image_pages:
            res += b" /XObject << /Im1 300 0 R >>"
        objs[page_ids[i]] = (b"<< /Type /Page /Parent 2 0 R /Resources << " + res +
                             b" >> /Contents %d 0 R >>" % content_id)
    out = bytearray(b"%PDF-1.4\n%\x93\x8c\n" if header else b"garbage\n")
    for num in sorted(objs):
        val = objs[num]
        out += b"%d 0 obj\n" % num
        if isinstance(val, tuple):
            out += val[0] + b"\nstream\n" + val[1] + b"\nendstream\n"
        else:
            out += val + b"\n"
        out += b"endobj\n"
    trailer = b"trailer\n<< /Root 1 0 R /Size %d" % (max(objs) + 1)
    if encrypt:
        trailer += b" /Encrypt 400 0 R"
    out += trailer + b" >>\nstartxref\n0\n%%EOF\n"
    return bytes(out)
