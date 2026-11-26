#!/bin/sh
#
# expand-drv.sh - portable replacement for SpliX's ppd/compile.sh "drv" mode.
#
# SpliX .drv.in files use a custom `#import "file"` directive (not understood
# by ppdc) to splice shared .defs files in. The upstream script relies on GNU
# sed -r and "\t" inside bracket expressions, which BSD/macOS tools reject or
# interpret differently. This does the same expansion with POSIX awk.
#
# Usage: expand-drv.sh <input.drv.in> > output.drv
#        (imports are resolved relative to the input file's directory)

set -eu

if [ $# -ne 1 ]; then
    echo "usage: $0 <file.drv.in>" >&2
    exit 64
fi

dir=$(cd "$(dirname "$1")" && pwd)

awk -v dir="$dir" '
function expand(file,    line, m, inc, rc) {
    while ((rc = (getline line < file)) > 0) {
        if (match(line, /^[ \t]*#import[ \t]+"[A-Za-z0-9._-]+"/)) {
            inc = line
            sub(/^[ \t]*#import[ \t]+"/, "", inc)
            sub(/".*$/, "", inc)
            expand(dir "/" inc)
        } else {
            print line
        }
    }
    if (rc < 0) {
        printf("expand-drv: cannot read %s\n", file) > "/dev/stderr"
        exit 1
    }
    close(file)
}
BEGIN { expand(ARGV[1]); ARGV[1] = "" }
' "$dir/$(basename "$1")"
