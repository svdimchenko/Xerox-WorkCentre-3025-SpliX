#!/bin/sh
#
# uninstall.sh - remove the Xerox WorkCentre 3025 SpliX driver.
#
# Removes the filter, the PPD and the installer receipt. Printer queues that
# use this driver are listed but NOT deleted; remove them in
# System Settings > Printers & Scanners (or with `lpadmin -x <queue>`).

set -eu

PKG_ID=io.github.splix.wc3025
PREFIX_DIR=/Library/Printers/SpliX
PPD="/Library/Printers/PPDs/Contents/Resources/Xerox WorkCentre 3025 SpliX.ppd.gz"

if [ "$(id -u)" -ne 0 ]; then
    echo "uninstall.sh: run with sudo" >&2
    exit 1
fi

queues=$(grep -l "Xerox WorkCentre 3025 SpliX" /etc/cups/ppd/*.ppd 2>/dev/null \
         | xargs -n1 basename 2>/dev/null | sed 's/\.ppd$//' || true)

rm -f "$PPD"
rm -rf "$PREFIX_DIR"
pkgutil --forget "$PKG_ID" >/dev/null 2>&1 || true

echo "Removed $PREFIX_DIR and the WorkCentre 3025 SpliX PPD."
if [ -n "$queues" ]; then
    echo "These printer queues still use the driver and will stop printing:"
    echo "$queues" | sed 's/^/    /'
fi
