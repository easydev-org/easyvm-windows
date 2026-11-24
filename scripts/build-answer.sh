#!/bin/sh
# THE ANSWER CD, BUILT FOR ONE WINDOWS FAMILY AND FOR THE MEDIUM THAT FAMILY IS INSTALLED FROM.
#
#   scripts/build-answer.sh <family> <windows.iso> <virtio-win.iso> <answer.iso>
#
#	family        win11 | win10 | win11iot-ltsc | win2025 - a row of build-answer.py's PROFILES
#	windows.iso   the medium the guest installs FROM: the edition table is read out of it
#	virtio-win.iso  the driver ISO whose $WinPEDriver$ tree goes on the CD
#	answer.iso    where to write the result
#
# WHY THIS IS A SCRIPT RATHER THAN EIGHT ARGUMENTS IN THE WORKFLOW. There are two decisions in it and
# both need a sentence:
#
#	WHICH IMAGE ON THE MEDIUM     never from a constant. `wim-editions.py` reads the medium's own
#	                              install.wim and prints the index for the image the family names,
#	                              or refuses with the whole table. MEASURED: Windows 11 consumer has
#	                              Professional at 6, the IoT LTSC evaluation medium has 6 out of
#	                              range, and Server 2025 names its images rather than numbering them.
#
#	INDEX OR NAME                 Server's medium answers to a NAME (`/IMAGE/NAME`), and the clients
#	                              answer to an INDEX. The choice is a fact about the family, so it
#	                              lives in PROFILES and this script reads it from there - one place,
#	                              not two that can disagree.
#
# A FAILURE HERE IS A REFUSAL WITH THE TABLE, not a Setup that stops at an image picker forty minutes
# into an install nobody is watching.
set -eu

family=${1:?family: win11, win10, win11iot-ltsc or win2025}
windows_iso=${2:?the Windows medium: the edition table is read out of it}
virtio_iso=${3:?the virtio-win ISO the drivers come from}
out=${4:?where to write the answer ISO}

here=$(dirname "$0")
[ -f "$windows_iso" ] || { echo "no Windows medium at $windows_iso" >&2; exit 1; }
[ -f "$virtio_iso" ] || { echo "no virtio-win ISO at $virtio_iso" >&2; exit 1; }

# A SINGLE-IMAGE MEDIUM IS NOT ASKED FOR A TABLE, AND THAT IS THE POINT.
#
# `wimlib-imagex` cannot read the Server 2025 evaluation medium's `install.wim` at all - measured
# 2026-11-24, "Unable to parse the WIM file's XML document" - and it is the DISC's tool that fails, not
# the disc: the ISO is exactly the declared size and `7z`'s own extraction is 857 bytes short of the
# size the archive reports. A family flagged `single_image` needs no table, no index and no name, so
# this path must not demand one.
single=$(python3 - "$here" "$family" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import importlib.util
spec = importlib.util.spec_from_file_location("ba", sys.argv[1] + "/build-answer.py")
ba = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ba)
print("yes" if ba.PROFILES[sys.argv[2]].get("single_image") else "no")
PYEOF
)

if [ "$single" = "yes" ]; then
    echo "=== $family: one image on the disc, so no selector is written"
    python3 "$here/build-answer.py" \
        --profile "$family" \
        --single-image \
        --template "$(dirname "$here")/11/answer/Autounattend.xml" \
        --virtio-iso "$virtio_iso" \
        --out "$out" \
        --label "ANSWER"
    size=$(stat -c %s "$out")
    echo "=== $out: $((size / 1024)) KiB"
    exit 0
fi

echo "=== $family: reading the edition table out of $(basename "$windows_iso")"
python3 "$here/wim-editions.py" "$windows_iso"

# THE SELECTOR, TAKEN FROM THE SAME TABLE THE CALLER JUST SAW.
want=$(python3 - "$here" "$family" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import importlib.util
spec = importlib.util.spec_from_file_location("ba", sys.argv[1] + "/build-answer.py")
ba = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ba)
print(ba.PROFILES[sys.argv[2]]["want"])
PY
)

# WHICH KIND OF SELECTOR THIS FAMILY'S ANSWER FILE TAKES, read from the same PROFILES table.
# `index` families are handed the NUMBER the medium's own table gave for the image they name;
# `name` families (Server) are handed the image's FULL NAME, because `/IMAGE/NAME` is compared for
# equality and a substring selects nothing.
selector=$(python3 - "$here" "$family" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import importlib.util
spec = importlib.util.spec_from_file_location("ba", sys.argv[1] + "/build-answer.py")
ba = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ba)
print(ba.PROFILES[sys.argv[2]].get("select", "index"))
PYEOF
)

echo "=== $family wants image $want, selected by $selector"
case "$selector" in
  name)
    # THE RESOLVED NAME, NEVER THE QUERY. Setup compares /IMAGE/NAME for equality.
    resolved=$(python3 "$here/wim-editions.py" "$windows_iso" --want "$want" --name)
    echo "    resolved to $resolved"
    set -- --want "$resolved"
    ;;
  index)
    # THE NUMBER FROM THE MEDIUM'S OWN TABLE, so a release that reorders its images still installs
    # the edition whose NAME the profile asked for.
    index=$(python3 "$here/wim-editions.py" "$windows_iso" --want "$want")
    echo "    resolved to index $index"
    set -- --index "$index"
    ;;
  *)
    echo "profile $family names an unknown selector $selector; it must be index or name" >&2
    exit 1
    ;;
esac

python3 "$here/build-answer.py" \
    --profile "$family" \
    "$@" \
    --template "$(dirname "$here")/11/answer/Autounattend.xml" \
    --virtio-iso "$virtio_iso" \
    --out "$out" \
    --label "ANSWER"

size=$(stat -c %s "$out")
# THE SAME FLOOR THE BUILDER ENFORCES, restated where a caller reads it: a 448 KiB ISO is a boot
# record with an answer file and none of the installer's drivers.
[ "$size" -gt $((100 * 1024)) ] || {
    echo "the answer ISO is $size bytes, which is smaller than an ISO9660 volume with one file" >&2
    exit 1
}
echo "=== $out: $((size / 1024)) KiB"
