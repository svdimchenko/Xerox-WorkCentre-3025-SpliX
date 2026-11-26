#!/usr/bin/env python3
"""
qpdl_check.py - offline validator for rastertoqpdl output (WC3025 / QPDL v3).

Decodes the QPDL byte stream SpliX produces for SPL2 monochrome printers
(algorithm 0x11) and checks it, pixel for pixel, against the CUPS raster that
was fed into the filter. This is the closest thing to a test print we can do
without the printer: it proves the job is well-formed (PJL framing, page and
band headers, checksums) and that the compressed bands decode back to exactly
the input image, minus the hardware margins the filter is supposed to trim.

Usage:
    qpdl_check.py --raster in.ras --qpdl out.qpdl [--png-dir DIR]
                  [--margin-pt 12.5] [--expect-pages N]

Exit status is 0 only if every check passes.

Format notes (from vendor/splix/src/qpdl.cpp, algo0x11.cpp, compress.cpp):
  job      := UEL "@PJL ..." lines, "@PJL ENTER LANGUAGE=QPDL\n", page*, 0x09 UEL
  page     := header[0x11] band* 0x01 copies:u16be
  header   := 00 yres/100 copies:u16be papertype w300:u16be h300:u16be
              source unk1 duplex tumble unk2 qpdlver unk3 xres/100
  band     := 0x0C bandnr width_px:u16be height:u16be compression:u8
              size:u32be signature:4 data checksum:u32be
  checksum := sum of signature + data bytes (mod 2**32)
  0x11     := lastOccur:u32 occur[64]:u16 raw[lastOccur] tokens...
              (u16/u32 endianness follows the signature: EF CD AB 09 = LE)
  The decompressed band is column-major (8-pixel-wide byte columns, each
  `height` rows tall) and inverted (1 = white).
"""

import argparse
import math
import os
import struct
import sys
import zlib

UEL = b"\x1b%-12345X"


class CheckError(Exception):
    pass


# --------------------------------------------------------------------------
# CUPS raster (v2 compressed / v3 uncompressed) reader, 1-bit only
# --------------------------------------------------------------------------
def read_cups_raster(path):
    with open(path, "rb") as f:
        data = f.read()
    sync = data[:4]
    if sync in (b"RaS2", b"RaS3"):
        endian = ">"
    elif sync in (b"2SaR", b"3SaR"):
        endian = "<"
    else:
        raise CheckError("not a CUPS raster v2/v3 file (sync %r)" % sync)
    compressed = sync in (b"RaS2", b"2SaR")
    off = 4
    pages = []
    while off < len(data):
        hdr = data[off:off + 1796]
        if len(hdr) < 1796:
            raise CheckError("truncated raster page header")
        u = lambda o: struct.unpack_from(endian + "I", hdr, o)[0]
        info = {
            "hwres": (u(276), u(280)),
            "margins": (u(312), u(316)),
            "pagesize": (u(352), u(356)),
            "width": u(372),
            "height": u(376),
            "bpc": u(384),
            "bpp": u(388),
            "bpl": u(392),
            "colorspace": u(400),
            "numcolors": u(420),
        }
        off += 1796
        if info["bpp"] != 1:
            raise CheckError("expected 1-bit raster, got %d bpp" % info["bpp"])
        bpl, height = info["bpl"], info["height"]
        rows = []
        if not compressed:
            for _ in range(height):
                rows.append(data[off:off + bpl])
                off += bpl
        else:
            while len(rows) < height:
                repeat = data[off] + 1
                off += 1
                line = bytearray()
                while len(line) < bpl:
                    n = data[off]
                    off += 1
                    if n == 128:
                        line.extend(b"\x00" * (bpl - len(line)))
                    elif n < 128:
                        line.extend(data[off:off + 1] * (n + 1))
                        off += 1
                    else:
                        cnt = 257 - n
                        line.extend(data[off:off + cnt])
                        off += cnt
                rows.extend([bytes(line[:bpl])] * repeat)
            rows = rows[:height]
        pages.append((info, rows))
    return pages


# --------------------------------------------------------------------------
# QPDL decoder
# --------------------------------------------------------------------------
def decompress_0x11(payload, width, height, little):
    e = "<" if little else ">"
    band_size = (width * height + 7) >> 3
    if len(payload) < 4 + 0x40 * 2:
        raise CheckError("0x11 band too short")
    last_occur = struct.unpack_from(e + "I", payload, 0)[0]
    occur = struct.unpack_from(e + "64H", payload, 4)
    idx = 4 + 0x40 * 2
    out = bytearray(b"\xff" * band_size)
    out[:last_occur] = payload[idx:idx + last_occur]
    w = last_occur
    idx += last_occur
    n = len(payload)
    while idx < n:
        counter = payload[idx]
        idx += 1
        if counter & 0x80:
            number = payload[idx]
            idx += 1
            count = ((number & 0xC0) << 1) + (counter & 0x7F) + 3
            dist = occur[number & 0x3F]
            src = w - dist
            if src < 0 or w + count > band_size:
                raise CheckError("0x11 back-reference out of range")
            for i in range(count):          # may overlap: copy bytewise
                out[w + i] = out[src + i]
            w += count
        else:
            cnt = counter + 1
            if w + cnt > band_size:
                raise CheckError("0x11 literal run overflows band")
            out[w:w + cnt] = payload[idx:idx + cnt]
            idx += cnt
            w += cnt
    if w != band_size:
        raise CheckError("0x11 band decoded to %d bytes, expected %d"
                         % (w, band_size))
    # column-major + inverted  ->  row-major, 1 = black
    cols = width // 8
    rows = []
    for y in range(height):
        rows.append(bytes((~out[x * height + y]) & 0xFF for x in range(cols)))
    return rows


def parse_qpdl(data):
    if not data.startswith(UEL):
        raise CheckError("job does not start with UEL")
    marker = data.find(b"ENTER LANGUAGE")
    if marker < 0:
        raise CheckError("no '@PJL ENTER LANGUAGE' line")
    pjl = data[:marker].decode("latin-1")
    lang_line_end = data.index(b"\n", marker)
    lang = data[marker:lang_line_end].decode("latin-1")
    if "QPDL" not in lang.upper():
        raise CheckError("unexpected language line: %r" % lang)
    off = lang_line_end + 1
    pages = []
    while True:
        if data[off] == 0x09:
            if data[off + 1:off + 1 + len(UEL)] != UEL:
                raise CheckError("job footer is not 0x09 + UEL")
            off += 1 + len(UEL)
            break
        hdr = data[off:off + 0x11]
        if hdr[0] != 0:
            raise CheckError("bad page header signature 0x%02x at %d"
                             % (hdr[0], off))
        page = {
            "yres": hdr[1] * 100,
            "copies": (hdr[2] << 8) | hdr[3],
            "papertype": hdr[4],
            "w300": (hdr[5] << 8) | hdr[6],
            "h300": (hdr[7] << 8) | hdr[8],
            "source": hdr[9],
            "duplex": hdr[0xB],
            "tumble": hdr[0xC],
            "qpdl": hdr[0xE],
            "xres": hdr[0x10] * 100,
            "bands": {},
        }
        off += 0x11
        while True:
            sig = data[off]
            if sig == 0x01:
                copies = (data[off + 1] << 8) | data[off + 2]
                if copies != page["copies"]:
                    raise CheckError("page footer copies mismatch")
                off += 3
                break
            if sig != 0x0C:
                raise CheckError("bad band signature 0x%02x at %d" % (sig, off))
            bandnr = data[off + 1]
            width = (data[off + 2] << 8) | data[off + 3]
            height = (data[off + 4] << 8) | data[off + 5]
            comp = data[off + 6]
            size = struct.unpack_from(">I", data, off + 7)[0]
            off += 11
            content = data[off:off + size]
            off += size
            if len(content) != size:
                raise CheckError("truncated band %d" % bandnr)
            if comp != 0x11:
                raise CheckError("band %d uses compression 0x%x, expected 0x11"
                                 % (bandnr, comp))
            body, given = content[:-4], struct.unpack(">I", content[-4:])[0]
            if (sum(body) & 0xFFFFFFFF) != given:
                raise CheckError("band %d checksum mismatch" % bandnr)
            sig4 = body[:4]
            if sig4 == b"\xef\xcd\xab\x09":
                little = True
            elif sig4 == b"\x09\xab\xcd\xef":
                little = False
            else:
                raise CheckError("band %d bad sub-header %s" % (bandnr, sig4.hex()))
            if bandnr in page["bands"]:
                raise CheckError("duplicate band %d" % bandnr)
            page["bands"][bandnr] = (width, height,
                                     decompress_0x11(body[4:], width, height,
                                                     little))
        pages.append(page)
    if off != len(data):
        raise CheckError("%d trailing bytes after job footer" % (len(data) - off))
    return pjl, pages


def assemble(page):
    """Stack decoded bands into a full bitmap (missing bands = blank)."""
    if not page["bands"]:
        return 0, []
    widths = {w for (w, h, _) in page["bands"].values()}
    heights = {h for (w, h, _) in page["bands"].values()}
    if len(widths) != 1 or len(heights) != 1:
        raise CheckError("inconsistent band geometry %s x %s" % (widths, heights))
    width, height = widths.pop(), heights.pop()
    blank = bytes(width // 8)
    rows = []
    for n in range(max(page["bands"]) + 1):
        rows.extend(page["bands"][n][2] if n in page["bands"] else [blank] * height)
    return width, rows


# --------------------------------------------------------------------------
# PNG preview (pure python, downscaled by averaging, so halftoned grays show
# up as grays rather than solid black)
# --------------------------------------------------------------------------
_POPCOUNT = bytes(bin(i).count("1") for i in range(256))


def write_png(path, width, rows, scale):
    scale = max(8, scale - scale % 8)        # whole bytes per output pixel
    step = scale // 8
    ow, oh = max(1, width // scale), max(1, len(rows) // scale)
    area = scale * scale
    raw = bytearray()
    for oy in range(oh):
        counts = [0] * ow
        for r in rows[oy * scale:(oy + 1) * scale]:
            for ox in range(ow):
                counts[ox] += sum(_POPCOUNT[b] for b in r[ox * step:(ox + 1) * step])
        raw.append(0)
        raw.extend(255 - (c * 255) // area for c in counts)

    def chunk(tag, body):
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 0, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raster", required=True)
    ap.add_argument("--qpdl", required=True)
    ap.add_argument("--png-dir")
    ap.add_argument("--margin-pt", type=float, default=12.5,
                    help="PPD HWMargins left/top in points (default 12.5)")
    ap.add_argument("--expect-pages", type=int)
    args = ap.parse_args()

    try:
        rpages = read_cups_raster(args.raster)
        with open(args.qpdl, "rb") as f:
            pjl, qpages = parse_qpdl(f.read())

        print("PJL header:")
        for line in pjl.replace(UEL.decode("latin-1"), "").splitlines():
            if line.strip():
                print("    " + line)

        if args.expect_pages is not None and len(qpages) != args.expect_pages:
            raise CheckError("expected %d pages, QPDL has %d"
                             % (args.expect_pages, len(qpages)))
        if len(rpages) != len(qpages):
            raise CheckError("raster has %d pages, QPDL has %d"
                             % (len(rpages), len(qpages)))

        for n, ((info, rrows), qp) in enumerate(zip(rpages, qpages), 1):
            xres, yres = info["hwres"]
            if (qp["xres"], qp["yres"]) != (xres, yres):
                raise CheckError("page %d: resolution %sx%s, raster is %sx%s"
                                 % (n, qp["xres"], qp["yres"], xres, yres))
            if qp["qpdl"] != 3:
                raise CheckError("page %d: QPDL version %d, expected 3"
                                 % (n, qp["qpdl"]))
            bpl, rh = info["bpl"], info["height"]
            qwidth, qrows = assemble(qp)
            qbpl = qwidth // 8
            page_width = (math.ceil(info["pagesize"][0] * xres / 72) + 7) & ~7
            page_height = math.ceil(info["pagesize"][1] * yres / 72)
            margin_width = (math.ceil(info["margins"][0] * xres / 72) + 7) // 8
            margin_height = math.ceil(info["margins"][1] * yres / 72)

            page_width_bytes = (page_width + 7) // 8
            if bpl > page_width_bytes - 2 * margin_width:
                clipping_x = (bpl - (page_width_bytes - 2 * margin_width)) // 2
                bytes_to_copy = page_width_bytes - 2 * margin_width
            else:
                clipping_x = 0
                margin_width = (page_width_bytes - bpl) // 2
                bytes_to_copy = bpl

            if rh > page_height - 2 * margin_height:
                clipping_y = (rh - (page_height - 2 * margin_height)) // 2
                output_y = margin_height
            else:
                clipping_y = 0
                output_y = (page_height - rh) // 2
            copied_rows = min(rh - clipping_y, page_height - 2 * margin_height)
            hardware_margin_y = (math.ceil(args.margin_pt * yres / 72)
                                 if info["margins"][1] else 0)
            output_y -= hardware_margin_y

            ink = 0
            mismatched = 0
            first_bad = None
            blank = bytes(qbpl)
            for y in range(max(rh, len(qrows))):
                expect = bytearray(qbpl)
                if output_y <= y < output_y + copied_rows:
                    src_y = clipping_y + y - output_y
                    src = rrows[src_y]
                    copy_start = min(margin_width, qbpl)
                    copy_end = min(margin_width + bytes_to_copy, qbpl)
                    src_start = clipping_x + copy_start - margin_width
                    expect[copy_start:copy_end] = src[src_start:src_start + copy_end - copy_start]
                got = qrows[y] if y < len(qrows) else blank
                if got != bytes(expect):
                    mismatched += 1
                    if first_bad is None:
                        first_bad = y
                if got != blank:
                    ink += sum(bin(b).count("1") for b in got)

            print("Page %d: %dx%d dpi, QPDL v%d, paper type %d, source %d, "
                  "duplex %d/%d, %d bands, band width %d px, %d black pixels"
                  % (n, qp["xres"], qp["yres"], qp["qpdl"], qp["papertype"],
                     qp["source"], qp["duplex"], qp["tumble"], len(qp["bands"]),
                     qwidth, ink))
            if mismatched:
                raster_ink = [y for y, row in enumerate(rrows) if any(row)]
                qpdl_ink = [y for y, row in enumerate(qrows) if any(row)]
                raise CheckError(
                    "page %d: %d rows differ from input raster (first at row %d); "
                    "raster=%dx%d colorspace=%d/%d margins=%s page-size=%s; "
                    "QPDL=%dx%d; layout output-y=%d hardware-margin-y=%d "
                    "clip-y=%d copied-rows=%d; "
                    "ink rows raster=%s QPDL=%s"
                    % (n, mismatched, first_bad, info["width"], rh,
                       info["colorspace"], info["numcolors"], info["margins"],
                       info["pagesize"], qwidth, len(qrows), output_y,
                       hardware_margin_y, clipping_y, copied_rows,
                       (raster_ink[0], raster_ink[-1]) if raster_ink else None,
                       (qpdl_ink[0], qpdl_ink[-1]) if qpdl_ink else None))
            if ink == 0:
                raise CheckError("page %d: decoded page is blank" % n)
            print("    decoded bands match input raster exactly "
                  "(raster dimensions %d x %d, QPDL band width %d px)"
                  % (bpl * 8, rh, qwidth))

            if args.png_dir:
                os.makedirs(args.png_dir, exist_ok=True)
                scale = max(1, xres // 75)
                png = os.path.join(args.png_dir, "page%d.png" % n)
                write_png(png, qwidth, qrows, scale)
                print("    preview: " + png)
    except CheckError as e:
        print("FAIL: %s" % e, file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
