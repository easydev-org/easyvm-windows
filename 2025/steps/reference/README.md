# The reference pictures this directory's `ssh.walk` compares against

`desktop.png` IS NOT HERE YET, and that is a real gap rather than an oversight. Every Windows family
draws a different wallpaper and taskbar, so the picture cannot be borrowed from another directory - a
comparison against the wrong one either fails on a correct desktop or has to be loosened until it
cannot fail.

**It comes from the first install of THIS family that reaches a desktop**, which is what the install
stage's own recording is for: run `windows-install.yml`, take the frame where the desktop is up, and
commit it here as `desktop.png`.

`ssh.walk` is the stage AFTER `install`, so nothing is blocked by the picture being absent - the stage
says so at its first step instead of spending 180 rounds reading `0.0000 similar`.
