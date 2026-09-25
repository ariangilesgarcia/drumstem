import httpx
import pytest

from moises_sync.spotify import fetch_tracks, playlist_id


@pytest.mark.parametrize("prefix", ["", "spotify:playlist:", "https://open.spotify.com/playlist/"])
def test_playlist_id(prefix):
    assert playlist_id(prefix + "a" * 22) == "a" * 22


def test_rejects_non_spotify_url():
    with pytest.raises(ValueError):
        playlist_id("https://example.com/playlist/" + "a" * 22)


def test_pagination_unavailable_and_episode_filtering():
    track = {
        "id": "song",
        "name": "Song",
        "type": "track",
        "artists": [{"name": "Artist"}],
    }
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"item": None},
                        {"item": {"type": "episode"}},
                        {"item": track},
                    ],
                    "next": "https://api.spotify.com/v1/next",
                },
            )
        return httpx.Response(200, json={"items": [{"track": track}], "next": None})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        tracks = fetch_tracks(client, "a" * 22)
    assert len(requests) == 2
    assert [track["position"] for track in tracks] == [3, 4]
    assert tracks[0]["artists"] == ["Artist"]


def test_denied_playlist_has_actionable_error():
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client,
        pytest.raises(ValueError, match="ownership"),
    ):
        fetch_tracks(client, "a" * 22)
