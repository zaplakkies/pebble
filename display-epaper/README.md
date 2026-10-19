# Pebble e-paper board

A LilyGO T5 V2.3.1 (2.13" e-paper, 250×122) that shows each kid's screen time today
and how long ago each of their devices last synced. It reads the server's
`/board.json` (the dashboard as JSON, no login, like the dashboard itself).

```
Mon 19 Oct  17:50                      TennisCourt
Caleb                                   0m / 3h
CalebsLaptop 2d   Calebstablet 8d
dad  (over)                          3h32 / 2h      <- inverted when over the limit
Dads gaming machine 1m   samsung phone 3m
```

- Wakes every 5 minutes, or straight away when the button (IO39) is pressed.
- Joins whichever of the two Wi-Fi networks in `site.h` is strongest where it stands.
  Both reach the server: TennisCourt directly, BananaForReference (the Deco) through NAT.
- If the server can't be reached it keeps showing the last data, with
  "no update since HH:MM" in the top right. Device ages keep counting up meanwhile.
- The top right shows the Wi-Fi network in use, or "battery low" on battery below 3.45 V.
- Full refresh once an hour against e-paper ghosting, partial refreshes in between.

## Building

Same board and panel as `~/workspace/liligot5epaper/epaper-alarm-clock` (flashing this
replaces the alarm clock; that project keeps a backup of the original firmware).

```bash
cp src/site.example.h src/site.h     # server URL and Wi-Fi passwords; not committed
pio run -t upload                    # board on /dev/ttyACM0
pio device monitor                   # shows the network, signal and HTTP errors
```

If the picture is garbled or mirrored, change `EPD_DRIVER` in `platformio.ini`
(see the comment there).
