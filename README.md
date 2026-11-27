# Xerox WorkCentre 3025 driver for macOS

A native print driver for the Xerox WorkCentre 3025 on current macOS
(Apple Silicon and Intel, macOS 11+). Xerox's own Mac driver stops at
macOS 10.14.

The WC3025 has no PostScript, PCL or AirPrint. It only accepts a host-rendered
Samsung format (SPL / QPDL v3), so the Mac has to produce the exact byte stream
itself. This project packages the open-source
[SpliX](https://github.com/OpenPrinting/splix) QPDL encoder, which supports
the WC3025 and its Samsung twin (M2070 series), as a macOS CUPS driver.

Printing only. Scanning isn't included.

## Install

```sh
make test       # optional: offline end-to-end check, see below
make install    # builds build/Xerox-WorkCentre-3025-SpliX-<version>.pkg, runs installer (sudo)
```

`<version>` is `VERSION` in the [Makefile](Makefile).

Prebuilt installer packages are attached to each
[GitHub Release](https://github.com/svdimchenko/Xerox-WorkCentre-3025-SpliX/releases).
Download the `.pkg` asset and open it with Installer, or run
`sudo installer -pkg Xerox-WorkCentre-3025-SpliX-<version>.pkg -target /`.

The package isn't signed or notarized, so macOS may refuse to open a
downloaded copy. Click **Open Anyway** in **System Settings → Privacy &
Security**, or install it with the `sudo installer` command above, which isn't
affected.

Then plug in the printer and open **System Settings → Printers & Scanners → Add
Printer**, select the WorkCentre 3025, and under **Use** choose
**Xerox WorkCentre 3025 SpliX, &lt;version&gt;** (Select Software… if it isn't
preselected).

From the command line instead:

```sh
/usr/libexec/cups/backend/usb          # prints the printer's usb:// URI
lpadmin -p WC3025 -E -v 'usb://Xerox/WorkCentre%203025?serial=…' \
  -P "/Library/Printers/PPDs/Contents/Resources/Xerox WorkCentre 3025 SpliX.ppd.gz"
```

Uninstall with `make uninstall`. Printer queues are left in place and listed.
If you installed from a release and have no source checkout, run the same
steps by hand:

```sh
sudo rm -rf /Library/Printers/SpliX
sudo rm -f "/Library/Printers/PPDs/Contents/Resources/Xerox WorkCentre 3025 SpliX.ppd.gz"
sudo pkgutil --forget io.github.splix.wc3025
```

### What gets installed

| Path | |
|---|---|
| `/Library/Printers/SpliX/Filters/rastertoqpdl` | CUPS filter (universal arm64 + x86_64, ad-hoc signed) |
| `/Library/Printers/PPDs/Contents/Resources/Xerox WorkCentre 3025 SpliX.ppd.gz` | PPD |
| `/Library/Printers/SpliX/COPYING` | SpliX licence (GPL-2.0) |

## How it works

```
app → PDF → cgpdftoraster (Apple) → 1-bit CUPS raster → rastertoqpdl → PJL + QPDL v3 → usb
```

macOS rasterizes the page itself, halftoning included. `rastertoqpdl` compresses
it into 128-row bands with Samsung's algorithm 0x11 and wraps it in PJL. The PPD
holds the model parameters SpliX needs: QPDL v3, 512-byte packets, the M2020
"special band width" table, and manual duplex.

## Testing without the printer

`make test` runs the real macOS print pipeline offline for A4 and Letter at 600
and 1200 DPI, using a generated 2-page test PDF (text, edge frame, diagonals,
gray ramp, hairlines):

1. `cupsfilter` turns the PDF into CUPS raster using Apple's filters and this PPD.
2. The built `rastertoqpdl` turns that raster into a printer job.
3. `tools/qpdl_check.py` checks the job's PJL framing, page and band headers,
   and every band checksum. It then decompresses every band and checks the
   result **bit for bit** against the input raster, with SpliX's margin
   handling applied.
4. The whole chain runs again through `cupsfilter -e` using the PPD's
   `cupsFilter` line, and its page data must be identical.
5. A job title with quotes and an embedded `@PJL` line must not break the PJL
   header.

Decoded pages are saved as PNG previews in `build/test/*/page*.png`.

This proves the job is well-formed and carries the right image. It can't prove
the printer accepts it. The first real test print does that.

## Development checks

Install [prek](https://prek.j178.dev/) with `brew install prek`, then run
`prek install` to enable the repository hooks. They check whitespace and merge
markers, validate YAML and private-key detection, and syntax-check the project
shell and Python tools. To run them manually on all tracked files, use
`prek run --all-files`.

GitHub Actions runs the hooks and `make test` on macOS for pushes and pull
requests targeting `main`. Pull request titles must follow Conventional
Commits, such as `feat: add support` or `fix: correct output`. Pushing a tag
matching the Makefile version (`v` followed by `VERSION`, for example
`v0.0.1`) runs the same checks, builds the installer package, and attaches it
to a GitHub Release. Pushes to `main` that change `docs/` also publish the
project website to GitHub Pages.

## First test print: checklist

1. Print `build/test/test-a4.pdf` (or `test-letter.pdf`), both pages.
2. Check that the frame is visible on all four sides, the diagonals are
   continuous with no seams every 128 rows, the gray ramp shows distinct steps,
   and page 2 follows page 1.
3. Repeat at **1200 DPI** (Printer Features / Quality in the print dialog).
4. Optional: try 2-sided printing. The WC3025 has no duplex unit, so SpliX does
   **manual** duplex. It prints one side, then asks you to reinsert the stack
   in the manual tray.

If something goes wrong, collect:

```sh
/usr/libexec/cups/backend/usb                       # the printer's IEEE-1284 device ID
cupsctl --debug-logging                             # then reprint
log show --last 10m --predicate 'process == "cupsd" OR process CONTAINS "rastertoqpdl"' > cups.log
cupsctl --no-debug-logging
```

The PPD's `*1284DeviceID` (`MFG:Xerox;MDL:WorkCentre 3025;`) is a best guess
that lets macOS preselect the driver. If `backend/usb` reports a different
`MDL:`, update it in [tools/patch-ppd.sh](tools/patch-ppd.sh). Printing works
either way, since you can pick the driver manually.

## Layout

```
vendor/splix/          SpliX @ OpenPrinting/splix 7a80218 (see patches below)
tools/expand-drv.sh    portable #import expander (replaces SpliX's GNU-sed compile.sh)
tools/patch-ppd.sh     adapts the ppdc output for macOS paths and naming
tools/qpdl_check.py    QPDL decoder and raster comparator used by `make test`
tools/make_testpdf.py  test page generator
tools/test-pipeline.sh `make test`
tools/uninstall.sh     `make uninstall`
```

### Changes to upstream SpliX

Pristine upstream is the first commit in this repo, so `git diff` against it
shows every change:

- `src/semaphore.cpp`: always signal on post. Upstream only signalled on the
  0→1 transition, which can lose wake-ups with several waiting threads.
- `src/cache.cpp`: `whatToDo = ~whatToDo` on a `bool` is always true, so the
  cache thread never alternated between preload and store. Now uses `!`.
- `src/printer.cpp`: job title and user name are sanitized before going into
  quoted PJL strings (`"` → `'`, control characters → space, max 79 bytes).
- `src/document.cpp`: reads page headers with `cupsRasterReadHeader2` instead
  of the deprecated `cupsRasterReadHeader`, and detects monochrome pages from
  `cupsNumColors` instead of only `CUPS_CSPACE_K`.

Built without JBIG (`-DDISABLE_JBIG`), since the WC3025 uses algorithm 0x11.
`pstoqpdl` isn't built, because macOS rasterizes PDF itself.

## Licence

SpliX is GPL-2.0 (`vendor/splix/COPYING`), so the built driver and installer
are distributed under GPL-2.0.
