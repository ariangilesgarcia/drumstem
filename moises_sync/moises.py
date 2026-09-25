import os
import re
from pathlib import Path

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import FrameLocator, Page

PLAY_BUTTON = "Moises Play Icon Play"
UPLOAD_FRAME = 'iframe[src^="https://studio1.moises.ai/upload/split/"]'
UPLOAD_URL = "https://studio.moises.ai/upload/split/3"


def open_upload(page: Page) -> FrameLocator:
    page.goto(UPLOAD_URL, wait_until="domcontentloaded")
    play = page.get_by_role("button", name=PLAY_BUTTON, exact=True)
    email_login = page.get_by_role(
        "button", name=re.compile(r"Continuar con correo electrónico|Continue with email", re.I)
    )
    play.or_(email_login).wait_for(state="visible", timeout=60_000)
    if not play.is_visible():
        username = os.environ.get("MOISES_USERNAME")
        password = os.environ.get("MOISES_PASSWORD")
        if not username or not password:
            raise ValueError("Set MOISES_USERNAME and MOISES_PASSWORD in .env to log into Moises.")
        email_login.click()
        try:
            page.get_by_role(
                "textbox", name=re.compile(r"Ingresa tu correo electrónico|Enter your email", re.I)
            ).fill(username)
            page.locator('input[type="password"]').fill(password)
            page.get_by_role(
                "button", name=re.compile(r"^(Inicia sesión|Log in|Sign in)$", re.I)
            ).click()
            play.wait_for(state="visible", timeout=60_000)
        except BrowserError:
            # Playwright's call log can include filled values.
            raise ValueError(
                "Moises login did not finish. Check your credentials "
                "or complete login in the browser."
            ) from None
    if page.url.rstrip("/") != UPLOAD_URL:
        page.goto(UPLOAD_URL, wait_until="domcontentloaded")
    # Play's uploader is hosted in a separate frame, not in the app shell.
    frame = page.frame_locator(UPLOAD_FRAME)
    field = frame.locator('input[type="file"]')
    field.wait_for(state="attached", timeout=60_000)
    return frame


def attach_files(frame: FrameLocator, files: list[str]) -> None:
    if len(files) > 5:
        raise ValueError("Moises accepts up to five files at once. Use a smaller setlist.")
    if not files or any(not Path(file).is_file() for file in files):
        raise ValueError("Download tracks first; all listed MP3 files must exist.")
    frame.locator('input[type="file"]').set_input_files(files)
    send = frame.get_by_role("button", name=re.compile(r"^(Enviar|Send)$", re.I))
    send.wait_for(state="visible", timeout=60_000)
    if send.count() != 1:
        raise ValueError("Could not identify the Moises submit button.")
    send.click()
