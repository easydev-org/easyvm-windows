#!/usr/bin/env python3
"""Print a Windows ISO download URL, through Microsoft's own pages.

    fetch-windows-iso.py win10
    fetch-windows-iso.py win11
    fetch-windows-iso.py win11iot-ltsc          # x64
    fetch-windows-iso.py win11iot-ltsc arm64
    fetch-windows-iso.py win2025

WHY THIS EXISTS: Windows 10 22H2 reached end of support on 2025-10-14, and the public page that used
to hand out its ISO now gives Windows visitors a Media Creation Tool instead. THE FILE IS STILL ON
MICROSOFT'S SERVERS - what went away is one page - so the requests below are the ones that page
itself makes. Nothing here is a mirror or a third-party source.

TWO MECHANISMS, BECAUSE MICROSOFT HAS TWO:

  the download connector   what `software-download/windows10ISO` and `windows11` call. Four requests:
                           a session, an anti-bot token, a SKU for one language, then the URL.

  the Evaluation Center    what the LTSC and Server ISOs are published through. One page listing
                           fwlinks, which are followed by NAME rather than by position.

WHY THE EVALUATION CENTER RESOLVES BY NAME. The first version of this file picked fwlink number 0
for x64 and number 1 for arm64, which is what dockur's script does. MEASURED: on today's pages that
is wrong - the first two fwlinks are a SIGNUP page and a Marketplace page, and the ISOs are further
down. So each candidate is HEADed and its Content-Disposition filename is what selects it:

    win11iot-ltsc x64     CLIENT_IOT_LTSC_EVAL_x64
    win11iot-ltsc arm64   CLIENT_IOT_LTSC_EVAL_A64
    win2025 x64           SERVER_EVAL_x64FRE_en-us       (one per language; en-us is chosen)

THE ONLY ARM64 WINDOWS THIS REPOSITORY SUPPORTS IS `win11iot-ltsc arm64`, AND THAT IS A DECISION
RATHER THAN A LIMITATION OF THE SCRIPT. Microsoft publishes exactly one ARM64 ISO that a virtual
machine can install from - Windows 11 IoT Enterprise LTSC 2024, whose Evaluation Center page carries
`CLIENT_IOT_LTSC_EVAL_A64`. Everything else on ARM64 is either a VHDX (a disk image, not a medium
this build can boot) or a Media Creation Tool: the download connector answers `DownloadType: 2` and
never `1` for `win11arm64`, which is why no ARM64 Pro or Home ISO appears here.

SO THERE IS NO `win11 arm64` AND NO `win2025 arm64`, AND NOTHING SHOULD ADD ONE. Running an ARM64 guest
is a second machine shape - qemu-system-aarch64, `-machine virt`, an AAVMF firmware instead of OVMF,
and `virtio-blk-device` instead of `virtio-blk-pci` - so a second ARM64 row would be a second
untested shape rather than a second ISO. When that shape exists, this is the one image it starts.

MICROSOFT BLOCKS THIS BY IP AND SAYS SO. The connector answers "Sentinel marked this request as
rejected." or "We are unable to complete this request at this time." Both mean the address is on a
list, and neither is worked around: the sentence is printed as itself.

THE USER AGENT MUST NOT SAY WINDOWS. The public page offers a Media Creation Tool to Windows
visitors and a direct ISO to everyone else, so a Windows UA gets a link to a .exe.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid

# The numbers the public download page itself sends. `profile` is that page's build id and
# `ProductEditionId` selects the release; both have been stable for years.
PROFILE = "606624d44113"
ORG_ID = "y6jn8c31"
INSTANCE = "560dc9f3-1aa5-4a2f-b63c-9e18f8d0e175"

CONNECTOR = {
    "win10": {"edition": "2618", "page": "windows10ISO"},
    "win11": {"edition": "3321", "page": "windows11"},
}

# The Evaluation Center pages, and the substring of an ISO's own filename that identifies it.
EVAL_CENTER = {
    "win11iot-ltsc": {
        "page": "windows-11-iot-enterprise-ltsc-eval",
        "x64": "CLIENT_IOT_LTSC_EVAL_x64",
        "arm64": "CLIENT_IOT_LTSC_EVAL_A64",
    },
    "win2025": {
        "page": "windows-server-2025",
        "x64": "SERVER_EVAL_x64FRE_en-us",
    },
}

AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
LANGUAGE = "English"


def get(url, referer=None, limit=1 << 20):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", AGENT)
    req.add_header("Accept", "*/*")
    if referer:
        req.add_header("Referer", referer)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(limit).decode("utf-8", "replace")


def head_name(url):
    """The filename Microsoft serves behind a fwlink, or "" when it is not a file at all."""
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", AGENT)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.headers.get("content-disposition") or ""
    except Exception:
        return ""


def connector(name):
    product = CONNECTOR[name]
    page = "https://www.microsoft.com/en-us/software-download/" + product["page"]
    session = str(uuid.uuid4())

    # 1. register the session, or the connector answers as if it had never heard of it
    get("https://vlscppe.microsoft.com/tags?org_id=%s&session_id=%s" % (ORG_ID, session))

    # 2. the anti-bot challenge: fetch a token, then post it back with the clock in milliseconds
    ov = get("https://ov-df.microsoft.com/mdt.js?instanceId=%s&PageId=si&session_id=%s"
             % (INSTANCE, session))
    token = re.search(r"[?&]w=([A-Fa-f0-9]+)", ov)
    ticks = re.search(r'rticks="\+?([0-9]+)', ov)
    if not token or not ticks:
        sys.exit("the ov-df challenge answered no token; Microsoft changed the page")
    get("https://ov-df.microsoft.com/?session_id=%s&CustomerId=%s&PageId=si&w=%s&mdt=%d&rticks=%s"
        % (session, INSTANCE, token.group(1), int(time.time() * 1000), ticks.group(1)))

    # 3. product edition -> SKU for one language
    sku_json = json.loads(get(
        "https://www.microsoft.com/software-download-connector/api/"
        "getskuinformationbyproductedition?profile=%s&ProductEditionId=%s&SKU=undefined"
        "&friendlyFileName=undefined&Locale=en-US&sessionID=%s"
        % (PROFILE, product["edition"], session), referer=page))
    skus = sku_json.get("Skus") or []
    sku = next((s["Id"] for s in skus if s.get("Language") == LANGUAGE), None)
    if not sku:
        sys.exit("no SKU for %r; the languages offered are %s"
                 % (LANGUAGE, [s.get("Language") for s in skus]))

    # 4. SKU -> the URL. Both rejection sentences are printed rather than retried: they name a
    #    block by address, and repeating the request does not lift it.
    link_json = get(
        "https://www.microsoft.com/software-download-connector/api/"
        "GetProductDownloadLinksBySku?profile=%s&ProductEditionId=undefined&SKU=%s"
        "&friendlyFileName=undefined&Locale=en-US&sessionID=%s"
        % (PROFILE, urllib.parse.quote(sku), session), referer=page)
    if "Sentinel marked this request as rejected" in link_json:
        sys.exit('Microsoft refused this address ("Sentinel marked this request as rejected")')
    if "We are unable to complete your request at this time" in link_json:
        sys.exit('Microsoft refused this address ("unable to complete your request")')

    data = json.loads(link_json)
    options = data.get("ProductDownloadOptions") or []
    # DownloadType 1 is the ISO; 2 is the Media Creation Tool, which this build cannot use.
    url = next((o["Uri"] for o in options if o.get("DownloadType") == 1), None)
    if not url:
        sys.exit("no ISO among the download options (only DownloadType %s); "
                 "Microsoft publishes this edition another way"
                 % [o.get("DownloadType") for o in options])
    return url


def eval_center(name, arch):
    product = EVAL_CENTER[name]
    want = product.get(arch)
    if not want:
        sys.exit("%s has no %s image (it offers: %s)"
                 % (name, arch, ", ".join(k for k in product if k != "page")))

    page = "https://www.microsoft.com/en-us/evalcenter/download-" + product["page"]
    html = get(page)

    candidates = []
    for m in re.finditer(r"https://go\.microsoft\.com/fwlink(?:/p)?/\?[^\"'<>\s]+", html):
        u = m.group(0).replace("&amp;", "&")
        if "clcid=0x409" in u and u not in candidates:
            candidates.append(u)
    if not candidates:
        sys.exit("the Evaluation Center page offered no downloadable fwlink; "
                 "Microsoft changed the page")

    # BY NAME, NOT BY POSITION. See this file's header: position 0 on today's pages is a signup
    # page, and the ISO is several links further down.
    for u in candidates:
        if want in head_name(u):
            return u
    sys.exit("no fwlink on %s serves a file named like %r; Microsoft changed the page"
             % (page, want))


def main():
    names = list(CONNECTOR) + list(EVAL_CENTER)
    if len(sys.argv) < 2 or sys.argv[1] not in names:
        sys.exit("usage: fetch-windows-iso.py {%s} [x64|arm64]" % ",".join(names))
    name = sys.argv[1]
    arch = sys.argv[2] if len(sys.argv) > 2 else "x64"

    if name in CONNECTOR:
        print(connector(name))
    else:
        print(eval_center(name, arch))


if __name__ == "__main__":
    main()
