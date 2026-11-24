# The reference pictures this directory's `ssh.walk` compares against

`desktop.png` IS HERE, from the first Windows 10 install of THIS family that reached a desktop:
2026-11-24, the frame showing the Windows 10 wallpaper, its LEFT-ALIGNED taskbar and the `Type here
to search` box.

That left-aligned taskbar is the visible difference from the other three families, and it is why this
picture cannot be borrowed from `11/` or `ltsc/` - a comparison against another family's
desktop either fails on a correct desktop or has to be loosened until it cannot fail.

WHAT MAKES IT A DESKTOP RATHER THAN A MENU OR A PROGRESS PAGE, measured: 2081 distinct colours in its
top 120 rows. windows 11's reference carries 3058 there and ltsc's 3134 - this wallpaper is a smooth
gradient, so it is lower - while a firmware menu has a few dozen and the OOBE frame is one line of
white text on black.

`install.walk` uses it as the verdict for `wait for the desktop`, and `ssh.walk` for its own first
step. Both crop the top 120 rows.
