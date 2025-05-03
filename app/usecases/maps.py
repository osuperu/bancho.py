from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime
from typing import Any
from typing import Tuple
from typing import cast
from zipfile import ZipFile

import app.settings
import app.state
from app import utils
from app.constants.gamemodes import GameMode
from app.logging import Ansi
from app.logging import log
from app.objects.beatmap import RankedStatus
from app.objects.player import Player
from app.repositories import maps as maps_repo
from app.repositories import mapsets as mapsets_repo
from app.repositories.maps import Map
from app.repositories.maps import MapServer
from app.usecases import performance


async def resolve_beatmapset(
    bmapset_id: int,
    bmap_ids: list[int],
) -> list[Map] | None:
    if bmapset_id >= 0:
        # Best-case scenario: The client already knows the set_id
        return await maps_repo.fetch_many(
            set_id=bmapset_id,
        )

    # There are 2 possible scenarios now:
    # 1. The user wants to upload a new beatmapset
    # 2. The user wants to update an existing beatmapset, but doesn't know the setId

    # Query existing beatmap_ids that are valid
    valid_bmaps: list[Map | None] = [
        await maps_repo.fetch_one(bmap_id) for bmap_id in bmap_ids if bmap_id >= 0
    ]

    filtered_valid_bmaps = [bmap for bmap in valid_bmaps if bmap is not None]

    if not filtered_valid_bmaps:
        return None

    # Check if all beatmaps are from the same set
    bmapset_ids = {bmap["set_id"] for bmap in filtered_valid_bmaps}

    if len(bmapset_ids) != 1:
        return None

    return filtered_valid_bmaps


async def update_beatmaps(
    bmap_ids: list[int],
    bmapset: list[Map],
) -> list[int]:
    # Get current beatmaps
    current_bmap_ids = [bmap["id"] for bmap in bmapset]

    if len(bmap_ids) < len(current_bmap_ids):
        # Check if beatmap ids are valid & part of the set
        for bmap_id in bmap_ids:
            assert bmap_id in current_bmap_ids

        # Remove beatmaps
        deleted_bmaps = [
            bmap_id for bmap_id in current_bmap_ids if bmap_id not in bmap_ids
        ]

        for bmap_id in deleted_bmaps:
            # TODO: delete plays
            await maps_repo.delete_one(bmap_id)

        # TODO: delete map files from disk

        log(f"Deleted {len(deleted_bmaps)} beatmaps", Ansi.GREEN)
        return bmap_ids

    # Calculate how many new beatmaps we need to create
    required_maps = max(len(bmap_ids) - len(current_bmap_ids), 0)

    # Create new beatmaps
    new_bmap_ids = [
        (
            await maps_repo.create(
                id=await maps_repo.generate_next_beatmap_id(),
                server=MapServer.PRIVATE,
                set_id=bmapset[0]["set_id"],
                status=RankedStatus.Pending,
                md5=hashlib.md5(
                    str(await maps_repo.generate_next_beatmap_id()).encode("utf-8"),
                ).hexdigest(),
                artist=bmapset[0]["artist"],
                title=bmapset[0]["title"],
                version=bmapset[0]["version"],
                creator=bmapset[0]["creator"],
                filename=bmapset[0]["filename"],
                last_update=datetime.now(),
                total_length=bmapset[0]["total_length"],
                max_combo=0,
                frozen=False,
                plays=0,
                passes=0,
                mode=GameMode.VANILLA_OSU,  # TODO
                bpm=bmapset[0]["bpm"],
                cs=0,
                ar=0,
                od=0,
                hp=0,
                diff=0.0,
            )
        )["id"]
        for _ in range(required_maps)
    ]

    log(f"Created {required_maps} new beatmaps", Ansi.GREEN)

    # Return new beatmap ids to the client
    return current_bmap_ids + new_bmap_ids


async def create_beatmapset(
    player: Player,
    bmap_ids: list[int],
) -> tuple[int, list[int]]:
    bmapset_id = await maps_repo.generate_next_beatmapset_id()

    await mapsets_repo.create(
        id=bmapset_id,
        server=MapServer.PRIVATE,
        last_osuapi_check=datetime.now(),
    )

    new_bmaps = [
        await maps_repo.create(
            id=await maps_repo.generate_next_beatmap_id(),
            server=MapServer.PRIVATE,
            set_id=bmapset_id,
            status=RankedStatus.Inactive,
            md5=hashlib.md5(
                str(await maps_repo.generate_next_beatmap_id()).encode("utf-8"),
            ).hexdigest(),
            artist="",
            title="",
            version="",
            creator=player.name,
            filename="",
            last_update=datetime.now(),
            total_length=0,
            max_combo=0,
            frozen=False,
            plays=0,
            passes=0,
            mode=GameMode.VANILLA_OSU,  # TODO
            bpm=0,
            cs=0,
            ar=0,
            od=0,
            hp=0,
            diff=0.0,
        )
        for _ in bmap_ids
    ]

    log(
        f"Created new beatmapset ({new_bmaps[0]["set_id"]} for user {player.name})",
        Ansi.GREEN,
    )

    return new_bmaps[0]["set_id"], [bmap["id"] for bmap in new_bmaps]


async def is_full_submit(bmapset_id: int, osz2_hash: str) -> bool:
    if not osz2_hash:
        # Client has no osz2 it can patch
        return True

    osz2_file = app.state.services.storage.get_osz2(bmapset_id)

    if osz2_file is None:
        # We don't have an osz2 we can patch
        return True

    # Check if osz2 file is outdated
    return osz2_hash != hashlib.md5(osz2_file).hexdigest()


async def duplicate_beatmap_files(files: dict[str, bytes], creator: str) -> bool:
    for filename, content in files.items():
        if not filename.endswith(".osu"):
            continue

        beatmap = await maps_repo.fetch_one(filename=filename)
        if beatmap is not None:
            if beatmap["creator"] != creator:
                return True

        beatmap_hash = hashlib.md5(content).hexdigest()

        beatmap = await maps_repo.fetch_one(md5=beatmap_hash)
        if beatmap is not None:
            if beatmap["creator"] != creator:
                return True

    return False


async def validate_beatmap_owner(
    beatmap_data: dict[str, Any],
    metadata: dict[str, Any],
    player: Player,
) -> bool:
    if metadata.get("Creator") != player.name:
        return False

    for beatmap in beatmap_data.values():
        if beatmap["metadata"]["author"]["username"] != player.name:
            return False

    return True


async def calculate_package_size(files: dict[str, bytes]) -> int:
    buffer = io.BytesIO()
    osz = ZipFile(buffer, "w", zipfile.ZIP_DEFLATED)

    for filename, data in files.items():
        osz.writestr(filename, data)

    osz.close()
    size = len(buffer.getvalue())

    del buffer
    del osz
    return size


async def calculate_size_limit(bmap_length: int) -> int:
    # The file size limit is 10MB plus an additional 10MB for
    # every minute of beatmap length, and it caps at the configured
    # maximum size.
    return int(
        min(
            10_000_000 + (10_000_000 * (bmap_length / 60)),
            app.settings.BSS_BEATMAPSET_MAX_SIZE * 1000000,
        ),
    )


async def update_beatmap_metadata(
    bmapset: list[Map],
    files: dict[str, bytes],
    metadata: dict[str, str | None],
    bmap_data: dict[str, Any],
) -> None:
    log("Updating beatmap metadata", Ansi.LCYAN)

    # Update beatmapset metadata
    [
        await maps_repo.partial_update(
            id=bmap["id"],
            artist=metadata.get("Artist"),  # type: ignore[arg-type]
            title=metadata.get("Title"),  # type: ignore[arg-type]
            creator=metadata.get("Creator"),  # type: ignore[arg-type]
            last_update=datetime.now(),
            status=RankedStatus.Pending,
        )
        for bmap in bmapset
    ]

    bmap_ids = sorted([bmap["id"] for bmap in bmapset])

    assert len(bmap_ids) == len(bmap_data)

    for filename, bmap in bmap_data.items():
        difficulty_attributes = performance.calculate_difficulty(
            files[filename],
            bmap["ruleset"]["onlineID"],
        )

        bmap_id = await resolve_beatmap_id(
            bmap_ids,
            bmap_data,
            filename,
        )

        assert difficulty_attributes is not None
        assert bmap_id is not None

        await maps_repo.partial_update(
            id=bmap_id,
            filename=filename,
            last_update=datetime.now(),
            total_length=round(bmap["length"] / 1000),
            md5=hashlib.md5(files[filename]).hexdigest(),
            version=bmap["difficultyName"] or "Normal",
            mode=bmap["ruleset"]["onlineID"],
            bpm=bmap["bpm"],
            hp=bmap["difficulty"]["drainRate"],
            cs=bmap["difficulty"]["circleSize"],
            od=bmap["difficulty"]["overallDifficulty"],
            ar=bmap["difficulty"]["approachRate"],
            max_combo=difficulty_attributes.max_combo,
            diff=difficulty_attributes.stars,
        )


async def update_beatmap_package(
    bmapset_id: int,
    files: dict[str, bytes],
) -> None:
    log("Updating beatmap package", Ansi.LCYAN)

    allowed_file_extensions = [
        ".osu",
        ".osz",
        ".osb",
        ".osk",
        ".png",
        ".mp3",
        ".jpeg",
        ".wav",
        ".png",
        ".wav",
        ".ogg",
        ".jpg",
        ".wmv",
        ".flv",
        ".mp3",
        ".flac",
        ".mp4",
        ".avi",
        ".ini",
        ".jpg",
        ".m4v",
    ]

    buffer = io.BytesIO()
    zip = ZipFile(buffer, "w", zipfile.ZIP_DEFLATED)

    for filename, data in files.items():
        if not any(filename.endswith(ext) for ext in allowed_file_extensions):
            continue

        zip.writestr(filename, data)

    zip.close()
    buffer.seek(0)

    app.state.services.storage.upload_osz(
        bmapset_id,
        buffer.getvalue(),
    )


async def update_beatmap_thumbnail(
    bmapset_id: int,
    files: dict[str, bytes],
    bmaps: dict[str, Any],
) -> None:
    log("Uploading beatmap thumbnail...", Ansi.LCYAN)

    background_files = [
        bmap["metadata"]["backgroundFile"]
        for bmap in bmaps.values()
        if bmap["metadata"]["backgroundFile"]
    ]

    if not background_files:
        log("Background file not specified. Skipping...", Ansi.YELLOW)
        return

    target_background = background_files[0]

    if target_background not in files:
        log("Background file not found. Skipping...", Ansi.YELLOW)
        return

    thumbnail = utils.resize_and_crop_image(
        files[target_background],
        target_width=160,
        target_height=120,
    )

    # Upload new thumbnail
    app.state.services.storage.upload_beatmap_thumbnail(
        str(bmapset_id),
        thumbnail,
    )


async def update_beatmap_audio(
    bmapset_id: int,
    files: dict[str, bytes],
    bmaps: dict[str, Any],
) -> None:
    log("Uploading beatmap audio preview...", Ansi.LCYAN)
    bmaps_with_audio = [
        bmap for bmap in bmaps.values() if bmap["metadata"]["audioFile"]
    ]

    if not bmaps_with_audio:
        log(f"Audio file not specified. Skipping...")
        return

    target_bmap = bmaps_with_audio[0]
    audio_file = target_bmap["metadata"]["audioFile"]
    audio_offset = target_bmap["metadata"]["previewTime"]

    if audio_file not in files:
        log(f"Audio file not found. Skipping...")
        return

    audio_snippet = utils.extract_audio_snippet(
        files[audio_file],
        offset_ms=audio_offset,
    )

    # Upload new audio
    app.state.services.storage.upload_beatmap_audio(
        str(bmapset_id),
        audio_snippet,
    )


async def update_beatmap_files(files: dict[str, bytes]) -> None:
    log("Updating beatmap files...", Ansi.LCYAN)

    for filename, content in files.items():
        if not filename.endswith(".osu"):
            continue

        bmap = await maps_repo.fetch_one(filename=filename)
        assert bmap is not None

        app.state.services.storage.upload_beatmap_file(
            bmap["id"],
            content,
        )


async def delete_inactive_beatmaps(player: Player) -> None:
    # Delete any inactive beatmaps
    inactive_bmapsets = await maps_repo.fetch_many(
        creator=player.name,
        status=RankedStatus.Inactive,
    )

    # TODO: Remove assets (osz2, osz, bg, mp3, beatmap file) from disk

    # TODO: Delete related data (favourites, ratings, scores)

    for bmapset in inactive_bmapsets:
        await maps_repo.delete_one(bmapset["id"])


async def resolve_beatmap_id(
    bmap_ids: list[int],
    bmap_data: dict[str, Any],
    filename: str,
) -> int:
    bmap_file = bmap_data[filename]

    # Newer .osu version have the beatmap id in the metadata
    bmap_id: int = bmap_file.get("onlineID", -1)
    if bmap_id != -1:
        assert bmap_id in bmap_ids
        return bmap_id

    # Try to get the beatmap id from the filename
    bmap = await maps_repo.fetch_one(filename=filename)
    if bmap is not None:
        bmap_ids.remove(bmap["id"])
        return bmap["id"]

    return bmap_ids.pop(0)


async def patch_osz2(patch_file: bytes, osz2: bytes) -> bytes | None:
    if not app.settings.BSS_OSZ2_SERVICE_URL:
        return None

    response = await app.state.services.http_client.post(
        f"{app.settings.BSS_OSZ2_SERVICE_URL}/osz2/patch",
        files={
            "patch": patch_file,
            "osz2": osz2,
        },
    )

    if not response.status_code == 200:
        return None

    return response.content


async def decrypt_osz2(osz2_file: bytes) -> dict[str, Any] | None:
    if not app.settings.BSS_OSZ2_SERVICE_URL:
        return None

    response = await app.state.services.http_client.post(
        f"{app.settings.BSS_OSZ2_SERVICE_URL}/osz2/decrypt",
        files={
            "osz2": osz2_file,
        },
    )

    if not response.status_code == 200:
        return None

    return cast(dict[str, Any], response.json())
