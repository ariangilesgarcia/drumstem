#!/usr/bin/env python3
"""Queue newly added videos from a YouTube playlist in StemDeck.

The systemd timer invokes this once per interval. SQLite remembers video IDs
that have already been submitted, so each playlist video is queued at most
once during normal operation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LOG = logging.getLogger("stemdeck_playlist_watcher")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def playlist_entries(url: str, ytdlp: str) -> list[tuple[str, str]]:
    """Return valid video IDs and titles from the configured playlist."""
    result = subprocess.run(
        [
            ytdlp,
            "--dump-single-json",
            "--flat-playlist",
            "--skip-download",
            "--no-warnings",
            "--no-progress",
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        detail = result.stderr.strip() or f"yt-dlp exited {result.returncode}"
        raise RuntimeError(f"could not read playlist: {detail[-1200:]}")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp returned invalid playlist data") from exc

    entries: list[tuple[str, str]] = []
    for item in info.get("entries") or []:
        if not isinstance(item, dict):
            continue
        video_id = str(item.get("id") or "")
        if not VIDEO_ID_RE.fullmatch(video_id):
            continue
        entries.append((video_id, str(item.get("title") or video_id)))
    return entries


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """CREATE TABLE IF NOT EXISTS submissions (
               video_id TEXT PRIMARY KEY,
               title TEXT NOT NULL,
               job_id TEXT,
               status TEXT NOT NULL,
               submitted_at TEXT NOT NULL,
               last_error TEXT
           )"""
    )
    db.commit()
    return db


def submit(api_base: str, video_id: str) -> str:
    body = json.dumps(
        {"url": f"https://www.youtube.com/watch?v={video_id}"}
    ).encode()
    request = Request(
        f"{api_base.rstrip('/')}/api/jobs",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError("StemDeck returned no job_id")
    return job_id


def refresh_job_states(api_base: str, db: sqlite3.Connection) -> None:
    """Mirror active StemDeck job states into SQLite for easy inspection."""
    terminal = ("done", "error", "cancelled", "unavailable", "rejected", "unknown")
    placeholders = ",".join("?" for _ in terminal)
    rows = db.execute(
        f"SELECT video_id, job_id FROM submissions "
        f"WHERE job_id IS NOT NULL AND status NOT IN ({placeholders})",
        terminal,
    ).fetchall()
    for video_id, job_id in rows:
        request = Request(f"{api_base.rstrip('/')}/api/jobs/{job_id}")
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                db.execute(
                    "UPDATE submissions SET status='unknown', last_error=? WHERE video_id=?",
                    ("StemDeck no longer has this job (for example, after a restart)", video_id),
                )
                db.commit()
            else:
                LOG.warning("could not refresh job %s: HTTP %d", job_id, exc.code)
            continue
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            LOG.warning("could not refresh job %s: %s", job_id, exc)
            continue

        status = payload.get("status")
        if isinstance(status, str):
            error = payload.get("error_detail") or payload.get("error")
            db.execute(
                "UPDATE submissions SET status=?, last_error=? WHERE video_id=?",
                (status, str(error) if error else None, video_id),
            )
            db.commit()


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    playlist_url = os.environ.get("STEMDECK_WATCHER_PLAYLIST_URL", "").strip()
    if not playlist_url:
        LOG.error("STEMDECK_WATCHER_PLAYLIST_URL is not set")
        return 2

    ytdlp = os.environ.get(
        "STEMDECK_WATCHER_YTDLP", "/opt/stemdeck/.venv/bin/yt-dlp"
    )
    api_base = os.environ.get("STEMDECK_WATCHER_API", "http://127.0.0.1:8000")
    db_path = Path(
        os.environ.get(
            "STEMDECK_WATCHER_STATE", "/var/lib/stemdeck-watcher/state.sqlite3"
        )
    )

    try:
        entries = playlist_entries(playlist_url, ytdlp)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        LOG.error("playlist scan failed: %s", exc)
        return 1

    LOG.info("found %d videos in the playlist", len(entries))
    db = open_db(db_path)
    queued = 0
    seen_this_scan: set[str] = set()
    try:
        refresh_job_states(api_base, db)
        for video_id, title in entries:
            if video_id in seen_this_scan:
                continue
            seen_this_scan.add(video_id)
            if db.execute(
                "SELECT 1 FROM submissions WHERE video_id = ?", (video_id,)
            ).fetchone():
                continue

            try:
                job_id = submit(api_base, video_id)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code == 503:
                    LOG.warning("StemDeck queue is full; will retry remaining videos next scan")
                    break
                if exc.code < 500:
                    # Invalid or unavailable videos will not change on the next poll.
                    db.execute(
                        """INSERT OR IGNORE INTO submissions
                           (video_id, title, job_id, status, submitted_at, last_error)
                           VALUES (?, ?, NULL, 'rejected', ?, ?)""",
                        (video_id, title, now(), f"HTTP {exc.code}: {detail}"),
                    )
                    db.commit()
                    LOG.error("StemDeck rejected %s (%s): %s", title, video_id, detail)
                    continue
                LOG.warning("temporary StemDeck HTTP %d; will retry next scan", exc.code)
                break
            except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                LOG.warning("could not submit %s (%s): %s; will retry next scan", title, video_id, exc)
                break

            db.execute(
                """INSERT OR IGNORE INTO submissions
                   (video_id, title, job_id, status, submitted_at, last_error)
                   VALUES (?, ?, ?, 'queued', ?, NULL)""",
                (video_id, title, job_id, now()),
            )
            db.commit()
            queued += 1
            LOG.info("queued %s (%s) as StemDeck job %s", title, video_id, job_id)
    finally:
        db.close()

    LOG.info("scan complete; queued %d new video(s)", queued)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
