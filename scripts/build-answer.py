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
#
# THE EDITION SELECTOR IS *NOT* HERE, AND THAT IS THE POINT OF THIS FILE'S SECOND HALF. It used to be
# `__WINDOWS_IMAGE_INDEX__: "6"` - a NUMBER THAT IS TRUE OF ONE MEDIUM. MEASURED across the images this
# repository publishes: Windows 11 consumer has Professional at 6, the IoT LTSC evaluation medium has
# one or two images and 6 is out of range, and Windows Server 2025's install media names its images
# "Windows Server 2025 SERVERSTANDARD" rather than offering a numbered list. So the selector is read
# from the ISO being installed - `scripts/wim-editions.py` - and passed in as `--index` or `--want`.
IDENTITY = {
    "__ADMIN_USER__": "vmuser",
    "__ADMIN_PASSWORD__": "admin",
    "__COMPUTER_NAME__": "sandbox",
}

# WHAT EACH FAMILY'S ANSWER FILE DIFFERS IN, AS DATA RATHER THAN AS FOUR COPIES OF A TEMPLATE.
#
# THE THREE DIFFERENCES THAT ARE NOT COSMETIC:
#
#	product key        Windows 11 Pro's generic install key selects Professional from a consumer
#	                   medium. The SAME key on an LTSC medium selects nothing - the edition it names
#	                   is not on the disc - and Setup stops asking for one. dockur/windows ships a
#	                   different key per family (CGK42-... for 11 IoT LTSC, M7XTQ-... for plain 11 LTSC,
#	                   TVRH6-... for Server 2025) for exactly this reason.
#	labconfig          The TPM/SecureBoot bypasses exist because OVMF_CODE_4M.fd has no Microsoft
#	                   keys. Windows 10 DOES NOT CHECK for either, and writes to LabConfig that
#	                   nothing reads - harmless, but a lie in a file that is supposed to say what
#	                   the guest needs. Server 2025 does not check either.
#	architecture       `processorArchitecture="amd64"` eight times. It stays a placeholder because the
#	                   template is written once and Setup ignores a component whose architecture does
#	                   not match the medium - but EVERY PROFILE HERE IS amd64: ARM64 is out of scope
#	                   (docs/WINDOWS-VERSIONS.md), so `arm64` would be a value nothing produces.
#
# SO THE TEMPLATE CARRIES PLACEHOLDERS AND THIS TABLE FILLS THEM. A fourth release is a fourth row.
PROFILES = {
    # The generic Pro key: it SELECTS an edition from a multi-image consumer medium and activates
    # nothing. Published by Microsoft for exactly this.
    "win11": {
        "key": "VK7JG-NPHTM-C97JM-9MPGT-3V66T",
        "want": "Windows 11 Pro",
        "arch": "amd64",
        "labconfig": True,
        "select": "index",
        # `w11` IS THIS GUEST'S OWN TREE - the one tree that has always worked here.
        "drivers": ["w11", "w10", "2k19"],
    },
    "win10": {
        # Windows 10 22H2's consumer medium carries Pro at index 6 as well, and the same generic key
        # selects it. MEASURED against the medium this repository mirrors.
        "key": "VK7JG-NPHTM-C97JM-9MPGT-3V66T",
        "want": "Windows 10 Pro",
        "arch": "amd64",
        # NO LABCONFIG: Windows 10 has no TPM or Secure Boot requirement, so the bypasses would be
        # registry writes for checks that never run.
        "labconfig": False,
        "select": "index",
        # `w10` FIRST, AND THIS IS THE FIX FOR `boot-critical drivers`. MEASURED on run 45329047801:
        # Setup started and refused `viostor/w11/amd64`, which is compiled against the Windows 11
        # kernel; its .inf excludes Windows 10's build 19045, so windowsPE will not load it and will
        # not install without it. Windows 10's own tree is what the guest can load.
        "drivers": ["w10", "w11", "2k19"],
    },
    "win11iot-ltsc": {
        # THE **IoT** LTSC KEY, WHICH IS NOT THE LTSC KEY, AND THE DIFFERENCE COST A RUN.
        #
        # MEASURED on run 9195696's ltsc leg: Setup came up, applied nothing, and drew
        #
        #	Windows 11 Setup
        #	Windows installation encountered an unexpected error.
        #	Error code: 0x0000A000 - 0x40031
        #
        # 0x40031 IS THE EDITION MISMATCH. The medium this repository mirrors carries exactly one image,
        # and its FLAGS read
        #
        #	1   Windows 11 IoT Enterprise LTSC 2024 Evaluation   IoTEnterpriseSEval
        #
        # - the IoT EVALUATION edition. `M7XTQ-FN8P6-TTKYV-9D4CC-J462D` is the key for Windows 11
        # ENTERPRISE LTSC (no "IoT"), which is a different SKU on a different disc, so Setup found a key
        # that named an edition the medium does not carry and stopped.
        #
        # THE MEDIUM IS AN EVALUATION DISC, SO NO KEY IS SENT. MEASURED: its only image has FLAGS
        # `IoTEnterpriseSEval`, and the retail/IoT key `CGK42-GYN6Y-VD22B-BX98W-J8JXD` still produced
        # `0x0000A000 - 0x40031` - the edition-mismatch code - because that key names a RETAIL IoT
        # edition and the disc carries the EVALUATION one.
        #
        # dockur/windows resolves this the same way: `removeEmbeddedProductKeys` strips the key from
        # generated answer files for `-eval` images, and its own win11x64-iot template ships an EMPTY
        # `<Key />`. An evaluation disc installs without one.
        "key": "",
        "want": "IoT Enterprise LTSC",
        "arch": "amd64",
        "labconfig": True,
        "select": "index",
        # WINDOWS 11 IOT LTSC IS A WINDOWS 11 KERNEL (build 26100), so `w11` is its own tree and the
        # one that belongs on the CD. `w10` is the fallback for a virtio-win ISO old enough to have no
        # `w11` directory at all.
        "drivers": ["w11", "w10", "2k19"],
    },
    "win2025": {
        # SERVER 2025 EVALUATION, AND THEREFORE NO PRODUCT KEY AT ALL.
        #
        # MEASURED: this medium carries four images whose FLAGS all end in `Eval`
        # (ServerStandardEvalCore, ServerStandardEval, ServerDataCenterEvalCore, ServerDataCenterEval).
        # A retail/KMS key - TVRH6-WHNXV-R9WG3-9XRFY-MY832 was the one here - names an edition the
        # disc does not carry, and Setup answers `0x0000A000 - 0x40031` before copying anything. An
        # evaluation disc installs without a key; a key is what the CONSUMER media needs to choose an
        # edition out of several.
        "key": "",
        "want": "Windows Server 2025 SERVERSTANDARD",
        "arch": "amd64",
        # Server does not require TPM or Secure Boot.
        "labconfig": False,
        # BY NAME, NOT BY INDEX. The Server medium's images are named "Windows Server 2025
        # SERVERSTANDARD" and "…SERVERDATACENTER"; the order they appear in is a fact about the
        # build, and a number copied from another release is how a server installs the wrong
        # edition. `/IMAGE/NAME` is compared for equality, which is what a name is for.
        "select": "name",
        # SERVER 2025 IS BUILD 26100 - the SAME KERNEL GENERATION AS WINDOWS 11 - so `w11` is its
        # tree, not `2k19` and not `2k25` (there is no `2k25` in a virtio-win release; the newest
        # server tree is `2k22`). `2k22` is the fallback for a virtio-win old enough to predate `w11`.
        "drivers": ["w11", "2k22", "2k19"],
    },
}

# THE PLACEHOLDER NAMES THE TEMPLATE USES, filled from a profile above and from `--index`/`--want`.
PROFILE_KEYS = ("key", "arch", "labconfig")

# THE FOUR BYPASSES, AS ONE STRING, BECAUSE THE WHOLE ELEMENT IS PRESENT OR ABSENT.
#
# AN EMPTY <RunSynchronous/> IS NOT THE SAME AS NO ELEMENT: the schema wants at least one command, so
# "this family does not need the bypasses" has to delete the element rather than fill it with nothing.
LABCONFIG = r"""      <RunSynchronous>
        <!-- TPM check. NO TPM IS ATTACHED BY DEFAULT and this is what makes that work.
             dockur/windows installs and runs Windows 11 the same way; its own install.sh
             says the secure/TPM path exists only for an install that was aborted, since
             that one has no answer file to bypass with. -->
        <RunSynchronousCommand wcm:action="add">
          <Order>1</Order>
          <Path>reg.exe add "HKLM\SYSTEM\Setup\LabConfig" /v BypassTPMCheck /t REG_DWORD /d 1 /f</Path>
          <Description>Do not stop on the TPM check</Description>
        </RunSynchronousCommand>
        <!-- THE ONE THAT MATTERS: the firmware has no Secure Boot keys. -->
        <RunSynchronousCommand wcm:action="add">
          <Order>2</Order>
          <Path>reg.exe add "HKLM\SYSTEM\Setup\LabConfig" /v BypassSecureBootCheck /t REG_DWORD /d 1 /f</Path>
          <Description>Do not stop on the Secure Boot check</Description>
        </RunSynchronousCommand>
        <!-- RAM. 8 GiB is configured, above the 4 GiB floor, but a smaller bake would
             otherwise fail on a check nobody was looking at. -->
        <RunSynchronousCommand wcm:action="add">
          <Order>3</Order>
          <Path>reg.exe add "HKLM\SYSTEM\Setup\LabConfig" /v BypassRAMCheck /t REG_DWORD /d 1 /f</Path>
          <Description>Do not stop on the RAM check</Description>
        </RunSynchronousCommand>
        <!-- Upgrades from unsupported CPUs. The guest CPU is `-cpu host`, so this is
             relevant only on a host whose model Windows does not list. -->
        <RunSynchronousCommand wcm:action="add">
          <Order>4</Order>
          <Path>reg.exe add "HKLM\SYSTEM\Setup\MoSetup" /v AllowUpgradesWithUnsupportedTPMOrCPU /t REG_DWORD /d 1 /f</Path>
          <Description>Allow an unlisted CPU model</Description>
        </RunSynchronousCommand>
      </RunSynchronous>
"""


def list_members(medium):
    """Every member path on a medium, lower-cased, from `7z l`.

    THE UNFILTERED LISTING IS THE POINT: `p7zip` 16.02 ignores a trailing member argument where 7-Zip
    24/26 honours it, and the ignored form succeeds with no output - so "filter here, match elsewhere"
    is the only shape that behaves the same on both. `-slt` prints one `Path = ...` per member; the
    plain table is the fallback for a build without it.
    """
    out = subprocess.run(["7z", "l", "-ba", "-slt", medium], capture_output=True, text=True)
    if out.returncode != 0:
        out = subprocess.run(["7z", "l", "-ba", medium], capture_output=True, text=True)
        if out.returncode != 0:
            raise SystemExit(f"{medium}: 7z could not list it: {(out.stderr or out.stdout).strip()[:300]}")
    paths = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("Path = "):
            paths.append(line[len("Path = "):].strip().lstrip("./"))
            continue
        parts = line.split()
        if len(parts) >= 6 and (parts[2].isdigit() or parts[3].isdigit()):
            paths.append(" ".join(parts[5:]).strip().lstrip("./"))
    # THE ORIGINAL CASE IS KEPT, because `7z x -i@-` matches the member names as the medium spells
    # them and an ISO's tree is mixed case (`Balloon/w11/amd64/Balloon.inf`). Matching folds case at
    # the comparison instead - see `extract_drivers`.
    return paths


# THE DIRECTORY NAME IS THE CONFIGURATION: Setup looks for `$WinPEDriver$` beside the answer file.
WINPE_DIR = "$WinPEDriver$"

# drivers windowsPE must load before it can install anything, and the release trees they live under.
DRIVERS = ["viostor", "vioscsi", "NetKVM", "Balloon"]

# THE RELEASE TREE IS A FACT ABOUT THE GUEST, NOT A UNIVERSAL PREFERENCE, AND THIS LIST USED TO BE ONE
# ORDER FOR EVERY FAMILY: `w11` first, always. That is why windows11 installed and the other three did
# not.
#
# MEASURED on run 45329047801 (windows10, frame t=1490). Setup started, then drew
#
#	Windows Setup
#	Windows Setup could not install one or more boot-critical drivers.
#	To install Windows, make sure that the drivers are valid, and restart the installation.
#
# and the machine rebooted back into the firmware menu. `viostor/w11/amd64` is compiled against the
# Windows 11 kernel (NT 10.0 build 22000+); its .inf carries a decoration that excludes Windows 10's
# build 19045, so windowsPE refuses it as a boot-critical driver and refuses to install without one.
# The disk is therefore invisible to Setup, which is the same outcome the driver tree exists to prevent.
#
# SO THE ORDER IS PER FAMILY - see PROFILES[...]["drivers"]. The list below is only the set of trees
# this script knows how to look for.
DRIVER_VERSIONS = ["w11", "w10", "2k25", "2k22", "2k19"]


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


def seven_zip_version():
    """The build's own version line, for a failure message that has to name it."""
    try:
        out = subprocess.run(["7z"], capture_output=True, text=True)
        for line in (out.stdout or out.stderr).splitlines():
            if "7-Zip" in line:
                return line.strip()
    except OSError:
        pass
    return "(7z could not be run)"


def members_written(root):
    """Every file currently under a directory, relative to it."""
    for base, _dirs, files in os.walk(root):
        for name in files:
            yield os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/")


def find_tree(root, member_dir):
    """The directory that holds `member_dir`'s files, wherever `7z` decided to put it.

    CASE-INSENSITIVE AND STRUCTURE-AGNOSTIC ON PURPOSE. `7z` writes members under their own paths,
    which differ between builds and between the ISO9660 and Joliet trees: the same four drivers arrive
    as `viostor/w11/amd64/...` from one and as `viostor/w11/amd64/...` from another. What is stable is
    the SHAPE - a directory whose name is `amd64` under a `w11`, `w10` or `2k19` under the driver - so
    the walk looks for that shape rather than for one exact spelling.
    """
    parts = member_dir.split("/")
    if len(parts) != 3:
        return None
    driver, version, leaf = (p.lower() for p in parts)
    for base, dirs, files in os.walk(root):
        if os.path.basename(base).lower() != leaf:
            continue
        parent = os.path.basename(os.path.dirname(base)).lower()
        grand = os.path.basename(os.path.dirname(os.path.dirname(base))).lower()
        if parent == version and grand == driver and any(not os.path.isdir(os.path.join(base, f))
                                                          for f in files):
            return base
    return None


def extract_drivers(virtio_iso, stage, versions=DRIVER_VERSIONS):
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

    # THE MEMBERS ARE LISTED ONCE AND MATCHED HERE, BECAUSE 7z'S OWN MEMBER FILTER IS NOT THE SAME
    # PROGRAM ON EVERY BUILD.
    #
    # MEASURED ON RUN 45218712522: this function extracted nothing at all on an ubuntu runner and said
    # "no drivers were extracted", for a virtio-win ISO whose trees are present. `p7zip` 16.02 - what
    # `apt-get install p7zip-full` gives - answers NOTHING and exit status 0 when `7z x` is given a
    # member pattern it does not apply literally; 7-Zip 24/26 expands `driver/version/amd64/*` and
    # extracts the files. Same command, two answers, and the failing one is silent.
    #
    # So the listing is taken WITHOUT a filter - the same call `wim-editions.py` was fixed to make -
    # and each wanted directory is handed to `7z x` as the list of members that matched it.
    members = list_members(virtio_iso)
    # A LISTING THAT FOUND NOTHING IS SAID OUT LOUD, BECAUSE THE NEXT LINE'S FAILURE IS MISLEADING.
    # "no drivers were extracted" for a medium whose trees are present sends a reader to the driver
    # names; the real question is whether `7z l` could read the ISO at all.
    if not members:
        raise SystemExit(
            "7z listed no members at all from %s, so the driver trees cannot be found.\n"
            "  7z version: %s" % (virtio_iso, seven_zip_version()))

    found = []
    for driver in DRIVERS:
        for version in versions:
            # THE VERSION DIRECTORIES ARE MATCHED AS DIRECTORIES, NOT AS A FILE PREFIX.
            #
            # MEASURED ON RUN 45219352187: this function still extracted nothing on a runner after
            # being rewritten to list the medium first, and the listing was not the problem - the
            # EXTRACTION was. `7z x -i@<list>` is honoured by 7-Zip 26 and quietly does nothing useful
            # on `p7zip` 16.02, and every fallback here then looked for files that had never been
            # written. The medium was never at fault.
            #
            # SO THE EXTRACTION TAKES A DIRECTORY NAME AND NOTHING ELSE. `7z x iso 'dir/*'` is the one
            # form both builds have always honoured, and the files are found afterwards by walking
            # what actually landed rather than by assuming a path.
            member_dir = f"{driver}/{version}/amd64"
            if not any(m.lower() == member_dir.lower() for m in members):
                continue
            before = set(members_written(winpe))
            subprocess.run(["7z", "x", "-y", f"-o{winpe}", f"{member_dir}/*", virtio_iso],
                           capture_output=True, text=True)
            source = find_tree(winpe, member_dir)
            if source is None:
                # SECOND ATTEMPT WITH NO PATTERN AT ALL: `7z x iso` extracts everything, which is
                # slower and cannot be ignored by any build. A virtio-win ISO is 877 MB and this only
                # runs when the patterned form produced nothing.
                subprocess.run(["7z", "x", "-y", f"-o{winpe}", virtio_iso],
                               capture_output=True, text=True)
                source = find_tree(winpe, member_dir)
            if source is None:
                continue
            target = os.path.join(winpe, driver)
            os.makedirs(target, exist_ok=True)
            for entry in os.listdir(source):
                os.replace(os.path.join(source, entry), os.path.join(target, entry))
            # EVERY VERSION DIRECTORY OF THIS DRIVER GOES, not only the one just used: an earlier
            # attempt may have left another, and a stray tree of 8.3 names is a file Setup may pick.
            shutil.rmtree(os.path.join(winpe, driver, version), ignore_errors=True)
            # THE VERSION IS PART OF THE ANSWER, NOT A DETAIL. `fiostor` from `w11` and the same
            # driver from `w10` are different binaries, and a log line that says only "viostor" is
            # the reason a `boot-critical drivers` failure took three runs to localise.
            found.append(f"{driver}({version})")
            break

    if not found:
        # THE DIAGNOSIS IS IN THE MESSAGE, BECAUSE THIS FAILURE HAS THREE POSSIBLE CAUSES AND THEY ARE
        # INDISTINGUISHABLE FROM THE SENTENCE ABOVE. It was "the medium is not readable" twice and
        # "the extraction wrote nothing" once, and each needed a different fix.
        want = [f"{d}/{v}/amd64" for d in DRIVERS for v in versions]
        present = [w for w in want if any(m.lower() == w.lower() for m in members)]
        wrote = sorted(members_written(winpe))
        raise SystemExit(
            "no drivers were extracted from %s.\n"
            "  7z: %s\n"
            "  members listed: %d\n"
            "  the directories it was asked for, and whether the medium has them:\n%s\n"
            "  what the extraction actually wrote (%d file(s)):\n%s\n"
            "  Without viostor, windowsPE cannot see the virtio disk and Setup stops at a dialog "
            "nobody clicks"
            % (virtio_iso, seven_zip_version(), len(members),
               "\n".join("    %-24s %s" % (w, "present" if w in present else "ABSENT") for w in want),
               len(wrote),
               "\n".join("    " + w for w in wrote[:12]) or "    (nothing)"))
    return found


def build(template, virtio_iso, out, label, values, versions=DRIVER_VERSIONS):
    if not os.path.isfile(template):
        raise SystemExit(f"no answer file at {template}")
    if not shutil.which("xorriso"):
        raise SystemExit("xorriso is not installed; the answer CD is an ISO9660 image with a "
                         "Joliet tree, and building one by hand truncates filenames")

    stage = tempfile.mkdtemp(prefix="answeriso-")
    try:
        with open(template, encoding="utf-8") as f:
            text = substitute(f.read(), values)

        # WINDOWS .cmd FILES MUST BE CRLF, BUT THIS FILE IS .xml - which has no such requirement,
        # and rewriting it only risks a BOM or an encoding question. The engine's builder made the
        # same choice (it normalised CRLF to LF), so the bytes on the CD match what it produced.
        text = text.replace("\r\n", "\n")
        with open(os.path.join(stage, "Autounattend.xml"), "w", encoding="utf-8") as f:
            f.write(text)

        found = extract_drivers(virtio_iso, stage, versions)
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
    ap.add_argument("--profile", required=True, choices=sorted(PROFILES),
                    help="which Windows family this answer CD is for: the product key, the "
                         "architecture and whether the TPM bypasses belong in it")
    # THE EDITION SELECTOR COMES FROM THE MEDIUM, NEVER FROM THIS FILE. One of these two is required,
    # because a template with neither leaves Setup on its image-picker page inside an install nobody
    # is watching.
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--index", type=int,
                     help="the /IMAGE/INDEX to install - the number scripts/wim-editions.py "
                          "printed for this ISO")
    sel.add_argument("--want",
                     help="the /IMAGE/NAME to install - used by Server, whose medium names its "
                          "images instead of numbering them")
    args = ap.parse_args()

    profile = dict(PROFILES[args.profile])
    values = dict(IDENTITY)
    # AN EMPTY KEY OMITS THE ELEMENT - see the template's note on 0x40031. `substitute` replaces the
    # placeholder with the string, so `""` leaves a blank line where an evaluation disc wants no key.
    if profile["key"]:
        values["__PRODUCT_KEY_BLOCK__"] = (
            "<ProductKey>\n"
            "            <Key>%s</Key>\n"
            "            <WillShowUI>Never</WillShowUI>\n"
            "          </ProductKey>" % profile["key"])
    else:
        values["__PRODUCT_KEY_BLOCK__"] = ""
    values["__ARCH__"] = profile["arch"]
    # AN EMPTY REPLACEMENT DELETES THE ELEMENT, and that is the whole point: `substitute` replaces
    # the placeholder with the string, so "" leaves a blank line where a family does not need the
    # TPM bypasses - which is what "absent" has to look like in a file this one generates.
    values["__LABCONFIG__"] = LABCONFIG if profile["labconfig"] else ""

    if args.index is not None:
        if args.index < 1:
            raise SystemExit("--index must be 1 or more; %d is not an image index" % args.index)
        # AN INDEX IS A SELECTOR, NOT AN EDITION NAME. Setup matches the number against the medium's
        # own list, so a wrong number installs a different edition or fails - which is why the caller
        # is expected to have got it from wim-editions.py rather than from this repository.
        values["__IMAGE_SELECTOR__"] = (
            "            <MetaData wcm:action=\"add\">\n"
            "              <Key>/IMAGE/INDEX</Key>\n"
            "              <Value>%d</Value>\n"
            "            </MetaData>" % args.index)
        selection = "index %d" % args.index
    else:
        want = args.want.strip()
        if not want:
            raise SystemExit("--want is empty; it must name an image")
        # XML-ESCAPED, because an image name can contain `&` (Windows 11 "IoT Enterprise LTSC" does
        # not, but a localized name may) and an unescaped one is a file Setup cannot parse.
        escaped = (want.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        values["__IMAGE_SELECTOR__"] = (
            "            <MetaData wcm:action=\"add\">\n"
            "              <Key>/IMAGE/NAME</Key>\n"
            "              <Value>%s</Value>\n"
            "            </MetaData>" % escaped)
        selection = "name %r" % want

    print("  profile %s: %s, %s" % (args.profile, profile["key"], selection))
    build(args.template, args.virtio_iso, args.out, args.label, values,
          profile.get("drivers", DRIVER_VERSIONS))


if __name__ == "__main__":
    main()
