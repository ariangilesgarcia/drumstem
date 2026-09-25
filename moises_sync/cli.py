import json
import os
import shutil
from pathlib import Path
from typing import Annotated

import httpx
import typer
from dotenv import load_dotenv
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright
from rich.table import Table
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from yt_dlp.utils import DownloadError

from moises_sync.spotify import access_token, fetch_tracks, playlist_id
from moises_sync.workflow import (
    console,
    download_tracks,
    match_tracks,
    save,
    upload_assisted,
)

app = typer.Typer(
    help="Move a Spotify setlist into Moises, one recording at a time.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
SetlistOption = Annotated[Path, typer.Option("--setlist", "-s", help="Saved setlist JSON.")]


@app.callback()
def configure() -> None:
    """Load settings from the working directory's .env file."""
    load_dotenv(Path.cwd() / ".env", override=False)


@app.command()
def login() -> None:
    """Connect Spotify in your browser."""
    access_token()
    console.print("Spotify connected.", style="green")


@app.command()
def export(
    playlist: Annotated[str, typer.Argument(help="Spotify playlist URL or ID.")],
    setlist: SetlistOption = Path("setlist.json"),
) -> None:
    """Save the songs from a playlist you own or collaborate on."""
    identifier = playlist_id(playlist)
    if setlist.exists():
        raise ValueError("Setlist already exists. Choose another path with --setlist.")
    token = access_token()
    with (
        console.status("Reading Spotify playlist…"),
        httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=30) as client,
    ):
        tracks = fetch_tracks(client, identifier)
    save(setlist, {"playlist_id": identifier, "tracks": tracks})
    console.print(f"Saved {len(tracks)} songs to {setlist}", style="green")


@app.command()
def match(setlist: SetlistOption = Path("setlist.json")) -> None:
    """Search YouTube and choose the right version of each song."""
    match_tracks(setlist, json.loads(setlist.read_text()))


@app.command()
def download(setlist: SetlistOption = Path("setlist.json")) -> None:
    """Download selected recordings as MP3; reuse completed files."""
    download_tracks(setlist, json.loads(setlist.read_text()))


@app.command()
def upload(setlist: SetlistOption = Path("setlist.json")) -> None:
    """Attach MP3s in Moises; finish submission in the browser."""
    upload_assisted(json.loads(setlist.read_text()))


@app.command()
def status(setlist: SetlistOption = Path("setlist.json")) -> None:
    """Show which songs have a match and a downloaded file."""
    data = json.loads(setlist.read_text())
    table = Table("#", "Artist", "Song", "Progress")
    for track in data["tracks"]:
        downloaded = track.get("mp3") and Path(track["mp3"]).is_file()
        state = (
            "Downloaded" if downloaded else "Matched" if track.get("youtube_url") else "Needs match"
        )
        table.add_row(str(track["position"]), ", ".join(track["artists"]), track["name"], state)
    console.print(table)


@app.command()
def doctor() -> None:
    """Check local tools before starting the workflow."""
    with sync_playwright() as playwright:
        browser_installed = Path(playwright.chromium.executable_path).is_file()
    checks = {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "YouTube JS runtime (Deno 2.3+ or Node 22+)": bool(
            shutil.which("deno") or shutil.which("node")
        ),
        "Spotify client ID": bool(os.environ.get("SPOTIPY_CLIENT_ID")),
        "Playwright Chromium": browser_installed,
    }
    for name, ready in checks.items():
        console.print(
            f"{'OK' if ready else 'Missing'}  {name}",
            style="green" if ready else "yellow",
        )
    if not all(checks.values()):
        raise typer.Exit(1)


def main() -> None:
    try:
        app()
    except (
        ValueError,
        OSError,
        httpx.HTTPError,
        DownloadError,
        BrowserError,
        SpotifyException,
        SpotifyOauthError,
    ) as error:
        console.print(f"Error: {error}", style="red")
        raise SystemExit(1) from None
