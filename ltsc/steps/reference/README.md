# The reference pictures this directory's `ssh.walk` compares against

`desktop.png` IS HERE, and it came from the first install of THIS family that reached a desktop:
2026-11-24, the frame at which `Windows 11 IoT Enterprise LTSC Evaluation` (build 26100) showed its
wallpaper, its centred taskbar and the evaluation watermark in the corner.

Every Windows family draws a different wallpaper and taskbar, so this picture is not shared with
`11/`, `10/` or `2025/` - a comparison against another family's desktop either fails on a correct
desktop or has to be loosened until it cannot fail.

WHAT MAKES IT A DESKTOP RATHER THAN A MENU OR A PROGRESS PAGE, measured: 3134 distinct colours in its
top 120 rows. windows 11's reference carries 3058 there, a firmware menu far fewer, and the OOBE's
"Please keep your computer on" frame is a black field with one line of white text.

`install.walk` uses it as the verdict for `wait for the desktop`, and `ssh.walk` for its own first
step. Both crop the top 120 rows, which is where a desktop is recognisably a desktop and an installer
page is recognisably not.
