#!/bin/sh
#
# patch-ppd.sh - adapt the ppdc-generated SpliX PPD for a macOS install.
#
# Usage: patch-ppd.sh <absolute-filter-path> <driver-version> < in.ppd > out.ppd
#
#  * cupsFilter: macOS's /usr/libexec/cups/filter is SIP-protected, so the
#    filter is installed under /Library/Printers and referenced by full path.
#  * NickName: make the driver distinguishable from Xerox's own (old) driver
#    in the macOS "Use:" driver menu. (*FileVersion is left alone on purpose:
#    rastertoqpdl refuses PPDs whose FileVersion != the SpliX version.)
#  * 1284DeviceID: lets macOS auto-select this PPD when the printer is
#    plugged in over USB (matched on MFG + MDL).

set -eu

if [ $# -ne 2 ]; then
    echo "usage: $0 <filter-path> <version> < in.ppd > out.ppd" >&2
    exit 64
fi

filter=$1
version=$2

sed -e "s|^\*cupsFilter: \"application/vnd.cups-raster 0 rastertoqpdl\"|*cupsFilter: \"application/vnd.cups-raster 0 $filter\"|" \
    -e "s|^\*NickName: .*|*NickName: \"Xerox WorkCentre 3025 SpliX, $version\"|" \
    -e '/^\*Product: /a\
*1284DeviceID: "MFG:Xerox;MDL:WorkCentre 3025;"' \
    | {
        out=$(cat)
        # Fail loudly if upstream changes break any of the substitutions.
        for want in "cupsFilter: \"application/vnd.cups-raster 0 $filter\"" \
                    "NickName: \"Xerox WorkCentre 3025 SpliX" \
                    "1284DeviceID: "; do
            printf '%s\n' "$out" | grep -qF "$want" || {
                echo "patch-ppd: substitution missing: $want" >&2
                exit 1
            }
        done
        printf '%s\n' "$out"
    }
