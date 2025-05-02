from __future__ import annotations

import ctypes
import inspect
import io
import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TypedDict
from typing import TypeVar

import pymysql
from PIL import Image
from pydub import AudioSegment

import app.settings
from app.logging import Ansi
from app.logging import log

T = TypeVar("T")


DATA_PATH = Path.cwd() / ".data"
ASSETS_PATH = Path.cwd() / "assets"


def make_safe_name(name: str) -> str:
    """Return a name safe for usage in sql."""
    return name.lower().replace(" ", "_")


def has_internet_connectivity(timeout: float = 1.0) -> bool:
    """Check for an active internet connection."""
    COMMON_DNS_SERVERS = (
        # Cloudflare
        "1.1.1.1",
        "1.0.0.1",
        # Google
        "8.8.8.8",
        "8.8.4.4",
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        for host in COMMON_DNS_SERVERS:
            try:
                client.connect((host, 53))
            except OSError:
                continue
            else:
                return True

    # all connections failed
    return False


class FrameInfo(TypedDict):
    function: str
    filename: str
    lineno: int
    charno: int
    locals: dict[str, str]


def get_appropriate_stacktrace() -> list[FrameInfo]:
    """Return information of all frames related to cmyui_pkg and below."""
    stack = inspect.stack()[1:]
    for idx, frame in enumerate(stack):
        if frame.function == "run":
            break
    else:
        raise Exception

    return [
        {
            "function": frame.function,
            "filename": Path(frame.filename).name,
            "lineno": frame.lineno,
            "charno": frame.index or 0,
            "locals": {k: repr(v) for k, v in frame.frame.f_locals.items()},
        }
        # reverse for python-like stacktrace
        # ordering; puts the most recent
        # call closest to the command line
        for frame in reversed(stack[:idx])
    ]


def pymysql_encode(
    conv: Callable[[Any, dict[object, object] | None], str],
) -> Callable[[type[T]], type[T]]:
    """Decorator to allow for adding to pymysql's encoders."""

    def wrapper(cls: type[T]) -> type[T]:
        pymysql.converters.encoders[cls] = conv
        return cls

    return wrapper


def escape_enum(
    val: Any,
    _: dict[object, object] | None = None,
) -> str:  # used for ^
    return str(int(val))


def ensure_persistent_volumes_are_available() -> None:
    # create /.data directory
    DATA_PATH.mkdir(exist_ok=True)

    # create /.data/... subdirectories
    for sub_dir in (
        "audio",
        "avatars",
        "logs",
        "osu",
        "osr",
        "osz",
        "osz2",
        "ss",
        "thumbnails",
    ):
        subdir = DATA_PATH / sub_dir
        subdir.mkdir(exist_ok=True)


def is_running_as_admin() -> bool:
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined, no-any-return, unused-ignore]
    except AttributeError:
        pass

    try:
        return ctypes.windll.shell32.IsUserAnAdmin() == 1  # type: ignore[attr-defined, no-any-return, unused-ignore]
    except AttributeError:
        raise Exception(
            f"{sys.platform} is not currently supported on bancho.py, please create a github issue!",
        )


def display_startup_dialog() -> None:
    """Print any general information or warnings to the console."""
    if app.settings.DEVELOPER_MODE:
        log("running in advanced mode", Ansi.LYELLOW)
    if app.settings.DEBUG:
        log("running in debug mode", Ansi.LMAGENTA)

    # running on root/admin grants the software potentally dangerous and
    # unnecessary power over the operating system and is not advised.
    if is_running_as_admin():
        log(
            "It is not recommended to run bancho.py as root/admin, especially in production."
            + (
                " You are at increased risk as developer mode is enabled."
                if app.settings.DEVELOPER_MODE
                else ""
            ),
            Ansi.LYELLOW,
        )

    if not has_internet_connectivity():
        log("No internet connectivity detected", Ansi.LYELLOW)


def has_jpeg_headers_and_trailers(data_view: memoryview) -> bool:
    return data_view[:4] == b"\xff\xd8\xff\xe0" and data_view[6:11] == b"JFIF\x00"


def has_png_headers_and_trailers(data_view: memoryview) -> bool:
    return (
        data_view[:8] == b"\x89PNG\r\n\x1a\n"
        and data_view[-8:] == b"\x49END\xae\x42\x60\x82"
    )


def resize_and_crop_image(image: bytes, target_width: int, target_height: int) -> bytes:
    img = Image.open(io.BytesIO(image))
    image_width, image_height = img.size

    aspect = image_width / float(image_height)
    target_aspect = target_width / float(target_height)

    if aspect > target_aspect:
        # Crop off left and right
        new_width = int(image_height * target_aspect)
        offset = (image_width - new_width) / 2
        box = (offset, 0, image_width - offset, image_height)

    else:
        # Crop off top and bottom
        new_height = int(image_width / target_aspect)
        offset = (image_height - new_height) / 2
        box = (0, offset, image_width, image_height - offset)

    image_buffer = io.BytesIO()
    img = img.crop(box)
    img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    img.convert("RGB").save(image_buffer, format="JPEG")
    return image_buffer.getvalue()


def resize_image(
    image: bytes,
    target_width: int | None = None,
    target_height: int | None = None,
) -> bytes:
    image_buffer = io.BytesIO()

    img = Image.open(io.BytesIO(image))
    img = img.resize((target_width, target_height))
    img.save(image_buffer, format="JPEG")

    return image_buffer.getvalue()


def extract_audio_snippet(
    audio_data: bytes,
    offset_ms: float,
    duration_ms: int = 10000,
    bitrate: str = "64k",
) -> bytes:
    # Load audio and extract snippet
    audio: AudioSegment = AudioSegment.from_file(io.BytesIO(audio_data))
    assert audio is not None

    if offset_ms < 0:
        # Set default offset
        audio_length = audio.duration_seconds * 1000
        offset_ms = audio_length / 2.5

    snippet = audio[offset_ms : offset_ms + duration_ms]

    # Export snippet as mp3
    snippet_buffer = io.BytesIO()
    snippet.export(snippet_buffer, format="mp3", bitrate=bitrate)  # type: ignore
    return snippet_buffer.getvalue()
