import os
import re
import secrets
from pathlib import Path

import httpx
from spotipy.oauth2 import SpotifyPKCE


def playlist_id(value: str) -> str:
    match = re.fullmatch(
        r"(?:https://open\.spotify\.com/playlist/|spotify:playlist:)?([A-Za-z0-9]{22})(?:\?[^\s]*)?",
        value,
    )
    if not match:
        raise ValueError("Provide a Spotify playlist URL, URI, or 22-character ID.")
    return match[1]


def access_token() -> str:
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    if not client_id:
        raise ValueError("Set SPOTIPY_CLIENT_ID to your Spotify developer app client ID.")
    state = Path(".state")
    state.mkdir(mode=0o700, exist_ok=True)
    cache = state / "spotify-token.json"
    auth = SpotifyPKCE(
        client_id=client_id,
        redirect_uri="http://127.0.0.1:8888/callback",
        scope="playlist-read-private playlist-read-collaborative",
        state=secrets.token_urlsafe(32),
        cache_path=str(cache),
    )
    try:
        return auth.get_access_token()
    finally:
        if cache.exists():
            cache.chmod(0o600)


def fetch_tracks(client: httpx.Client, identifier: str) -> list[dict]:
    url = f"https://api.spotify.com/v1/playlists/{identifier}/items?limit=50"
    tracks = []
    position = 0
    while url:
        if not url.startswith("https://api.spotify.com/v1/"):
            raise ValueError("Unexpected Spotify pagination URL.")
        response = client.get(url)
        if response.status_code == 403:
            raise ValueError(
                "Spotify denied access. Check Premium, app user access, and playlist "
                "ownership/collaboration."
            )
        if response.status_code == 429:
            raise ValueError(
                f"Spotify rate limit; retry after {response.headers.get('retry-after')}s."
            )
        response.raise_for_status()
        page = response.json()
        for entry in page["items"]:
            position += 1
            track = entry.get("item", entry.get("track"))
            if not track or track.get("type") != "track" or not track.get("id"):
                continue
            tracks.append(
                {
                    "position": position,
                    "spotify_id": track["id"],
                    "name": track["name"],
                    "artists": [artist["name"] for artist in track["artists"]],
                    "duration_ms": track.get("duration_ms"),
                    "youtube_url": None,
                }
            )
        url = page.get("next")
    return tracks
