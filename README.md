# undertale-3ds

An unofficial fan port of UNDERTALE to the Nintendo 3DS.

You build it from your own copy of UNDERTALE.

## Status

UNDERTALE 1.0 beta: coming in early November. The newest build is being measured on every console now, and I'll play the hardest scenes on it myself. The beta goes out once I can't notice lag in them, after a final check.

DELTARUNE: in progress. It comes after UNDERTALE.

## Progress to 1.0

The goal: every scene running at a locked 30 fps on every model.

The bars count the scenes we measure on real consoles that pass, each on the newest build it was measured on.

- 3DS and 3DS XL: most scenes were measured on 3 November on our newest test build with the game on the bottom screen, which is how I play (63 of 72 measured scenes on the 3DS, 56 of 73 on the 3DS XL). The rest were measured with the game on the top screen, on builds from 27 October to 3 November.
- New 3DS and 2DS: measured with the game on the top screen. On the New 3DS, every scene on a build from 30 October or later; on the 2DS, about half the scenes on builds from 27-29 October and the rest from 30 October to 3 November.
- The newest test build's code isn't in this repository yet; it comes with the next code update.

```
New 3DS / New 3DS XL / New 2DS XL   ███████████████████░   99%
3DS                                 ███████████████████░   97%
3DS XL                              ███████████████████░   95%
2DS                                 ██████████████████░░   88%
Overall                             ███████████████████░   94%
```

A scene passes only when every single frame in play is ready in time, with no dropped frames. Most scenes that fail miss by a single frame here and there, which is hard to notice while playing. That's why the beta is judged by playing the worst scenes.

New 3DS: 70 of 71 measured scenes pass. The one left is the Omega Flowey fight, with a single late frame.

Older models: 70 of 72 measured scenes pass on a 3DS, 69 of 73 on a 3DS XL and 64 of 73 on a 2DS. Left:

- The Omega Flowey fight, on every model
- The ending credits: on a 3DS, one late frame on the final screen that we can't explain yet; on a 3DS XL, the part where you dodge the names, which runs just over our 30 ms limit (30.1 and 30.8 ms) though no frame is dropped; on a 2DS, the spinning circles of text and the part where you dodge the names (last measured before the newest build)
- Asriel's fight: on a 3DS XL one frame took 41.8 ms in one of two runs, though no frame was dropped; on a 2DS its start, saving Undyne during it, and the dream part (last measured 27-31 October)
- On a 2DS, one Hotland room, with a single late frame
- One Snowdin scene on a 2DS that dropped no frames but still needs its slowest frame measured
- On a 3DS, the dream part of Asriel's fight hasn't been measured yet
- A final check of every scene

We also measured every room of a full playthrough on recent builds: 595 of 595 rooms pass on a New 3DS, 594 of 595 on a 3DS, 580 of 581 on a 2DS and 595 of 596 on a 3DS XL. A second tour of 498 scenes, on a build from 1 November with the game on the top screen, dropped no frames in play on a 2DS, a 3DS or a 3DS XL.

## What changed since the last update (3 November, morning)

This update changes this page only. The code is the same as in the last update.

- 3DS and 3DS XL: we measured our newest test build with the game on the bottom screen. On the 3DS XL, 52 of 53 scenes passed, most of them run twice; on the 3DS, 61 of 63 passed. We then measured the 3DS XL's remaining failures on it too: the ending credits and Asriel's fight no longer drop frames there, but they still go over our 30 ms limit, so they still count as failing.
- 3DS XL: the 19 scenes that had never been measured on it now are, and all 19 pass. The 3DS XL gets its own bar.
- Omega Flowey: in the newest test build, the flame attack no longer drops a frame when its sound starts, in our tests on all three older models.
- Asgore: in the newest test build, the late frames in his first turns are gone in our tests, and his fight passes on a 3DS and a 3DS XL.
- Ending credits on a 3DS: the hitch in the part where you dodge the names didn't show up, and the spinning circles of text passed, in our one run of each on the newest test build.

## Setbacks

- The Omega Flowey fight still drops a few frames on every model, mostly late in the fight on the older models. On the New 3DS it's the only scene left.
- Ending credits on a 3DS: one 67 ms frame on the final screen, and we don't know the cause yet.
- The fixes for Asgore and the Omega Flowey flame attack aren't in this repository's code yet; they come with the next code update.
- Older models: in Asriel's fight, the music cut out once in play-testing when we went to save Alphys. We're still looking into it.

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
