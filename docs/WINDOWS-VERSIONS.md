# Windows, and which versions this repository will boot

## What is supported

| family | architecture | ISO | walk directory | install workflow | published tag |
|---|---|---|---|---|---|
| `win11` | x64 | `Win11_25H2_English_x64_v2.iso` | `11/` | `windows11-install.yml` | `windows11` |
| `win10` | x64 | `Win10_22H2_English_x64v1.iso` | `10/` | `windows10-install.yml` | `windows10` |
| `win11iot-ltsc` | x64 | `CLIENT_IOT_LTSC_EVAL_x64` | `ltsc/` | `windows11iot-ltsc-install.yml` | `windows11iot-ltsc` |
| `win2025` | x64 | `SERVER_EVAL_x64FRE_en-us` | `2025/` | `windows2025-install.yml` | `windows2025` |

**EVERY INSTALL IS ITS OWN WORKFLOW FILE, AND NONE OF THEM HAS A MATRIX.** A dispatch runs one family;
there is no `strategy:` anywhere in the five files and no `needs:` between them. The reason is that a
matrix makes five unrelated installs look like one job - they share no artifact, no tag and no
conviction - and a family that stops on a dialog it does not know should not be visible as a row that
cancelled four others.

`scripts/fetch-windows-iso.py <family>` prints the URL for each, through Microsoft's own pages. It
downloads nothing: the caller decides whether to fetch 5-8 GiB and where to put it.

**ARM64 IS NOT SUPPORTED.** This engine drives `qemu-system-x86_64` and an x86 UEFI firmware; an ARM64
Windows needs a different emulator, AAVMF, `-machine virt` and an ARM64 host for KVM. The medium and the
answer-file half were prepared and then removed rather than left as a stage that could never pass.

## The edition selector is read from the medium, never copied

Every answer file selects WHICH image on the medium to install, and that selection used to be
`__WINDOWS_IMAGE_INDEX__: "6"` - a number that is true of exactly one medium. Measured across the four:

| family | medium's images | how it is selected |
|---|---|---|
| `win11` | Pro at index 6 | `/IMAGE/INDEX`, resolved from the image named "Windows 11 Pro" |
| `win10` | Pro at index 6 | `/IMAGE/INDEX`, resolved from "Windows 10 Pro" |
| `win11iot-ltsc` | one or two | `/IMAGE/INDEX`, resolved from "IoT Enterprise LTSC" |
| `win2025` | named, not numbered | `/IMAGE/NAME` = "Windows Server 2025 SERVERSTANDARD" |

`scripts/wim-editions.py` prints the table out of a medium with `wimlib-imagex info --xml`, and
`scripts/build-answer.sh` joins it to `scripts/build-answer.py`, which renders one answer file from a
`PROFILES` row. **An index is never written by hand**, so a release that reorders its images still
installs the edition whose NAME was asked for.

That is the same shape [dockur/windows](https://github.com/dockur/windows) uses: its client templates
carry no `/IMAGE/INDEX` at all, and `src/image.sh` injects one at run time from
`wimlib-imagex info --xml`. The difference is that this repository resolves it at PUBLISH time, so the
answer CD in ghcr already says which edition it is and the install leg has nothing to look up.

### A substring match prefers the least qualified name

The evaluation medium carries BOTH `Windows 11 IoT Enterprise LTSC 2024 Evaluation` and
`Windows 11 IoT Enterprise LTSC 2024`. A query of `LTSC 2024` hits both, so the shorter name wins: the
query explained all of it, and "Evaluation" is a qualifier nobody asked for. Naming more reaches the
eval image (`LTSC 2024 Evaluation`, one hit). Measured on a synthesised medium carrying exactly that
pair, where a plain first-match rule would have installed the wrong edition.

## The product key selects the edition, and it is per family

| family | key | why |
|---|---|---|
| `win11`, `win10` | `VK7JG-NPHTM-C97JM-9MPGT-3V66T` | the generic Pro install key; selects Professional from a consumer medium and activates nothing |
| `win11iot-ltsc` | `M7XTQ-FN8P6-TTKYV-9D4CC-J462D` | the LTSC evaluation key from Microsoft's Evaluation Center; the Pro key selects nothing on this medium |
| `win2025` | `TVRH6-WHNXV-R9WG3-9XRFY-MY832` | the Server 2025 evaluation key |

The Pro key on an LTSC medium names an edition the disc does not carry, and Setup then stops asking for
one. dockur/windows ships a different key per family for exactly this reason.

## The TPM bypasses are only in the families that check

`BypassTPMCheck` / `BypassSecureBootCheck` exist because `OVMF_CODE_4M.fd` carries no Microsoft Secure
Boot keys, and Windows 11 refuses to install without Secure Boot. **Windows 10 and Server 2025 check
neither**, so their answer files omit the whole `<RunSynchronous>` block - an omitted element, not an
empty one, because the schema wants at least one command.

## What each walk directory differs in, and why it is not a copy

| | `11/` | `10/` | `ltsc/` | `2025/` |
|---|---|---|---|---|
| Setup window gate | `Windows Setup` | `Windows Setup` | `Windows Setup` | **`Windows Server`** |
| quit-dialog gate | `quit` | **`sure`** | `quit` | `quit` |
| reference desktop | 11's | **its own** | its own | **its own** |
| answer CD | `answer-windows11` | `answer-win10` | `answer-win11iot-ltsc` | `answer-win2025` |
| disk | 25 GiB | 25 GiB | 25 GiB | **40 GiB** |

**The quit-dialog gate for Windows 10 is `sure`, not `quit`, and that is deliberately loose.** Windows
11's dialog reads "Are you sure you want to quit?" - measured on this repository's own recording of run
45194828845. Windows 10's Setup is reported to read "...to exit?", and there is no recording of our own
to confirm it. A gate keyed on `quit` would then never open and the dialog would sit through the whole
install, which is the exact failure the sequence exists to prevent. `sure` is the word both sentences
share, the region is the dialog's own text, and the action is gated on "a confirmation asking whether I
am sure" rather than on one verb.

## Why `smoke.walk` IS shared and `ssh.walk` is not

`smoke.walk` asks the console one question - `BdsDxe: starting` - and reads nothing from the picture, so
it is identical for all four and is copied rather than parameterised.

`ssh.walk` compares the top 120 px against `reference/desktop.png`, and every family draws a different
wallpaper and taskbar. So each directory needs its own, **taken from the first install that reaches a
desktop** - which is what the install stage's own recording is for.

`10/steps/reference/desktop.png`, `ltsc/…` and `2025/…` are NOT in the tree yet. Their `ssh.walk`
says so at the top. `ssh` runs after `install`, so nothing is blocked by writing them now, and a
comparison against 11's picture would either fail on a correct desktop or be loosened until it could
not fail.

## Why Windows 10 is resolved at run time rather than pinned

Windows 10 22H2 reached end of support on 2025-10-14, and the public page that used to offer its ISO
now gives Windows visitors a Media Creation Tool instead. **The file is still on Microsoft's servers**,
and the connector's answer is a SIGNED URL:

```
https://software.download.prss.microsoft.com/dbazure/Win10_22H2_English_x64v1.iso
  ?t=67fc0410-...&P1=1795536030&...
```

`P1=1795536030` is 2026-11-24T16:00:30Z, so a literal one in the workflow is a dead link for every run
after tomorrow. That row therefore carries `resolve: win10` instead of `url:`, and
`scripts/fetch-windows-iso.py` mints the URL in the job that uses it. The LTSC and Server rows are
stable `go.microsoft.com/fwlink` redirects and can be written down.

**No digest is pinned for these three**, because the filename behind the link changes at each refresh.
The **length is exact** and a mismatch is a refused push.
