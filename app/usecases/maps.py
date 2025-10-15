from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime
from typing import Any
from typing import Tuple
from typing import cast
from zipfile import ZipFile
from zipfile import ZipInfo

from osz2 import File  # type: ignore[import-untyped]
from osz2 import MetadataType
from osz2 import apply_bsdiff_patch
from slider import Beatmap  # type: ignore[import-untyped]

import app.settings
import app.state
from app import bss
from app import utils
from app.constants.gamemodes import GameMode
from app.logging import Ansi
from app.logging import log
from app.objects.beatmap import RankedStatus
from app.objects.player import Player
from app.osz2 import InternalOsz2
from app.repositories import favourites as favourites_repo
from app.repositories import maps as maps_repo
from app.repositories import mapsets as mapsets_repo
from app.repositories import ratings as ratings_repo
from app.repositories import scores as scores_repo
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
            bmap = await maps_repo.fetch_one(id=bmap_id)
            assert bmap is not None

            await scores_repo.delete_all_in_beatmap(map_md5=bmap["md5"])
            await maps_repo.delete_one(bmap_id)

            app.state.services.storage.remove_beatmap_file(bmap["id"])

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
                mode=GameMode.VANILLA_OSU,
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
            mode=GameMode.VANILLA_OSU,
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
        f"Created new beatmapset ({new_bmaps[0]['set_id']} for user {player.name})",
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


async def duplicate_beatmap_files(
    bmapset: list[Map],
    files: list[File],
) -> bool:
    """Check for duplicate beatmap filenames & checksums"""
    for file in files:
        if not file.filename.endswith(".osu"):
            continue

        beatmap = await maps_repo.fetch_one(filename=file.filename)
        if beatmap:
            if beatmap["creator"] != bmapset[0]["creator"]:
                return True

        file_checksum = hashlib.md5(file.content).hexdigest()

        beatmap = await maps_repo.fetch_one(md5=file_checksum)
        if beatmap:
            if beatmap["creator"] != bmapset[0]["creator"]:
                return True

    return False


def validate_beatmap_owner(
    metadata: dict[MetadataType, str],
    beatmaps: dict[str, Beatmap],
    allowed_usernames: list[str],
) -> bool:
    if metadata.get(MetadataType.Creator) not in allowed_usernames:
        return False

    for beatmap in beatmaps.values():
        if beatmap.creator not in allowed_usernames:
            return False

    return True


async def update_beatmap_metadata(
    bmapset: list[Map],
    files: list[File],
    metadata: dict[MetadataType, str],
    bmap_data: dict[str, Beatmap],
) -> None:
    log("Updating beatmap metadata", Ansi.LCYAN)

    # Update beatmapset metadata
    [
        await maps_repo.partial_update(
            id=bmap["id"],
            artist=metadata.get(MetadataType.Artist),  # type: ignore[arg-type]
            title=metadata.get(MetadataType.Title),  # type: ignore[arg-type]
            creator=metadata.get(MetadataType.Creator),  # type: ignore[arg-type]
            last_update=datetime.now(),
            status=RankedStatus.Pending,
        )
        for bmap in bmapset
    ]

    bmap_files = {
        file.filename: file for file in files if file.filename.endswith(".osu")
    }

    bmap_ids = sorted([bmap["id"] for bmap in bmapset])

    assert len(bmap_ids) == len(bmap_data)

    for filename, bmap in bmap_data.items():
        bmap_id = await resolve_beatmap_id(
            bmap_ids,
            bmap,
            filename,
        )
        assert bmap_id is not None

        difficulty_attributes = performance.calculate_difficulty(
            bmap_files[filename].content,
            bmap.mode,
        )
        assert difficulty_attributes is not None

        await maps_repo.partial_update(
            id=bmap_id,
            filename=filename,
            last_update=datetime.now(),
            total_length=round(bss.calculate_beatmap_total_length(bmap) / 1000),
            md5=hashlib.md5(bmap_files[filename].content).hexdigest(),
            version=bmap.version or "Normal",
            mode=bmap.mode,
            bpm=bss.calculate_beatmap_median_bpm(bmap),
            hp=bmap.hp(),
            cs=bmap.cs(),
            od=bmap.od(),
            ar=bmap.ar(),
            max_combo=difficulty_attributes.max_combo,
            diff=difficulty_attributes.stars,
        )


async def update_beatmap_package(
    bmapset_id: int,
    files: list[File],
) -> None:
    log("Updating beatmap package", Ansi.LCYAN)

    osz_package = bss.create_osz_package(files)

    app.state.services.storage.upload_osz(bmapset_id, osz_package)


async def update_beatmap_thumbnail_and_cover(
    bmapset: list[Map],
    bmaps: dict[str, Beatmap],
    files: list[File],
) -> None:
    log("Uploading beatmap thumbnail...", Ansi.LCYAN)

    filenames = [file.filename for file in files]

    background_files = [
        beatmap.background for beatmap in bmaps.values() if beatmap.background
    ]

    if not background_files:
        log("Background file not specified. Skipping...", Ansi.YELLOW)
        return

    target_background = background_files[0]

    if target_background not in filenames:
        log("Background file not found. Skipping...", Ansi.YELLOW)
        return

    background_file = next(file for file in files if file.filename == target_background)

    thumbnail = utils.resize_and_crop_image(
        background_file.content,
        target_width=160,
        target_height=120,
    )

    cover = utils.resize_and_crop_image(
        background_file.content,
        target_width=900,
        target_height=250,
    )

    app.state.services.storage.upload_beatmap_thumbnail(
        str(bmapset[0]["set_id"]),
        thumbnail,
    )

    app.state.services.storage.upload_beatmap_cover(
        str(bmapset[0]["set_id"]),
        cover,
    )


async def update_beatmap_audio(
    bmapset: list[Map],
    bmaps: dict[str, Beatmap],
    files: list[File],
) -> None:
    log(f"Uploading beatmap audio preview...", Ansi.LCYAN)
    bmaps_with_audio = [beatmap for beatmap in bmaps.values() if beatmap.audio_filename]

    if not bmaps_with_audio:
        log(f"Audio file not specified. Skipping...")
        return

    target_beatmap = bmaps_with_audio[0]
    audio_filename = target_beatmap.audio_filename
    audio_offset = target_beatmap.preview_time.total_seconds() * 1000

    audio_file = next((file for file in files if file.filename == audio_filename), None)

    if not audio_file:
        log(f"Audio file not found. Skipping...")
        return

    audio_snippet = utils.extract_audio_snippet(
        audio_file.content,
        offset_ms=audio_offset,
    )

    # Upload new audio
    app.state.services.storage.upload_beatmap_audio(
        str(bmapset[0]["set_id"]),
        audio_snippet,
    )


async def update_beatmap_files(files: list[File]) -> None:
    log(f"Uploading beatmap files...", Ansi.LCYAN)

    for file in files:
        if not file.filename.endswith(".osu"):
            continue

        bmap = await maps_repo.fetch_one(filename=file.filename)

        if not bmap:
            log(f'Beatmap file "{file.filename}" not found in database. Skipping...')
            continue

        app.state.services.storage.upload_beatmap_file(
            bmap["id"],
            file.content,
        )


async def delete_inactive_beatmaps(player: Player) -> None:
    # Delete any inactive beatmaps
    inactive_bmapsets = await maps_repo.fetch_many(
        creator=player.name,
        status=RankedStatus.Inactive,
    )

    log(f"Found {len(inactive_bmapsets)} inactive beatmaps.", Ansi.LCYAN)

    for bmapset in inactive_bmapsets:
        await remove_all_beatmap_files(bmapset["set_id"])

        await maps_repo.delete_one(id=bmapset["id"])
        await mapsets_repo.delete_one(id=bmapset["set_id"])

        await favourites_repo.delete_favourite_from_player(
            userid=player.id,
            setid=bmapset["set_id"],
        )
        await ratings_repo.delete_rating_from_player(
            userid=player.id,
            map_md5=bmapset["md5"],
        )
        await scores_repo.delete_all_in_beatmap(
            map_md5=bmapset["md5"],
        )


async def remove_all_beatmap_files(bmapset_id: int) -> None:
    app.state.services.storage.remove_osz2(bmapset_id)
    app.state.services.storage.remove_osz(bmapset_id)
    app.state.services.storage.remove_beatmap_thumbnail(str(bmapset_id))
    app.state.services.storage.remove_beatmap_audio(str(bmapset_id))

    bmaps = await maps_repo.fetch_many(set_id=bmapset_id)
    for bmap in bmaps:
        app.state.services.storage.remove_beatmap_file(bmap["id"])


async def resolve_beatmap_id(
    bmap_ids: list[int],
    bmap: Beatmap,
    filename: str,
) -> int:
    # Newer .osu version have the beatmap id in the metadata
    bmap_id: int = bmap.beatmap_id
    if bmap_id is not None:
        return bmap_id

    # Try to get the beatmap id from the filename
    bmap_object = await maps_repo.fetch_one(filename=filename)
    if bmap_object is not None:
        bmap_ids.remove(bmap_object["id"])

        bmap.beatmap_id = bmap_object["id"]
        return bmap_object["id"]

    return bmap_ids.pop(0)


def patch_osz2(osz2_patch: bytes, osz2_source: bytes) -> bytes:
    return bytes(apply_bsdiff_patch(osz2_source, osz2_patch))


def decrypt_osz2(osz2_file: bytes) -> InternalOsz2 | None:
    return InternalOsz2.from_bytes(osz2_file)


def parse_beatmap(osu_file: bytes) -> Beatmap | None:
    return Beatmap.parse(osu_file.decode(errors="ignore"))
