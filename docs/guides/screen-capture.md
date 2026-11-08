# Count what is on a screen (no OBS needed)

The app can read a monitor directly: a livestream or video playing **fullscreen**, or Fortnite itself. Nothing else to
set up.

1. Play the stream or video **fullscreen** on one of your monitors (in a browser: the player's fullscreen button, or
   theatre mode at the least). For your own game, simply play.
2. In the app: **Video source** -> **Screen 1** / **Screen 2** (the list shows each screen's size; **Refresh** after plugging
   a monitor in) -> **Start counting**.
3. Turn on **Live preview** once to check that the counter sees the game picture with the HUD.

Good to know:

- The counter reads the **whole screen**. The gameplay must fill it: a small player inside a web page (chat, menus and the
  page around it) makes the chest pop-up too small and puts it in the wrong place, and nothing is counted. Tested: a whole
  Twitch page with the player at about half size counted nothing; the same stream fullscreen counted every chest.
- Keep other windows off that screen while counting (a window on top of the pop-up hides it).
- A 16:9 screen works best (1920 x 1080, 2560 x 1440). Other shapes squash the picture.
- Want to count a stream without keeping it on screen? Use the [Livestream URL](livestream-url.md) input instead - it
  reads the stream itself, in the background.
- Playing Fortnite on the same PC while the app reads that screen works technically; read
  [Fair play and compatibility](../../README.md#fair-play-and-compatibility) first.

Then [show the numbers on stream](obs-overlay.md) if you want them in OBS.
