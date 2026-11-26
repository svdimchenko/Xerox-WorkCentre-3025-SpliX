#!/bin/sh
#
# test-pipeline.sh - run the macOS print pipeline offline and validate output.
#
# For each (paper size, resolution) case:
#   1. PDF -> CUPS raster with Apple's own filters (cupsfilter), using our PPD
#   2. raster -> QPDL with the freshly built rastertoqpdl
#   3. decode the QPDL and compare it pixel-for-pixel with the raster
#   4. also run the whole chain through cupsfilter, to prove the PPD's
#      cupsFilter line resolves, and check it yields the same page data
#
# Usage: test-pipeline.sh <rastertoqpdl> <wc3025.ppd>

set -eu

filter=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
ppd=$2
here=$(cd "$(dirname "$0")" && pwd)
out=${TEST_OUT:-$(dirname "$filter")/test}
rm -rf "$out"
mkdir -p "$out"

# Test copy of the PPD whose cupsFilter points at the build tree.
sed "s|^\*cupsFilter: \"application/vnd.cups-raster 0 .*\"|*cupsFilter: \"application/vnd.cups-raster 0 $filter\"|" \
    "$ppd" > "$out/test.ppd"

fail=0
for paper in A4 Letter; do
    lc=$(echo $paper | tr '[:upper:]' '[:lower:]')
    python3 "$here/make_testpdf.py" "$out/test-$lc.pdf" "$lc"
    for res in 600dpi 1200dpi; do
        case_dir="$out/$lc-$res"
        mkdir -p "$case_dir"
        opts="PageSize=$paper Resolution=$res"
        echo "=== $paper @ $res"

        cupsfilter -p "$out/test.ppd" -m application/vnd.cups-raster \
            -o PageSize=$paper -o Resolution=$res \
            "$out/test-$lc.pdf" > "$case_dir/job.ras" 2> "$case_dir/cupsfilter-raster.log"

        PPD="$out/test.ppd" "$filter" 1 tester "test-$lc" 1 "$opts" \
            "$case_dir/job.ras" > "$case_dir/job.qpdl" 2> "$case_dir/filter.log" || {
            echo "FAIL: rastertoqpdl exited $?"; cat "$case_dir/filter.log"; fail=1; continue; }

        python3 "$here/qpdl_check.py" --raster "$case_dir/job.ras" \
            --qpdl "$case_dir/job.qpdl" --png-dir "$case_dir" --expect-pages 2 || fail=1

        # Whole chain through CUPS: PDF -> ... -> our filter (via PPD path).
        # -m printer/foo: convert all the way to the printer format (the default
        # destination is application/pdf). -e: honour the PPD's cupsFilter
        # lines; without it cupsfilter silently takes a PostScript route.
        if cupsfilter -p "$out/test.ppd" -e -m printer/foo \
                -o PageSize=$paper -o Resolution=$res \
                "$out/test-$lc.pdf" > "$case_dir/chain.qpdl" 2> "$case_dir/cupsfilter-chain.log"; then
            # PJL carries a timestamp/job name; compare from the QPDL payload on.
            a=$(sed -n '/ENTER LANGUAGE/,$p' "$case_dir/job.qpdl" | shasum | cut -c1-16)
            b=$(sed -n '/ENTER LANGUAGE/,$p' "$case_dir/chain.qpdl" | shasum | cut -c1-16)
            if [ "$a" = "$b" ]; then
                echo "    full cupsfilter chain: identical page data"
            else
                echo "FAIL: full cupsfilter chain output differs from direct run"
                fail=1
            fi
        else
            echo "FAIL: full cupsfilter chain failed"; tail -5 "$case_dir/cupsfilter-chain.log"
            fail=1
        fi
    done
done

# Job titles with quotes / control characters must not break the PJL header.
echo "=== hostile job title"
title=$(printf 'Report "Q3"\n@PJL SET RESOLUTION=300')
PPD="$out/test.ppd" "$filter" 1 'o"brien' "$title" 1 "PageSize=A4 Resolution=600dpi" \
    "$out/a4-600dpi/job.ras" > "$out/title.qpdl" 2>/dev/null
pjl_bad=$(sed -n '/ENTER LANGUAGE/q;p' "$out/title.qpdl" \
    | grep -E '^@PJL SET (JOBNAME|USERNAME)=' | grep -vE '^@PJL SET [A-Z]+="[^"]*"$' || true)
injected=$(grep -c '^@PJL SET RESOLUTION=300' "$out/title.qpdl" || true)
if [ -z "$pjl_bad" ] && [ "$injected" = 0 ] && \
   python3 "$here/qpdl_check.py" --raster "$out/a4-600dpi/job.ras" \
       --qpdl "$out/title.qpdl" >/dev/null; then
    echo "PASS"
else
    echo "FAIL: job title / user name not sanitised in PJL header"; fail=1
fi

[ $fail -eq 0 ] && echo "ALL TESTS PASSED" || echo "SOME TESTS FAILED"
exit $fail
