#!/usr/bin/env python3
"""Print the edition table inside a Windows ISO, so an answer file never guesses an index.

    wim-editions.py <windows.iso>
    wim-editions.py <windows.iso> --want "Windows 10 Pro"
    wim-editions.py work/install.wim --json

WHY THIS EXISTS. `11/answer/Autounattend.xml` selects an edition by `/IMAGE/INDEX`, and the index is
a NUMBER THAT DEPENDS ON THE IMAGE - not on the release. MEASURED across the four images this
repository now publishes:

    Windows 11 consumer          index 6 is Professional
    Windows 11 IoT LTSC eval     one or two images, and 6 is out of range
    Windows Server 2025 eval     two images, and the installation media names them
                                 "Windows Server 2025 SERVERSTANDARD" / "... SERVERDATACENTER"

So a second Windows release with `index 6` copied from the first is a Setup that stops on "the image
you have selected is not available" - a sentence that names neither the index nor the ISO. The index
has to be READ off the image it belongs to.

WHAT DOCKUR DOES, AND WHY THIS IS THE SAME SHAPE. dockur/windows does not pin an index at all for the
client images: its templates carry no `/IMAGE/INDEX`, and `src/image.sh` calls

    wimlib-imagex info --xml "$wim" | iconv -f UTF-16LE -t UTF-8

then injects the matching index into the answer file at run time. This script is that read, in Python,
with the selection rule made explicit instead of implied by a `case` on the filename.

THE XML IS UTF-16LE AND SAYS SO. `wimlib-imagex info --xml` emits the WIM's own metadata verbatim, and
that is UTF-16LE WITHOUT a BOM in the case measured here - `ET.fromstring` on the raw bytes fails with
"no element found", which is why the decode is explicit rather than left to the parser's guess.

TWO CONTAINERS HOLD THESE IMAGES, AND BOTH ARE READ THE SAME WAY. `install.wim` is the usual one;
`install.esd` is the same format with a different compression, and a release that switched to ESD
would otherwise read as "this ISO has no image".

THE ISO IS OPENED, NOT MOUNTED. `7z` reads an ISO9660/Joliet/UDF tree without a loop device, which is
what a CI runner without root and without `mount` needs. The install image is then extracted to a
temporary file; it is the largest file on the medium and the only one this script wants.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# THE TWO NAMES A WINDOWS MEDIUM USES FOR ITS IMAGE. Order matters only for the message.
IMAGE_NAMES = ("sources/install.wim", "sources/install.esd")


def run(argv):
    out = subprocess.run(argv, capture_output=True)
    if out.returncode != 0:
        raise SystemExit("%s: %s" % (" ".join(argv[:3]), out.stderr.decode(errors="replace").strip()))
    return out.stdout


def local_name(tag):
    return tag.split("}")[-1]


def decode_xml(blob):
    """The WIM metadata XML, from the bytes wimlib printed.

    UTF-16LE IS THE FORMAT AND IT COMES WITHOUT A BOM. A BOM is honoured when it is there, because a
    different wimlib build may emit one, and guessing wrong turns a readable table into a parse error.
    """
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return blob.decode("utf-16")
    if blob[:3] == b"\xef\xbb\xbf":
        return blob.decode("utf-8-sig")
    # NO BOM: the measured case is UTF-16LE, where every ASCII byte is followed by a zero.
    if len(blob) > 2 and blob[1] == 0:
        return blob.decode("utf-16-le", errors="replace")
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return blob.decode("utf-16-le", errors="replace")


def editions_from_xml(text):
    """Every <IMAGE> in the metadata, as the four facts a selection needs."""
    root = ET.fromstring(text)
    rows = []
    for image in root.iter():
        if local_name(image.tag) != "IMAGE":
            continue
        index = image.attrib.get("INDEX")
        if not index or not index.isdigit():
            continue
        name = flags = description = ""
        for child in image:
            tag = local_name(child.tag)
            if tag == "NAME":
                name = (child.text or "").strip()
            elif tag == "FLAGS":
                flags = (child.text or "").strip()
            elif tag == "DESCRIPTION":
                description = (child.text or "").strip()
        rows.append({"index": int(index), "name": name, "flags": flags,
                     "description": description})
    return sorted(rows, key=lambda r: r["index"])


def read_wim(path):
    return editions_from_xml(decode_xml(run(["wimlib-imagex", "info", "--xml", path])))


def find_image(iso):
    """The install image inside an ISO, extracted to a temporary file.

    THE EXTRACTION IS THE POINT: `wimlib-imagex` cannot read a member of an ISO, and mounting one needs
    root. `7z` writes the single member out by its full path.
    """
    for name in IMAGE_NAMES:
        out = subprocess.run(["7z", "l", "-ba", iso, name], capture_output=True, text=True)
        if out.returncode != 0 or not out.stdout.strip():
            continue
        tmp = tempfile.mkdtemp(prefix="wim-editions-")
        dest = os.path.join(tmp, os.path.basename(name))
        subprocess.run(["7z", "x", "-y", "-o" + tmp, iso, name],
                       capture_output=True, text=True, check=False)
        if not os.path.isfile(dest):
            # 7z KEEPS THE PATH (`sources/install.wim`) when the member is named with one.
            nested = os.path.join(tmp, *name.split("/"))
            if os.path.isfile(nested):
                return nested
            raise SystemExit("%s: 7z listed %s but did not extract it" % (iso, name))
        return dest
    raise SystemExit("%s: no %s and no %s on this medium, so there is no edition table to read"
                     % (iso, IMAGE_NAMES[0], IMAGE_NAMES[1]))


def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def select(rows, want):
    """The row an answer file's `/IMAGE/NAME` should name, or a refusal listing what is there.

    AN EXACT NAME IS TRIED FIRST, then a case-and-space-insensitive one, then a substring.

    A SUBSTRING MATCH IS RANKED BY HOW LITTLE OF THE NAME IT LEAVES UNEXPLAINED, AND THAT IS NOT A
    DETAIL. The evaluation medium carries BOTH of

        Windows 11 IoT Enterprise LTSC 2024 Evaluation
        Windows 11 IoT Enterprise LTSC 2024

    so the query "LTSC 2024" hits two images, and a first-match or a refusal is wrong twice over:
    the retail template wants the SHORTER name, and the eval template reaches its own by naming more
    ("LTSC 2024 Evaluation", which hits one). MEASURED on a synthesised medium with exactly that
    pair: a plain substring rule answered "matches 2 images", which is a dead end where the shorter
    name was the intended answer all along.

    SO THE SHORTEST NAME WINS. The query explains ALL of a short name and only part of a longer one,
    and the part it does not explain ("Evaluation") is a qualifier the caller did not ask for. That is
    the same rule as a longest-prefix match read backwards, and it is what makes a generic query mean
    the generic image.

    A TIE IS STILL A REFUSAL, because two names of the same length that both contain the query are
    genuinely ambiguous, and picking one would be a guess.
    """
    wanted = normalise(want)
    for row in rows:
        if row["name"] == want:
            return row, "exact"
    for row in rows:
        if normalise(row["name"]) == wanted:
            return row, "case and spacing"
    hits = [row for row in rows if wanted in normalise(row["name"])]
    if not hits:
        raise SystemExit("no image on this medium is named like %r; it has:\n%s"
                         % (want, table(rows)))
    if len(hits) == 1:
        return hits[0], "substring"
    # THE SHORTEST NAME THAT STILL CONTAINS THE QUERY - the one whose every word the query said.
    shortest = min(len(normalise(row["name"])) for row in hits)
    finalists = [row for row in hits if len(normalise(row["name"])) == shortest]
    if len(finalists) == 1:
        return finalists[0], "substring, least qualified of %d" % len(hits)
    raise SystemExit("%r matches %d images of the same length, which is not a choice:\n%s"
                     % (want, len(finalists), table(rows)))


def table(rows):
    width = max([len(r["name"]) for r in rows] + [5])
    lines = ["  %-5s  %-*s  %s" % ("INDEX", width, "NAME", "FLAGS")]
    for row in rows:
        lines.append("  %-5d  %-*s  %s" % (row["index"], width, row["name"], row["flags"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("medium", help="a Windows ISO, or an install.wim / install.esd")
    ap.add_argument("--want", default="",
                    help="select the image whose NAME matches this, and print only its index")
    ap.add_argument("--json", action="store_true", help="the whole table as JSON")
    ap.add_argument("--name", action="store_true",
                    help="with --want: print the image's FULL name instead of its index, for an "
                         "answer file that selects by /IMAGE/NAME")
    args = ap.parse_args()

    if not os.path.isfile(args.medium):
        raise SystemExit("%s does not exist" % args.medium)

    lower = args.medium.lower()
    rows = read_wim(args.medium if lower.endswith((".wim", ".esd")) else find_image(args.medium))

    if not rows:
        raise SystemExit("%s holds a WIM with no images at all" % args.medium)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if args.want:
        row, how = select(rows, args.want)
        # THE INDEX AND THE REASON GO TO DIFFERENT STREAMS, because a caller substitutes the first
        # into an answer file and a person reads the second.
        if args.name:
            # THE FULL NAME, NOT THE QUERY THAT FOUND IT. `/IMAGE/NAME` is compared for EQUALITY by
            # Setup, so a substring like "IoT Enterprise LTSC" matches no image at all even though it
            # selected one here. MEASURED: the query hit the right row and the answer file was written
            # with the query, which would have stopped Setup on its image picker.
            print(row["name"])
        else:
            print("%d" % row["index"])
        print("  %r is index %d by %s match" % (row["name"], row["index"], how), file=sys.stderr)
        return 0

    print(table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
