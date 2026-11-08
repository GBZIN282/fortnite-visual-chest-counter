"""
Optional OBS integrations that talk to OBS Studio itself (not through files or a video device).

    websocket.py    a small WebSocket client (standard library only)
    client.py       OBS's built-in WebSocket server (obs-websocket 5, OBS 28+): log in + the few allowed requests
    credentials.py  the OBS WebSocket password in Windows Credential Manager (never in config.toml or a log)
    link.py         the app's "OBS WebSocket" overlay output: copies obs_output/chest_counter.txt into a Text source

All of it is optional and OFF by default. The text files in obs_output/ are always written exactly as before; nothing here
is used by the counting worker or the detector.
"""
