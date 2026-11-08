# Count from a Twitch or YouTube livestream URL

Paste the link of a live stream and press **Start counting** - no OBS, no capture card, no Virtual Camera, no browser.
The counter watches the public stream the way viewers get it, a few seconds behind. Your own OBS setup stays exactly as
it is; the counter can even run on another PC.

> **Tested (2026-11-08):** a live Fortnite stream simulcast on Twitch and YouTube - 1280x720 at 60 fps in, 15 pictures
> analysed per second, nothing dropped; both platforms counted the same chests, and every counted chest checked was a real
> "CHEST" pop-up. A **3-hour session** on one streamer (v0.2.1) counted about 500 chests; video arrived in bursts at times,
> without disturbing the session. Not yet measured: exactly how many chests a stream makes it miss (the 3-hour count was
> not checked chest by chest), ad breaks, flaky connections.
>
> Good to know: the counter sees what viewers get - bursts, buffering, ad breaks and stream restarts included. It reconnects
> by itself and keeps your counts; video the platform never delivered cannot be counted (the app tells you when).

## Use it

1. Open **Fortnite Visual Chest Counter.exe**.
2. **Video source** -> **Livestream URL (Twitch / YouTube)**.
3. Paste the link:
   - Twitch: `https://www.twitch.tv/CHANNEL`
   - YouTube: the live video's `https://www.youtube.com/watch?v=...`, or `https://www.youtube.com/@CHANNEL/live`
4. **Start counting**. The stream must be **live** and **public** (not subscriber-only, members-only or age-restricted).
5. Show the numbers on your stream as usual: [OBS overlay guide](obs-overlay.md).

## What to expect

- **A delay of a few seconds to ~15 s.** Twitch and YouTube send video in bursts of several seconds; the counter analyses
  every picture in order, so nothing in a burst is skipped. Counting is complete, just not instant.
- **The stream's picture quality is what counts.** The counter reads 720p (about 20 % of one CPU core to receive and
  decode it). Facecams, overlays or a small gameplay area covering the chest pop-up can make it miss chests.
- **The app always says when the stream is not delivering video:** the status pill and the Live preview switch to
  *Buffering* / *Ad break* (yellow: waiting, normal now and then) or *Reconnecting* / *Stream offline* (red: the
  connection dropped - the app reconnects by itself). The Activity log shows the same in colour, and after a gap a yellow
  line says how many seconds of the stream could not be seen: **chests opened in that part are missing from the count**.
  Counts are always kept, and nothing is counted twice (a reconnect continues at the newest part of the stream).
- Your OBS overlay text is never changed to show these messages.
- **Only one stream at a time**, like every other source.

Advanced (`config.toml`, `[live]`): `source = "stream"`, `url = "..."`, `stream_quality = "720p" | "1080p" | "480p"`
(1080p costs about four times the decoding CPU; 480p is not recommended for small pop-up text).

Problems: [troubleshooting](troubleshooting.md#the-counter-does-not-get-a-picture).
