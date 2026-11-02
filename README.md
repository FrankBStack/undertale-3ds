# undertale-3ds

An unofficial fan port of UNDERTALE to the Nintendo 3DS.

You build it from your own copy of UNDERTALE.

## Status

UNDERTALE 1.0 beta: coming in early November. The newest build is being measured on every console now, and I'll play the hardest scenes on it myself. The beta goes out once I can't notice lag in them, after a final check.

DELTARUNE: in progress. It comes after UNDERTALE.

## Progress to 1.0

The goal: every scene running at a locked 30 fps on every model.

The bars count the scenes we measure on real consoles that pass. They come from the builds before the newest one (29 October 2026); the newest build is being measured now.

```
New 3DS / New 3DS XL / New 2DS XL   ███████████████████░   97%
3DS / 3DS XL / 2DS                  ████████████████░░░░   78%
Overall                             █████████████████░░░   87%
```

A scene passes only when every single frame in play is ready in time, with no dropped frames. Some scenes that fail miss by a single frame here and there, which is hard to notice while playing. That's why the beta is judged by playing the worst scenes.

New 3DS: 63 of 65 measured scenes pass. The other two (the Omega Flowey finale and one credits scene) dropped no frames, but their single slowest frame still needs measuring.

Older models: 54 of 69 measured scenes pass on a 3DS (45 of 71 on 28 October). Left:

- The Omega Flowey finale
- Asriel's fight, and two of the scenes where you save your friends during it
- Mettaton's opera
- Parts of the fights with Asgore and Mad Dummy
- Lemon Bread in the True Lab
- The ending credits
- The end of Undyne's bridge in Waterfall
- One Snowdin scene that dropped no frames but still needs its slowest frame measured
- A final check of every scene

Asriel, Mad Dummy and Lemon Bread were measured before the 29 October sound fix, and Asgore before the 30 October changes.

We also measured every room of a full playthrough on the older models, on an earlier build: 589 of 595 rooms pass on a 3DS.

## What changed since the last update (1 November)

- Older models: loading into a battle is much shorter. In our console tests: the battle at the Snowdin ice exit about 1.0-1.5 s down to 0.5-0.8 s, Papyrus 0.45-0.67 s down to 0.2-0.26 s, and a Waterfall battle 0.3-0.5 s down to 0.09-0.16 s.
- Older models: the slowest frame during the Omega Flowey fight (before the ending's load) is lower: 2DS 70 to 50 ms, 3DS 65 to 51 ms, 3DS XL 56 to 53 ms. A locked 30 needs about 33 ms or less.
- Older models: in our console tests, the fights with Asgore, Undyne, Sans and Mettaton EX ran at a locked 30 on all three models, apart from the one Asgore hitch below.
- FPS counter: with the game on the bottom screen and the counter on the top, black lines no longer flicker through the counter.
- The dialogue box at a save point no longer lingers for a moment over the SAVE menu. We first saw it at a Waterfall save point.
- The red pixels around the last Froggit in the ending credits: the builder now cleans up that art when it prepares the game. This should hide them, but it isn't a full fix, and we haven't confirmed it on a console yet.
- The alarm-timing fix mentioned last time is in this build.

## Setbacks

- Older models: the Asgore fight has one hitch near its start, when its art loads for the first time. The fix is planned for the next build.
- Older models: the Omega Flowey fight still drops frames for a second or two after the 2nd SOUL.
- Older models: the spinning circles of text in the ending credits still drop frames.
- Older models: in Asriel's fight, the music cut out once in play-testing when we went to save Alphys. We're looking into it.

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
