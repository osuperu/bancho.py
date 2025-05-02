from __future__ import annotations

import os

from app.logging import Ansi
from app.logging import log
from app.utils import ASSETS_PATH
from app.utils import DATA_PATH


class Storage:
    def get_file_content(self, filepath: str) -> bytes | None:
        try:
            with open(f"{DATA_PATH}/{filepath}", "rb") as f:
                return f.read()
        except Exception as e:
            log(f'The file "{filepath}" doesn\'t exist', Ansi.YELLOW)
            return None

    def get_file_content_2(self, filepath: str) -> bytes | None:
        try:
            with open(f"{ASSETS_PATH}/{filepath}", "rb") as f:
                return f.read()
        except Exception as e:
            log(f'The file "{filepath}" doesn\'t exist', Ansi.YELLOW)
            return None

    def save_to_file(self, filepath: str, content: bytes) -> bool:
        try:
            with open(f"{DATA_PATH}/{filepath}", "wb") as f:
                f.write(content)
        except Exception as e:
            log(f'Failed to save file "{filepath}": {e}', Ansi.LRED)
            return False

        return True

    def remove_file(self, filepath: str) -> bool:
        try:
            os.remove(f"{DATA_PATH}/{filepath}")
        except Exception as e:
            log(f'Failed to file "{filepath}": "{e}"', Ansi.LRED)
            return False

        return True

    def file_exists(self, key: str, extension: str, bucket: str) -> bool:
        return os.path.isfile(f"{DATA_PATH}/{bucket}/{key}.{extension}")

    def get(self, key: str, extension: str, bucket: str) -> bytes | None:
        return self.get_file_content(f"{bucket}/{key}.{extension}")

    def get_2(self, key: str, extension: str, bucket: str) -> bytes | None:
        return self.get_file_content_2(f"{bucket}/{key}.{extension}")

    def save(self, key: str, extension: str, content: bytes, bucket: str) -> bool:
        return self.save_to_file(f"{bucket}/{key}.{extension}", content)

    def remove(self, key: str, extension: str, bucket: str) -> bool:
        return self.remove_file(f"{bucket}/{key}.{extension}")

    def get_beatmap_file(self, id: int) -> bytes | None:
        return self.get(str(id), "osu", "osu")

    def get_replay_file(self, id: int) -> bytes | None:
        return self.get(str(id), "osr", "osr")

    def get_screenshot(self, id: str, extension: str) -> bytes | None:
        return self.get(id, extension, "ss")

    def get_avatar(self, id: str, extension: str) -> bytes | None:
        return self.get(id, extension, "avatars")

    def get_default_avatar(self) -> bytes | None:
        return self.get_2("default_avatar", "jpg", "avatar")

    def get_bancho_default_avatar(self) -> bytes | None:
        return self.get_2("bancho_default_avatar", "png", "avatar")

    def upload_replay(self, id: int, content: bytes) -> bool:
        return self.save(str(id), "osr", content, "osr")

    def upload_avatar(self, id: int, extension: str, content: bytes) -> bool:
        self.remove_avatar(id)
        return self.save(str(id), extension, content, "avatars")

    def upload_beatmap_file(self, id: int, content: bytes) -> bool:
        return self.save(str(id), "osu", content, "osu")

    def upload_screenshot(self, id: str, extension: str, content: bytes) -> bool:
        return self.save(id, extension, content, "ss")

    def remove_avatar(self, id: int) -> None:
        log(f"Removing avatar for user {id}", Ansi.GREEN)
        for ext in ("jpg", "png"):
            if self.file_exists(str(id), ext, "avatars"):
                self.remove(str(id), ext, "avatars")
                break
