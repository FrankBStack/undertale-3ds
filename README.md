# undertale-3ds

> **Not released yet. There is nothing to download or install yet.**
>
> **The first release (UNDERTALE 1.0 beta) is planned for early November.** It comes with the builder, a program that builds the port from your own copy of UNDERTALE and installs it. Until then, this repository is the source code only.

An unofficial fan port of UNDERTALE to the Nintendo 3DS.

You build it from your own copy of UNDERTALE.

## Status

UNDERTALE 1.0 beta: The newest build is being measured on every console now, and I'll play the hardest scenes on it myself. The beta goes out once I can't notice lag in them, after a final check.

DELTARUNE: in progress. It comes after UNDERTALE.

## Progress to 1.0

The goal: every scene running at a locked 30 fps on every model.

```
New 3DS / New 3DS XL / New 2DS XL   ███████████████████░   99%
3DS                                 ███████████████████░   97%
3DS XL                              ███████████████████░   95%
2DS                                 ██████████████████░░   88%
Overall                             ███████████████████░   94%
```

A scene passes only when every single frame in play is ready in time, with no dropped frames. Most scenes that fail miss by a single frame here and there, which is hard to notice while playing. That's why the beta is judged by playing the worst scenes.

New 3DS: 70 of 71 measured scenes pass.

Older models: 70 of 72 measured scenes pass on a 3DS, 69 of 73 on a 3DS XL and 64 of 73 on a 2DS.

## Known issues

- On older models, some heavy battles and the ending credits can slow down.
- On older models, some sounds can start late or briefly interrupt play; songs in Mettaton's opera can start about a fifth of a second late.
- On older models, opening the Rosalina menu while the game runs can freeze the console. Save before using it.
- Smart smoothing can lose fine lines in some large artwork, such as Mettaton NEO, Asriel's wings and Asgore's cape.
- Opening Options lets the music fade out instead of stopping at once, and a sound that was playing can be cut off or play twice afterwards.
- A few stray red pixels can appear around the last Froggit in the ending credits. This build should hide them; we haven't confirmed it on a console yet.
- Rarely, an older model can crash when you press HOME, and a 2DS can freeze or crash around Asriel's fight or the ending credits. We're looking into it. Save first.

## Supported consoles

- New 3DS, New 3DS XL, New 2DS XL
- 3DS, 3DS XL, 2DS

## What you need

- UNDERTALE 1.08 for PC, from Steam or GOG
- A Windows, Linux or Mac computer
- A 3DS that can run homebrew, and an SD card (freshly formatted, with plenty of free space, is best)

## How it works

A small builder app on your computer finds your copy of UNDERTALE and builds a .3dsx or .cia for your console. It can also bring your PC save over. Your copy of the game stays yours, so please don't share the files it makes.

## FAQ

**Is this piracy?**
No. Nothing from the game is here. The builder only works with a copy you own.

**What about DELTARUNE?**
Later, in its own repository, starting with the New 3DS models.

**Something looks or plays differently from the PC version.**
Please open an issue with your console model and where it happened.

## How it was made

Most of the code was written with AI models (mainly Claude) under my supervision and direction.

## Who am I?

Hi, I'm Ethan. I'm 21 and in my fourth year of Computer Science at Western University (the University of Western Ontario).

UNDERTALE and DELTARUNE mean a lot to me, and I wanted to play them on the 3DS. So I made this.

Yes, a lot of this port was built with AI assistance. That doesn't mean it was rushed. Every room, font and sprite was checked against the original, down to the sub-pixel, so it looks and feels right on the 3DS's small screens. It was made with a lot of love and care.

I hope you enjoy playing it as much as I enjoyed making it.

If you want to say hi or tell me what you think, please don't hesitate to reach out; my Discord is 3lit3hax.

## Credits

- UNDERTALE by Toby Fox.
- Engine: a fork of [Butterscotch](https://github.com/ButterscotchRunner/Butterscotch), used under the GNU AGPL v3. Modified from Butterscotch, 2026.
- devkitPro, libctru and citro3d.
- Other libraries: see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

## Disclaimer

Unofficial fan project, not affiliated with or endorsed by Toby Fox, Fangamer, YoYo Games or Nintendo. UNDERTALE is a trademark of Toby Fox. Nintendo 3DS is a trademark of Nintendo.

## Licence

GNU Affero General Public License v3. See [LICENSE](LICENSE).
