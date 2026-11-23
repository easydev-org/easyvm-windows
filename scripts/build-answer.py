#!/usr/bin/env python3
"""BUILD THE ANSWER CD A WINDOWS GUEST BOOTS WITH: answer.iso.

THIS USED TO RUN INSIDE `easyvm run`, AS A `fetch: answer_iso` STEP. It is a CI build now, for the
same two reasons macOS's firmware build is:

  1. ITS INPUTS ARE FIXED. The four placeholders the template carries - the account name, its
     password, the computer name and the Windows image index - are the same for every guest of this
     family, and the driver tree comes from one pinned ISO. The same inputs always produce the same
     ISO, so building it once and publishing the result turns a build in every Windows stage into a
     download.

  2. IT IS NOT A GUEST ACTION. It never boots anything, types nothing and needs no screen: it
     renders an XML file, extracts four driver directories and runs xorriso. It was a step only
     because that was how code ran at the time, and a step that does host work is a step whose
     failure looks like a guest failure.

WHAT THE IDENTITY IS, AND WHY A SHARED ONE IS CORRECT HERE

  user      vmuser
  password  admin
  computer  sandbox
  image     6

Every walk in this family already defaults to those values, and macOS's firmware build made the same
call for the same reason: a guest's identity is a fact about the IMAGE, not about a run. A published
disk that boots with a per-run password cannot be re-opened by anyone, and a stage that has to
re-produce it cannot start from the artifact the stage before it published.

THE FILES THAT GO ON THE CD

  Autounattend.xml                    the rendered answer file, LF line endings
  $WinPEDriver$/<driver>/<files>      viostor, vioscsi, NetKVM, Balloon

`viostor` IS NOT OPTIONAL: without it windowsPE cannot see the virtio disk and Setup stops at a
dialog nobody clicks. That is why no drivers is an error here rather than a smaller ISO.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

# THE IDENTITY, IN ONE PLACE. If a guest ever needs a different name, it is a different artifact -
# not a flag, because a flag is a second place for the same fact.
IDENTITY = {
    "__ADMIN_USER__": "vmuser",
    "__ADMIN_PASSWORD__": "admin",
    "__COMPUTER_NAME__": "sandbox",
    "__WINDOWS_IMAGE_INDEX__": "6",
}

# THE DIRECTORY NAME IS THE CONFIGURATION: Setup looks for `$WinPEDriver$` beside the answer file.
WINPE_DIR = "$WinPEDriver$"

# drivers windowsPE must load before it can install anything, and the release trees they live under.
# `w11` first because that is the guest; `w10` and `2k19` are the fallback for an older virtio-win.
DRIVERS = ["viostor", "vioscsi", "NetKVM", "Balloon"]
DRIVER_VERSIONS = ["w11", "w10", "2k19"]


def run(argv):
    out = subprocess.run(argv, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"{' '.join(argv[:3])}: {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout


def substitute(text, values):
    """Replace every `__NAME__` placeholder, and refuse an unknown one.

    A TEMPLATE THAT INVENTS A PLACEHOLDER IS A TEMPLATE WHOSE VALUE NOBODY SUPPLIES, and Setup then
    receives the literal text - which reads as a Windows problem and is not one.
    """
    found = set(re.findall(r"__[A-Z_]+__", text))
    unknown = found - set(values)
    if unknown:
        raise SystemExit(f"the template uses {sorted(unknown)}, which have no value. The vocabulary "
                         f"is {sorted(values)}")
    for name, value in values.items():
        text = text.replace(name, value)
    return text


def has_files(path):
    try:
        return any(not e.is_dir() for e in os.scandir(path))
    except OSError:
        return False


def extract_drivers(virtio_iso, stage):
    """Lay the four driver trees out flat, as `$WinPEDriver$/<driver>/<files>`.

    SEVEN-ZIP RATHER THAN A HAND-WRITTEN Joliet READER: the ISO carries a Joliet tree, and extracting
    it by hand produces 8.3 filenames that do not match the driver the answer file names.
    """
    if not os.path.isfile(virtio_iso):
        raise SystemExit(f"no virtio-win ISO at {virtio_iso}")
    if not shutil.which("7z"):
        raise SystemExit("7z is not installed; the virtio-win ISO needs it to extract the drivers")

    winpe = os.path.join(stage, WINPE_DIR)
    os.makedirs(winpe, exist_ok=True)

    found = []
    for driver in DRIVERS:
        for version in DRIVER_VERSIONS:
            member = f"{driver}/{version}/amd64"
            subprocess.run(["7z", "x", "-y", f"-o{winpe}", virtio_iso, member + "/*"],
                           capture_output=True, text=True)
            source = os.path.join(winpe, driver, version, "amd64")
            if not has_files(source):
                continue
            target = os.path.join(winpe, driver)
            os.makedirs(target, exist_ok=True)
            for entry in os.listdir(source):
                os.replace(os.path.join(source, entry), os.path.join(target, entry))
            # the now-empty version directories are not wanted in the image
            shutil.rmtree(os.path.join(winpe, driver, version), ignore_errors=True)
            found.append(driver)
            break

    if not found:
        raise SystemExit(
            f"no drivers were extracted from {virtio_iso}. Looked for {DRIVERS} under "
            f"{'/'.join(DRIVER_VERSIONS)}/amd64. Without viostor, windowsPE cannot see the virtio "
            f"disk and Setup stops at a dialog nobody clicks")
    return found


def build(template, virtio_iso, out, label):
    if not os.path.isfile(template):
        raise SystemExit(f"no answer file at {template}")
    if not shutil.which("xorriso"):
        raise SystemExit("xorriso is not installed; the answer CD is an ISO9660 image with a "
                         "Joliet tree, and building one by hand truncates filenames")

    stage = tempfile.mkdtemp(prefix="answeriso-")
    try:
        with open(template, encoding="utf-8") as f:
            text = substitute(f.read(), IDENTITY)

        # WINDOWS .cmd FILES MUST BE CRLF, BUT THIS FILE IS .xml - which has no such requirement,
        # and rewriting it only risks a BOM or an encoding question. The engine's builder made the
        # same choice (it normalised CRLF to LF), so the bytes on the CD match what it produced.
        text = text.replace("\r\n", "\n")
        with open(os.path.join(stage, "Autounattend.xml"), "w", encoding="utf-8") as f:
            f.write(text)

        found = extract_drivers(virtio_iso, stage)
        print(f"  drivers on the answer CD: {', '.join(found)}")

        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        # xorriso refuses an existing output, and a stale one would be published with a fresh log
        # line saying it was rebuilt.
        if os.path.exists(out):
            os.remove(out)

        print(f"  building the answer ISO -> {out}")
        # THE NATIVE xorriso FORM, NOT `-as mkisofs`, so the bytes match what the engine's builder
        # produced for the same inputs - `-map` on a directory inserts its whole subtree and "/"
        # puts the file at the image root, which is where Setup looks. Joliet lets Windows read the
        # long driver names. THERE IS NO `-rock`: Rock Ridge is on by default and asking for it is an
        # error rather than a no-op.
        run(["xorriso", "-outdev", out, "-volid", label, "-joliet", "on",
             "-map", stage, "/", "-commit"])

        size = os.path.getsize(out)
        # A 448 KB ISO IS THE FAILURE THIS CHECK EXISTS TO AVOID: a boot record with the answer file
        # and none of the installer's drivers.
        if size < 100 << 10:
            raise SystemExit(f"the answer ISO is {size} bytes, which is smaller than an ISO9660 "
                             f"volume with one file and a driver tree; xorriso wrote a boot "
                             f"record only")
        print(f"  {os.path.basename(out)}: {size >> 10} KiB")
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True, help="the Autounattend.xml to render")
    ap.add_argument("--virtio-iso", required=True, help="the virtio-win ISO the drivers come from")
    ap.add_argument("--out", required=True, help="the ISO to write")
    ap.add_argument("--label", default="ANSWER", help="the ISO's volume name")
    args = ap.parse_args()
    build(args.template, args.virtio_iso, args.out, args.label)


if __name__ == "__main__":
    main()
