# easyvm-windows

Walkthroughs and CI for **Windows** guests, driven by
[`easydev-org/easyvm`](https://github.com/easydev-org/easyvm).

## What lives here

`11/`, `10/`, `ltsc/` - one directory per Windows family, each holding the `.walk` files for
`install`, `ssh`, `vm-configure` and `dev`, the PowerShell scripts those stages run inside the guest,
and the reference images they compare against.

`docs/WINDOWS-VERSIONS.md` - which releases are supported, how each one's edition is selected, and why
ARM64 is out of scope.

`scripts/` - the three things that are not a walkthrough:

```sh
scripts/fetch-windows-iso.py <family>               # print the URL, through Microsoft's own pages
scripts/wim-editions.py <iso>                       # the edition table out of a medium
scripts/build-answer.py --profile <family> ...
scripts/build-answer.sh <family> <iso> <virtio.iso> <out.iso>   # the two joined
```

**One workflow file per family, and no matrix anywhere.** Each names its own media and publishes its
own tag, so a dispatch runs exactly one install and nothing else can affect it:

```sh
gh workflow run windows11-install.yml
gh workflow run windows10-install.yml
gh workflow run windows11iot-ltsc-install.yml
```

| file | walk | publishes |
|---|---|---|
| `windows11-install.yml` | `11/` | `windows11` |
| `windows10-install.yml` | `10/` | `windows10` |
| `windows11iot-ltsc-install.yml` | `ltsc/` | `windows11iot-ltsc` |

## What makes these guests different

**The edition selector comes out of the medium.** Every Windows answer file has to say WHICH image on
the disc to install, and the index is not stable across releases: Windows 11's consumer medium has
Professional at 6 and the IoT LTSC evaluation medium has one or two images. So
`artifacts-publish.yml` reads the medium's own `install.wim` with
`wimlib-imagex` while it builds the answer CD, and the CD in ghcr already carries the right selector.
**No index is ever typed by hand.** See `docs/WINDOWS-VERSIONS.md`.

**The product key is per family**, because a key SELECTS an edition: the generic Pro key picks nothing
on an LTSC medium, so Setup stops asking for one.

**The TPM bypasses are only in the families that check for TPM.** Windows 10 checks neither, so its
answer file omits the block rather than writing registry values nothing reads.

## The media is mirrored, not fetched from upstream

A stage pulls its installer image from this repository's ghcr package, never from the publisher:

```sh
gh workflow run artifacts-publish.yml -f which=iso-win10
gh workflow run artifacts-publish.yml -f which=answer-win10
```

Windows 10 is the exception that proves the rule: its URL is a **signed link that expires in a day**, so
the publish row mints it through `scripts/fetch-windows-iso.py` in the job that downloads it, rather
than writing one into the file.

## What lives elsewhere, on purpose

The **engine** - the daemon, the qemu argument builder, the walkthrough interpreter - is in
`easydev-org/easyvm`. The **CI machinery** is too: these workflows call
`easydev-org/easyvm/.github/workflows/stage.yml@v0.0.3-dev`, so the runner setup, the KVM probes and the
publish logic exist once.

Disks pull from and publish to this repository's own ghcr package, `easydev-org/easyvm-windows`, so they
cannot collide with another operating system's.
