# Windows, and which versions this repository will boot

## What is supported

| name | architecture | ISO | comes from |
|---|---|---|---|
| `win11` | x64 | `Win11_25H2_English_x64_v2.iso` | the download connector |
| `win10` | x64 | `Win10_22H2_English_x64v1.iso` | the download connector |
| `win11iot-ltsc` | x64 | `CLIENT_IOT_LTSC_EVAL_x64` | the Evaluation Center |
| `win11iot-ltsc` | **arm64** | `CLIENT_IOT_LTSC_EVAL_A64` | the Evaluation Center |
| `win2025` | x64 | `SERVER_EVAL_x64FRE_en-us` | the Evaluation Center |

`scripts/fetch-windows-iso.py <name> [x64|arm64]` prints the URL for each, through Microsoft's own
pages. It downloads nothing: the caller decides whether to fetch 5-8 GiB and where to put it.

## Why Windows 10 is fetched through an API rather than a download page

Windows 10 22H2 reached end of support on 2025-10-14, and the public page that used to offer its ISO
now gives Windows visitors a Media Creation Tool instead. **The file is still on Microsoft's
servers** - one page went away - so the script makes the four requests that page made: a session, an
anti-bot token, a SKU for one language, then the URL. Nothing here is a mirror.

## Why there is exactly one ARM64 image

`win11iot-ltsc arm64` is the **only** ARM64 Windows a virtual machine can install from. Everything
else on ARM64 is one of two things that cannot boot:

- a **VHDX** - a disk image, not an installation medium
- a **Media Creation Tool** - the download connector answers `DownloadType: 2` and never `1` for
  `win11arm64`

So `win11 arm64` and `win2025 arm64` do not exist, and adding one would be a mistake rather than a
feature. **Do not add another ARM64 row.** Running an ARM64 guest is a second machine shape -
`qemu-system-aarch64`, `-machine virt`, AAVMF instead of OVMF, `virtio-blk-device` instead of
`virtio-blk-pci` - so a second ARM64 row would be a second untested shape, not a second ISO. When
that shape is built, IoT LTSC is the image it starts.

## The two mechanisms, and why both are needed

**The download connector** (`www.microsoft.com/software-download-connector/api/`) is what the public
`windows10ISO` and `windows11` pages call from a browser. It answers a direct ISO - but only to a
visitor whose user agent is **not** Windows, which is why the script sends a Linux one.

**The Evaluation Center** is where the LTSC and Server ISOs live. Its pages list several
`go.microsoft.com/fwlink` URLs, and the script picks one by **the filename its redirect serves**, not
by position: measured on today's pages, position 0 is a signup page and the ISO is several links
further down.

## What Microsoft does to stop this, and what the script does about it

The connector can answer

```
Sentinel marked this request as rejected.
We are unable to complete your request at this time.
```

Both mean the caller's **address** is on a list. The script prints the sentence as itself and exits;
it does not retry, because retrying an address block does not lift it. A CI runner that hits this
needs an egress address Microsoft has not flagged - not a different set of headers.
