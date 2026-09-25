# Moises Sync

Python CLI prototype: Spotify playlist metadata → selected YouTube recordings → MP3 → assisted Moises upload.

## Setup

Requires Python 3.12+, uv, and ffmpeg (`brew install ffmpeg` on macOS).
YouTube also needs Node.js 22+ or Deno 2.3+ on PATH. The CLI enables installed
runtimes automatically; `yt-dlp[default]` includes the matching challenge solver.

```sh
uv sync
uv run playwright install chromium
```

Create `.env` in the project directory using `.env.example` as a template:

```dotenv
SPOTIPY_CLIENT_ID=your-client-id
MOISES_USERNAME=your-email
MOISES_PASSWORD=your-password
```

The CLI loads `.env` from the current working directory. Existing environment variables take precedence. `.env` is ignored by Git.

```sh
uv run moises-sync doctor
uv run moises-sync login
```

Create an app in the [Spotify developer dashboard](https://developer.spotify.com/dashboard), register `http://127.0.0.1:8888/callback` as its redirect URI, and allowlist your Spotify account. PKCE requires no client secret. Tokens and the separate Moises browser profile are stored in ignored `.state/`; do not share this directory.

Spotify development mode currently requires the app owner to have Premium and limits playlist contents to playlists you own or collaborate on. See the [migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).

## Workflow

```sh
uv run moises-sync export 'https://open.spotify.com/playlist/PLAYLIST_ID'
uv run moises-sync match
uv run moises-sync status
uv run moises-sync download
uv run moises-sync upload
```

Use `--setlist path.json` after the command for another setlist. Export refuses to overwrite existing work. Match offers ten YouTube candidates, sorted by closeness to Spotify's duration, with the time difference shown. It saves each choice and skips already matched songs. Downloads are named `Artist - Song.mp3`, with matching MP3 artist and title tags; completed downloads are reused for the same YouTube video.

`setlist.json`, downloaded audio, Spotify tokens, and the saved Moises browser session are local files and excluded from Git. `setlist.example.json` shows the expected setlist structure with placeholder data.

Upload launches a separate visible Chromium profile and reuses its Moises session. If login is needed, it uses `MOISES_USERNAME` (your email) and `MOISES_PASSWORD` from `.env`. It opens Moises's embedded uploader, attaches up to five MP3s, and clicks Enviar/Send using the default separation choice. Keep the CLI open while Moises processes the tracks.

## Prototype boundaries

- Moises's signed-in upload frame has been inspected. The CLI starts processing, but it does not record remote completion.
- No automatic playlist refresh, deletion sync, or remote duplicate detection yet. Running upload again can create duplicates.
- Spotify login/export and YouTube downloads need live account/network validation. For YouTube runtime setup, see [yt-dlp requirements](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
- Missing/local tracks and episodes are omitted; supported tracks retain playlist order and duplicate entries.
- Failures stop the current command; saved matches and completed download paths remain available for reruns.
- A later UI can wrap these stages. Unattended Moises automation should follow inspection of the actual upload flow and a reliable completion signal.

## Development

```sh
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```
