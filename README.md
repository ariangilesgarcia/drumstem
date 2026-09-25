# StemDeck playlist watcher

A small poller that watches a YouTube Music playlist and submits newly added
videos to StemDeck. A systemd timer runs it every two minutes. SQLite stores
submitted video IDs and StemDeck job statuses, so videos are not submitted
again on later scans.

## Files

- `scripts/stemdeck_playlist_watcher.py` — playlist poller and SQLite state.
- `deploy/stemdeck-playlist-watcher.service` — one-shot systemd service.
- `deploy/stemdeck-playlist-watcher.timer` — runs the service every two minutes.

## Mini PC setup

The service expects StemDeck at `/opt/stemdeck`, with `yt-dlp` and Python in
`/opt/stemdeck/.venv`. Install the script as
`/opt/stemdeck-watcher/stemdeck_playlist_watcher.py` and the systemd units under
`/etc/systemd/system/`. Configure `/etc/default/stemdeck-playlist-watcher`:

```sh
STEMDECK_WATCHER_PLAYLIST_URL='https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID'
# Optional; these are the defaults:
# STEMDECK_WATCHER_API='http://127.0.0.1:8000'
# STEMDECK_WATCHER_YTDLP='/opt/stemdeck/.venv/bin/yt-dlp'
# STEMDECK_WATCHER_STATE='/var/lib/stemdeck-watcher/state.sqlite3'
```

Then enable and start the timer:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now stemdeck-playlist-watcher.timer
```

Check recent scans with:

```sh
sudo systemctl status stemdeck-playlist-watcher.timer
sudo journalctl -u stemdeck-playlist-watcher.service -n 50 --no-pager
```

The service calls StemDeck's local `POST /api/jobs` endpoint. SQLite state is
kept at `/var/lib/stemdeck-watcher/state.sqlite3` on the mini PC.
