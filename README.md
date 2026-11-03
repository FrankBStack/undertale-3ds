# undertale-3ds

An unofficial fan port of UNDERTALE to the Nintendo 3DS.

You build it from your own copy of UNDERTALE.

## Status

UNDERTALE 1.0 beta: coming in early November. The newest build is being measured on every console now, and I'll play the hardest scenes on it myself. The beta goes out once I can't notice lag in them, after a final check.

DELTARUNE: in progress. It comes after UNDERTALE.

## Progress to 1.0

The goal: every scene running at a locked 30 fps on every model.

The bars count the scenes we measure on real consoles that pass, each on the newest build it was measured on. On the New 3DS every scene was measured on a build from 30 October or later. On the older models, about half the scenes were last measured on builds from 27-29 October, and the rest on builds from 30 October to 2 November.

```
New 3DS / New 3DS XL / New 2DS XL   ███████████████████░   99%
3DS                                 ██████████████████░░   92%
2DS                                 ██████████████████░░   88%
Overall                             ███████████████████░   93%
```

A scene passes only when every single frame in play is ready in time, with no dropped frames. Most scenes that fail miss by a single frame here and there, which is hard to notice while playing. That's why the beta is judged by playing the worst scenes.

New 3DS: 70 of 71 measured scenes pass. The one left is the Omega Flowey fight, with a single late frame.

Older models: 65 of 71 measured scenes pass on a 3DS and 64 of 73 on a 2DS (on 29 October: 54 of 69 on a 3DS). Left:

- The Omega Flowey fight
- The ending credits: the spinning circles of text, and on a 2DS also the part where you dodge the names
- Asriel's fight: its start, and saving Undyne during it; on a 2DS also the dream part (last measured on 27 October)
- On a 2DS, one Hotland room, with a single late frame
- One Snowdin scene that dropped no frames but still needs its slowest frame measured
- A final check of every scene

On a 3DS XL, 46 of the 54 scenes measured on it so far pass; 19 scenes haven't been measured on it yet, so it has no bar of its own.

We also measured every room of a full playthrough on recent builds: 595 of 595 rooms pass on a New 3DS, 594 of 595 on a 3DS, 580 of 581 on a 2DS and 595 of 596 on a 3DS XL.

## What changed since the last update (2 November)

- Options: a new Controls page. Each 3DS button can be set to what it does in the game (Confirm, Cancel, Menu, a direction, or nothing), with Default, B confirms and Custom layouts. It won't let you take the last Confirm, Cancel, Menu or Move off your buttons. The Controls row on the main options page showed Default but left and right didn't change it; now they switch between Default and B confirms.
- Older models: entering a battle is shorter again. In our console tests of this build: the battle at the Snowdin ice exit 0.37-0.66 s down to 0.23-0.50 s, Papyrus 0.19-0.23 s down to 0.14-0.17 s, and a Waterfall battle 0.09-0.14 s down to about 0.04 s. In the earlier tests of this change, Asgore's battle (entered with the game's art already cached) went from about 0.29-0.33 s to 0.13-0.14 s.
- Older models: during testing, a 2DS showed one late frame in a Waterfall battle. It didn't happen again when we re-ran that battle four times.

## Setbacks

- Older models: Asgore's first turns can still have two or three single late frames while some of his art loads from the SD card. The fix we planned for this build didn't cover it; a new fix is ready for the next build.
- Older models: in the Omega Flowey fight, the flame attack can still drop a single frame when its sound starts: about 50-57 ms in most of our tests of this build, 72 ms once.
- Older models: the spinning circles of text in the ending credits still drop frames. Each circle's first frame takes about as long as the frame budget allows, so some of them are late.
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
