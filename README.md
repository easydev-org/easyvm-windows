# easyvm-windows

Walkthroughs and CI for **Windows 11** guests, driven by
[`easydev-org/easyvm`](https://github.com/easydev-org/easyvm).

## What lives here

`11/steps/` - the `.walk` files for `install`, `ssh`, `vm-configure` and `dev`, plus the PowerShell
scripts those stages run inside the guest and the reference images they compare against.

`windows.yml` - the serial chain. Each stage can run on its own with `from_tag`, which names a
published disk:

```sh
gh workflow run windows.yml -f disks_repository=easydev-org/easyvm-windows -f from_tag=windows11-ssh
```

## What lives elsewhere, on purpose

The **engine** - the daemon, the qemu argument builder, the walkthrough interpreter - is in
`easydev-org/easyvm`. The **CI machinery** is too: this workflow calls
`easydev-org/easyvm/.github/workflows/stage.yml@main`, so the runner setup, the KVM probes and the
publish logic exist once.

Disks pull from and publish to this repository's own ghcr package, `easydev-org/easyvm-windows`, so
they cannot collide with another operating system's.
