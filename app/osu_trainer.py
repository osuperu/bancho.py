from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from slider import Beatmap
from slider import TimingPoint

OSU_TRAINER_SPEED = re.compile(r"(?P<speed>\d(?:\.\d{1,2})?)x \((?P<bpm>\d+)bpm\)")
OSU_TRAINER_HP = re.compile(r"HP(?P<hp>(?:11|10|\d)(?:\.\d{1,2})?)")
OSU_TRAINER_CS = re.compile(r"CS(?P<cs>(?:11|10|\d)(?:\.\d{1,2})?)")
OSU_TRAINER_AR = re.compile(r"AR(?P<ar>(?:11|10|\d)(?:\.\d{1,2})?)")
OSU_TRAINER_OD = re.compile(r"OD(?P<od>(?:11|10|\d)(?:\.\d{1,2})?)")


def split_version_from_edits(full_version: str) -> tuple[str, dict[str, str]]:
    version = full_version

    edits: dict[str, str] = {}
    speed_edits = [match.groupdict() for match in OSU_TRAINER_SPEED.finditer(version)]
    if speed_edits:
        edits.update(speed_edits[-1])
    hp_edits = [match.groupdict() for match in OSU_TRAINER_HP.finditer(version)]
    if hp_edits:
        edits.update(hp_edits[-1])
    cs_edits = [match.groupdict() for match in OSU_TRAINER_CS.finditer(version)]
    if cs_edits:
        edits.update(cs_edits[-1])
    ar_edits = [match.groupdict() for match in OSU_TRAINER_AR.finditer(version)]
    if ar_edits:
        edits.update(ar_edits[-1])
    od_edits = [match.groupdict() for match in OSU_TRAINER_OD.finditer(version)]
    if od_edits:
        edits.update(od_edits[-1])

    # keeping the ordering of these asserted
    if "od" in edits:
        new_version = version.removesuffix(f" OD{edits['od']}")
        assert new_version != version
        version = new_version
    if "ar" in edits:
        new_version = version.removesuffix(f" AR{edits['ar']}")
        assert new_version != version
        version = new_version
    if "cs" in edits:
        new_version = version.removesuffix(f" CS{edits['cs']}")
        assert new_version != version
        version = new_version
    if "hp" in edits:
        new_version = version.removesuffix(f" HP{edits['hp']}")
        assert new_version != version
        version = new_version
    if "speed" in edits:
        new_version = version.removesuffix(f" {edits['speed']}x ({edits['bpm']}bpm)")
        assert new_version != version
        version = new_version

    return version, edits


def create_edited_beatmap(
    original_version: str,
    new_version: str,
    new_beatmap_id: int,
    original_osu_file_path: bytes,
    edits: dict[str, str],
) -> Beatmap:
    if not edits:
        raise Exception("No edits provided")

    print("Original version:", original_version)
    print("New version:", new_version)

    original_beatmap = Beatmap.from_bytes(original_osu_file_path)

    speed = float(edits.get("speed", 1))
    ar = float(edits.get("ar", str(original_beatmap.approach_rate)))
    od = float(edits.get("od", str(original_beatmap.overall_difficulty)))
    cs = float(edits.get("cs", str(original_beatmap.circle_size)))
    hp = float(edits.get("hp", str(original_beatmap.hp_drain_rate)))

    if ar > 10 and od > 10:
        ar = transform_ar(float(ar))
        od = transform_od(float(od))
        speed = float(speed) / 1.5

    tags: list[str] = original_beatmap.tags
    audio_filename: str = original_beatmap.audio_filename
    audio_filename_base, audio_filename_ext = audio_filename.rsplit(".", 1)
    if speed != 1.0:
        audio_filename = f"{audio_filename_base} {speed:.3f}x.{audio_filename_ext}"
    preview_time: timedelta = timedelta(
        milliseconds=original_beatmap.preview_time.total_seconds() * 1000 / speed,
    )
    breaks = [
        (
            (
                timedelta(milliseconds=int(_break[0].total_seconds() * 1000 // speed))
                if isinstance(_break[0], timedelta)
                else timedelta(milliseconds=int(int(_break[0]) // speed))
            ),
            (
                timedelta(milliseconds=int(_break[1].total_seconds() * 1000 // speed))
                if isinstance(_break[1], timedelta)
                else timedelta(milliseconds=int(int(_break[1]) // speed))
            ),
        )
        for _break in original_beatmap.breaks
    ]
    bookmarks: list[timedelta] = original_beatmap.bookmarks
    # TODO: don't scale bookmarks because osutrainer doesn't do that, idk if it's a bug or intended
    # if bookmarks:
    # scale all bookmarks
    # bookmarks = [timedelta(seconds=bookmark.total_seconds() / float(rate)) for bookmark in bookmarks]

    timing_points: list[TimingPoint] = original_beatmap.timing_points
    for timing_point in timing_points:
        timing_point.offset /= speed
        if timing_point.ms_per_beat > 0:
            # beatlength can be negative when it's indicating slider velocity, we don't need to change that
            timing_point.ms_per_beat /= speed

    tags.append("osutrainer")

    return Beatmap(
        format_version=original_beatmap.format_version,
        audio_filename=audio_filename,
        audio_lead_in=original_beatmap.audio_lead_in,
        preview_time=preview_time,
        countdown=original_beatmap.countdown,
        sample_set=original_beatmap.sample_set,
        stack_leniency=original_beatmap.stack_leniency,
        mode=original_beatmap.mode,
        letterbox_in_breaks=original_beatmap.letterbox_in_breaks,
        widescreen_storyboard=original_beatmap.widescreen_storyboard,
        bookmarks=bookmarks,
        distance_spacing=original_beatmap.distance_spacing,
        beat_divisor=original_beatmap.beat_divisor,
        grid_size=original_beatmap.grid_size,
        timeline_zoom=original_beatmap.timeline_zoom,
        title=original_beatmap.title,
        title_unicode=original_beatmap.title_unicode,
        artist=original_beatmap.artist,
        artist_unicode=original_beatmap.artist_unicode,
        creator=original_beatmap.creator,
        version=new_version,
        source=original_beatmap.source,
        tags=original_beatmap.tags,
        beatmap_id=new_beatmap_id,
        beatmap_set_id=original_beatmap.beatmap_set_id,
        hp_drain_rate=float(hp),
        circle_size=float(cs),
        overall_difficulty=float(od),
        approach_rate=float(ar),
        slider_multiplier=original_beatmap.slider_multiplier,
        slider_tick_rate=original_beatmap.slider_tick_rate,
        timing_points=timing_points,
        combo_colours=original_beatmap.combo_colours,
        slider_track_override=original_beatmap.slider_track_override,
        slider_border=original_beatmap.slider_border,
        hit_objects=original_beatmap.hit_objects(stacking=False, speed_scale=speed),
        background=original_beatmap.background,
        videos=[],
        breaks=breaks,
    )


def transform_ar(after_dt: float) -> float:
    """
    Transforms AR after DT/HT
    """
    return 0.5 * (after_dt * 3 - 13)


def transform_od(after_od: float) -> float:
    """
    Transforms OD after DT/HT
    """
    after_hit_window = 79.5 - 6 * after_od
    before_hit_window = after_hit_window * 1.5
    return (79.5 - before_hit_window) / 6
