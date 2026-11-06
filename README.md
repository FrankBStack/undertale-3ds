# undertale-3ds

![Contributions welcome](https://img.shields.io/badge/contributions-welcome-yellow?style=for-the-badge)

An unofficial fan port of UNDERTALE to the Nintendo 3DS.

> **Not released yet. There is nothing to download or install at the moment.**
>
> **The first release (UNDERTALE 1.0 beta) is planned for early November.** It will come with a builder, a program that builds the port from your game files.

You build it from your own UNDERTALE copy.

## Status

UNDERTALE beta 1.0: 99% there. Squashing the very last few bugs.

DELTARUNE: In progress, chapters 1-5 will be prioritized after UNDERTALE releases.

## Known issues

- When the game is open for a long time, audio caches accumulate which can cause slight stutter in heavy fights (e.g/ Omega Flowey).
- Special Thanks drops a single frame at a single scene.
- A couple of other bugs that have been caught and are being fixed.

## Supported consoles (Every model)

- New 3DS, New 3DS XL, New 2DS XL, 3DS, 3DS XL, 2DS

## Requirements

- UNDERTALE 1.08 for PC, from Steam or GOG
- A Windows, Linux or Mac computer
- A 3DS that can run homebrew, and an SD card

## How it works

A builder app (not available for download yet, will launch with beta 1.0) on your computer locates an UNDERTALE copy and builds a .3dsx or .cia. It also gives you the option to copy your PC saves over.

## FAQ

**Is this piracy?**
No. There are no game code or assets in this repo. The builder constructs all parts of the game from the game files directly.

**What about DELTARUNE?**
Coming after beta 1.0's release, with initial n3ds/n2ds support (older console support will require a significant amount of work, so it will take some time, especially chapters 3-5).

**Something looks or plays differently from the PC version.**
Please open an issue, this port was designed to be 1:1 to the original game. If there are any inconsistencies, please let me know (or open a GitHub issue)!

## How it was made

Most of the code was written with AI models (mainly Claude) under my supervision and direction.

## Who am I?

I'm Ethan. I'm 21 and in my 4th year of Computer Science at UWO (the University of Western Ontario).

I've always loved UNDERTALE and DELTARUNE, and other ports that exist are less performance-oriented, so I figured "why not build the definitive way of playing the game?"

My goals and values for this port were relatively straightforward: keep the game 1:1 pixel identical with the PC version where possible, have high performance (30fps in every fight with 0 visible stuttering or frame drops), offer unique 3ds QOL features, and just generally have it be an amazing, uncompromising experience.

Yes, AI wrote most of the code in this port, and I cannot (and will not try to) change how you might feel about this. All that I will say is I have poured countless hours of my own time into this, and I wouldn't let the fact that it's largely AI assisted taint your view on the overall experience that the port offers.

If you give it a go and it doesn't live up to your expectations, please pass on any suggestions/improvements you might have, I always appreciate feedback in any form. My Discord is 3lit3hax.

This genuinely was a blast to make, and I am extremely proud of how the game runs and feels on both new and old consoles.

## Credits

- UNDERTALE by Toby Fox.
- Engine: a fork of [Butterscotch](https://github.com/ButterscotchRunner/Butterscotch), used under the GNU AGPL v3. Modified from Butterscotch, 2026.
- devkitPro, libctru and citro3d.
- Other libraries: see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

## Disclaimer

Unofficial fan project, not affiliated with or endorsed by Toby Fox, Fangamer, YoYo Games or Nintendo. UNDERTALE is a trademark of Toby Fox. Nintendo 3DS is a trademark of Nintendo.

## Licence

GNU Affero General Public License v3. See [LICENSE](LICENSE).
