import json
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.progress import track as progress_tracks
from rich.prompt import Prompt
from rich.table import Table
from yt_dlp import YoutubeDL

from moises_sync.moises import attach_files, open_upload

console = Console(markup=False)


class DownloadLogger:
    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        console.print(f"Warning: {message}", style="yellow")

    def error(self, message: str) -> None:
        # yt-dlp also raises DownloadError; the CLI prints it once.
        pass


def youtube_options() -> dict:
    runtimes = {name: {"path": path} for name in ("deno", "node") if (path := shutil.which(name))}
    if not runtimes:
        raise ValueError("YouTube needs Deno 2.3+ or Node.js 22+. Install one and retry.")
    return {
        "js_runtimes": runtimes,
        "quiet": True,
        "noprogress": True,
        "color": "never",
        "logger": DownloadLogger(),
    }


def save(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def audio_stem(track: dict) -> str:
    label = f"{' & '.join(track['artists'])} - {track['name']}"
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", label)
    label = re.sub(r"\s+", " ", label).strip(" .")[:160]
    return label or track.get("spotify_id", "track")


def tag_audio(path: Path, track: dict) -> None:
    try:
        tags = EasyID3(path)
    except ID3NoHeaderError:
        tags = EasyID3()
        tags.save(path)
        tags = EasyID3(path)
    tags["title"] = [track["name"]]
    tags["artist"] = track["artists"]
    tags.save()


def name_existing_downloads(path: Path, data: dict) -> None:
    folder = Path("downloads").resolve()
    claimed: set[Path] = set()
    changed = False
    for track in data["tracks"]:
        source = Path(track["mp3"]) if track.get("mp3") else None
        if source is None or not source.is_file():
            continue
        destination = folder / f"{audio_stem(track)}.mp3"
        if destination in claimed or (destination.exists() and destination != source):
            suffix = track.get("spotify_id", "track")[-6:]
            destination = folder / f"{audio_stem(track)} ({suffix}).mp3"
            duplicate = 2
            while destination in claimed or (destination.exists() and destination != source):
                destination = folder / f"{audio_stem(track)} ({suffix}-{duplicate}).mp3"
                duplicate += 1
        if source != destination:
            source.rename(destination)
            track["mp3"] = str(destination)
            changed = True
        video_id = parse_qs(urlparse(track.get("youtube_url", "")).query).get("v", [None])[0]
        if video_id and track.get("youtube_id") != video_id:
            track["youtube_id"] = video_id
            changed = True
        tag_audio(destination, track)
        claimed.add(destination)
    if changed:
        save(path, data)


def match_tracks(path: Path, data: dict) -> None:
    with YoutubeDL({**youtube_options(), "extract_flat": True, "skip_download": True}) as ydl:
        for track in data["tracks"]:
            if track.get("youtube_url"):
                continue
            query = f"{' '.join(track['artists'])} {track['name']}"
            result = ydl.extract_info(f"ytsearch10:{query}", download=False)
            entries = list((result or {}).get("entries", []))
            spotify_seconds = track.get("duration_ms", 0) / 1000
            if spotify_seconds:
                entries.sort(
                    key=lambda entry: (
                        entry.get("duration") is None,
                        abs(entry["duration"] - spotify_seconds)
                        if entry.get("duration") is not None
                        else float("inf"),
                    )
                )
            table = Table(title=query)
            table.add_column("#", style="cyan")
            table.add_column("Recording")
            table.add_column("Seconds")
            table.add_column("Δ from Spotify")
            table.add_column("URL")
            for number, entry in enumerate(entries, 1):
                seconds = entry.get("duration")
                delta = (
                    f"{abs(seconds - spotify_seconds):.0f}s"
                    if seconds is not None and spotify_seconds
                    else "—"
                )
                table.add_row(
                    str(number),
                    entry["title"],
                    str(seconds if seconds is not None else "—"),
                    delta,
                    entry.get("url", ""),
                )
            console.print(table)
            if duration := track.get("duration_ms"):
                console.print(f"Spotify duration: {duration / 1000:.0f} seconds")
            choice = Prompt.ask(
                "Choose a recording (Enter to skip)",
                choices=["", *[str(i) for i in range(1, len(entries) + 1)]],
                default="",
                show_choices=False,
                console=console,
            )
            if not choice:
                continue
            entry = entries[int(choice) - 1]
            track["youtube_url"] = f"https://www.youtube.com/watch?v={entry['id']}"
            save(path, data)


def download_tracks(path: Path, data: dict) -> None:
    if not shutil.which("ffmpeg"):
        raise ValueError("Install ffmpeg first (macOS: brew install ffmpeg).")
    folder = Path("downloads").resolve()
    folder.mkdir(exist_ok=True)
    name_existing_downloads(path, data)
    selected = [track for track in data["tracks"] if track.get("youtube_url")]
    if not selected:
        raise ValueError("No recordings selected. Run match first.")
    options = youtube_options()
    for track in progress_tracks(selected, description="Downloading", console=console):
        url = track.get("youtube_url")
        if not url:
            continue
        video_id = parse_qs(urlparse(url).query).get("v", [None])[0]
        if not video_id:
            raise ValueError(f"Could not read a video ID for {track['name']}.")
        stem = audio_stem(track)
        destination = folder / f"{stem}.mp3"
        current = Path(track["mp3"]) if track.get("mp3") else None
        same_download = track.get("youtube_id") == video_id and current == destination
        if destination.exists() and not same_download:
            destination = folder / f"{stem} ({track['spotify_id'][-6:]}).mp3"
        same_download = track.get("youtube_id") == video_id and current == destination
        if same_download and destination.is_file() and destination.stat().st_size > 0:
            tag_audio(destination, track)
            track["mp3"] = str(destination)
            save(path, data)
            continue
        with YoutubeDL(
            {
                **options,
                "format": "bestaudio/best",
                "noplaylist": True,
                "outtmpl": str(destination.with_suffix("")) + ".%(ext)s",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            }
        ) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or "entries" in info:
                raise ValueError("Select a single YouTube video.")
            ydl.process_ie_result(info, download=True)
            if not destination.is_file() or destination.stat().st_size == 0:
                raise ValueError(f"MP3 was not created for {track['name']}.")
            tag_audio(destination, track)
            track["mp3"] = str(destination)
            track["youtube_id"] = video_id
            save(path, data)


def upload_assisted(data: dict) -> None:
    files = list(dict.fromkeys(track["mp3"] for track in data["tracks"] if track.get("mp3")))
    if not files or any(not Path(file).is_file() for file in files):
        raise ValueError("Download tracks first; all listed MP3 files must exist.")
    if len(files) > 5:
        raise ValueError("Moises accepts up to five files at once. Use a smaller setlist.")
    profile = Path(".state/moises-browser")
    profile.mkdir(parents=True, mode=0o700, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile), headless=False, timeout=20_000
            )
        except BrowserError as error:
            message = str(error).splitlines()[0]
            if "Target page, context or browser has been closed" in message:
                raise ValueError(
                    "Moises' saved browser profile is already open. Close the other "
                    "Moises Sync browser window, then retry upload."
                ) from None
            raise ValueError(f"Could not start the Moises browser: {message}") from None
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                field = open_upload(page)
                attach_files(field, files)
            except ValueError:
                console.print("Upload setup stopped. The browser is open for inspection.")
                console.input("Press Enter to close the browser and show the error: ")
                raise
            except BrowserError as error:
                console.print("Moises did not open the upload screen.")
                console.input("Press Enter to close the browser: ")
                message = str(error).splitlines()[0]
                raise ValueError(f"Moises upload setup failed: {message}") from None
            console.print("Files sent to Moises. Watch the browser for processing status.")
            console.input("Press Enter AFTER uploads finish to close the browser: ")
        finally:
            context.close()
