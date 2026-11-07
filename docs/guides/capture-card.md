# Dual-PC or console setup with a capture card

For a console (PlayStation, Xbox, Switch), or a gaming PC that should not run OBS: the game goes over HDMI into a capture
card on the streaming PC, and the counter runs there. **Nothing from this project runs on the console or gaming PC.**

> **Testing status:** the counter's side of this setup (OBS Virtual Camera on the streaming PC) is the same as in the
> tested [single-PC](obs-single-pc.md) and [SRT](obs-dual-pc-srt.md) setups, but the whole chain **has not yet been
> tested with a physical capture card**. Gaming PC with OBS on it? The [SRT setup](obs-dual-pc-srt.md) needs no capture
> card and has been tested.

```text
Console / gaming PC -> HDMI -> capture card -> streaming PC: OBS -> scene "ChestDetectorFeed"
                    -> OBS Virtual Camera -> Fortnite Visual Chest Counter -> OBS Text source on your stream
```

## Steps (on the streaming PC)

1. Connect the console or gaming PC's HDMI output to the capture card, and the card to the streaming PC (USB or PCIe), as
   its manual describes. Use the card's passthrough output for your own screen if it has one.
2. In OBS, **Scenes** box: **+** -> name it `ChestDetectorFeed`.
3. **Sources** box: **+** -> **Video Capture Device** -> select your card. If you can, set **Resolution/FPS Type** to
   **Custom** with 1920x1080 or 1280x720 (30 or 60 fps). Make it fill the scene (`Ctrl+F`). Nothing else goes in this scene.
4. Your stream scene needs the card too? Use **Sources** -> **+** -> **Video Capture Device** -> **Add Existing**.
   Many cards can be opened only once, so never add the same card twice as a new source.
5. **Controls** box: **gear** next to **Start Virtual Camera** -> **Output Type** = **Scene**, **Output Selection** =
   **ChestDetectorFeed** -> **Start Virtual Camera**.
6. Open **Fortnite Visual Chest Counter.exe**, keep **OBS Virtual Camera**, click **Start counting**. Check once with
   **Live preview**: the full 16:9 picture with the HUD.
7. Show the numbers on stream: [OBS overlay guide](obs-overlay.md).

## If the picture is black

- **PS5:** Settings -> System -> HDMI -> turn off **Enable HDCP** (protected output cannot be captured).
- Close the card's own software or any other program that uses the card.
- Deactivate and reactivate the source (right-click it -> Properties -> **Deactivate** / **Activate**), or re-select the
  device.

## Advanced: the capture card directly, without OBS

The card also appears in the app's **Video source** list as **Capture device: ...**. Many cards work with only **one**
program at a time, so this does not work while OBS uses the card; it also uses the card's default resolution. If the app
says the device cannot be opened, go back to OBS Virtual Camera. *(Not yet tested with physical cards.)*

Problems: [troubleshooting](troubleshooting.md).
