import json

from typer.testing import CliRunner

from moises_sync.cli import app

runner = CliRunner()


def test_help_lists_workflow():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["login", "export", "match", "download", "upload", "status", "doctor"]:
        assert command in result.output


def test_status_reports_missing_download_as_matched(tmp_path):
    path = tmp_path / "setlist.json"
    path.write_text(
        json.dumps(
            {
                "tracks": [
                    {
                        "position": 1,
                        "artists": ["Artist"],
                        "name": "Song",
                        "youtube_url": "https://www.youtube.com/watch?v=example",
                        "mp3": str(tmp_path / "missing.mp3"),
                    }
                ]
            }
        )
    )
    result = runner.invoke(app, ["status", "--setlist", str(path)])
    assert result.exit_code == 0
    assert "Matched" in result.output
    assert "Downloaded" not in result.output
