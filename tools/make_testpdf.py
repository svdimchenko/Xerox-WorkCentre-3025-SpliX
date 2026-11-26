#!/usr/bin/env python3
"""Write a small 2-page test PDF (text, edge frame, lines, fills, gray ramp).

Usage: make_testpdf.py out.pdf [a4|letter]
"""

import sys

SIZES = {"a4": (595, 842), "letter": (612, 792)}


def page_stream(n, w, h):
    s = []
    # Frame 18pt inside the paper edge: shows whether margins clip.
    s.append("2 w 18 18 %d %d re S" % (w - 36, h - 36))
    # Diagonals: catch band seams / column-order mistakes.
    s.append(
        "0.5 w 18 18 m %d %d l S 18 %d m %d 18 l S" % (w - 18, h - 18, h - 18, w - 18)
    )
    # Title + body text.
    s.append("BT /F1 28 Tf 54 %d Td (WorkCentre 3025 test page %d) Tj ET" % (h - 80, n))
    for i, line in enumerate(
        [
            "SpliX rastertoqpdl on macOS - QPDL v3, algorithm 0x11",
            "The quick brown fox jumps over the lazy dog 0123456789",
            "Left edge, right edge, top and bottom frames should all print.",
        ]
    ):
        s.append("BT /F1 12 Tf 54 %d Td (%s) Tj ET" % (h - 120 - i * 18, line))
    # Solid black block and a 10-step gray ramp (exercises halftoning).
    s.append("0 g 54 %d 120 120 re f" % (h - 330))
    for i in range(10):
        s.append("%.2f g %d %d 40 120 re f" % (i / 9.0, 200 + i * 34, h - 330))
    s.append("0 g")
    # Fine vertical hairlines across the full width: each band column.
    for x in range(30, w - 30, 8):
        s.append("0.25 w %d 200 m %d 300 l S" % (x, x))
    # Page-specific marker so pages can't be confused.
    s.append("BT /F1 72 Tf %d 80 Td (%d) Tj ET" % (w // 2 - 20, n))
    return "\n".join(s).encode()


def main():
    out = sys.argv[1]
    w, h = SIZES[(sys.argv[2] if len(sys.argv) > 2 else "a4").lower()]
    pages = [page_stream(n, w, h) for n in (1, 2)]
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join("%d 0 R" % (4 + 2 * i) for i in range(len(pages)))
    objs.append(
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages))).encode()
    )
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, stream in enumerate(pages):
        objs.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                % (w, h, 5 + 2 * i)
            ).encode()
        )
        objs.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets:
        pdf += b"%010d 00000 n \n" % o
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    with open(out, "wb") as f:
        f.write(pdf)


if __name__ == "__main__":
    main()
