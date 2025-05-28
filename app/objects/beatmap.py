from __future__ import annotations

import functools
import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from datetime import timedelta
from enum import IntEnum
from enum import unique

import aiosu
import httpx

import app.settings
import app.state
from app.adapters.osu_api_v1 import get_osu_file
from app.adapters.osu_api_v2 import get_beatmapset
from app.adapters.osu_api_v2 import lookup_beatmap
from app.constants.gamemodes import GameMode
from app.logging import log
from app.repositories import maps as maps_repo
from app.repositories.maps import MapServer
from app.utils import escape_enum
from app.utils import pymysql_encode

# from dataclasses import dataclass

DEFAULT_LAST_UPDATE = datetime(1970, 1, 1)


def disk_has_expected_osu_file(
    beatmap_id: int,
    expected_md5: str | None = None,
) -> bool:
    file_exists = app.state.services.storage.file_exists(str(beatmap_id), "osu", "osu")
    if file_exists and expected_md5 is not None:
        osu_file = app.state.services.storage.get_beatmap_file(beatmap_id)
        if osu_file is not None:
            osu_file_md5 = hashlib.md5(osu_file).hexdigest()
            return osu_file_md5 == expected_md5
    return file_exists


async def ensure_osu_file_is_available(
    beatmap_id: int,
    expected_md5: str | None = None,
) -> bool:
    """\
    Download the .osu file for a beatmap if it's not already present.

    If `expected_md5` is provided, the file will be downloaded if it
    does not match the expected md5 hash -- this is typically used for
    ensuring a file is the latest expected version.

    Returns whether the file is available for use.
    """
    if disk_has_expected_osu_file(beatmap_id, expected_md5):
        return True

    latest_osu_file = await get_osu_file(beatmap_id)
    if latest_osu_file is None:
        return False

    app.state.services.storage.upload_beatmap_file(beatmap_id, latest_osu_file)
    return True


# for some ungodly reason, different values are used to
# represent different ranked statuses all throughout osu!
# This drives me and probably everyone else pretty insane,
# but we have nothing to do but deal with it B).


@unique
@pymysql_encode(escape_enum)
class RankedStatus(IntEnum):
    """Server side osu! beatmap ranked statuses.
    Same as used in osu!'s /web/getscores.php.
    """

    Inactive = -3  # used in beatmap submission
    NotSubmitted = -1
    Pending = 0
    UpdateAvailable = 1
    Ranked = 2
    Approved = 3
    Qualified = 4
    Loved = 5

    def __str__(self) -> str:
        return {
            self.NotSubmitted: "Unsubmitted",
            self.Pending: "Unranked",
            self.UpdateAvailable: "Outdated",
            self.Ranked: "Ranked",
            self.Approved: "Approved",
            self.Qualified: "Qualified",
            self.Loved: "Loved",
        }[self]

    @functools.cached_property
    def osu_api(self) -> int:
        """Convert the value to osu!api status."""
        # XXX: only the ones that exist are mapped.
        return {
            self.Pending: 0,
            self.Ranked: 1,
            self.Approved: 2,
            self.Qualified: 3,
            self.Loved: 4,
        }[self]

    @classmethod
    @functools.cache
    def from_osuapi(cls, osuapi_status: int) -> RankedStatus:
        """Convert from osu!api status."""
        mapping: Mapping[int, RankedStatus] = defaultdict(
            lambda: cls.UpdateAvailable,
            {
                -2: cls.Pending,  # graveyard
                -1: cls.Pending,  # wip
                0: cls.Pending,
                1: cls.Ranked,
                2: cls.Approved,
                3: cls.Qualified,
                4: cls.Loved,
            },
        )
        return mapping[osuapi_status]

    @classmethod
    @functools.cache
    def from_osudirect(cls, osudirect_status: int) -> RankedStatus:
        """Convert from osu!direct status."""
        mapping: Mapping[int, RankedStatus] = defaultdict(
            lambda: cls.UpdateAvailable,
            {
                0: cls.Ranked,
                2: cls.Pending,
                3: cls.Qualified,
                # 4: all ranked statuses lol
                5: cls.Pending,  # graveyard
                7: cls.Ranked,  # played before
                8: cls.Loved,
            },
        )
        return mapping[osudirect_status]

    @classmethod
    @functools.cache
    def from_str(cls, status_str: str) -> RankedStatus:
        """Convert from string value."""  # could perhaps have `'unranked': cls.Pending`?
        mapping: Mapping[str, RankedStatus] = defaultdict(
            lambda: cls.UpdateAvailable,
            {
                "pending": cls.Pending,
                "ranked": cls.Ranked,
                "approved": cls.Approved,
                "qualified": cls.Qualified,
                "loved": cls.Loved,
            },
        )
        return mapping[status_str]


# @dataclass
# class BeatmapInfoRequest:
#    filenames: Sequence[str]
#    ids: Sequence[int]

# @dataclass
# class BeatmapInfo:
#    id: int # i16
#    map_id: int # i32
#    set_id: int # i32
#    thread_id: int # i32
#    status: int # u8
#    osu_rank: int # u8
#    fruits_rank: int # u8
#    taiko_rank: int # u8
#    mania_rank: int # u8
#    map_md5: str


class Beatmap:
    """A class representing an osu! beatmap.

    This class provides a high level api which should always be the
    preferred method of fetching beatmaps due to its housekeeping.
    It will perform caching & invalidation, handle map updates while
    minimizing osu!api requests, and always use the most efficient
    method available to fetch the beatmap's information, while
    maintaining a low overhead.

    The only methods you should need are:
      await Beatmap.from_md5(md5: str, set_id: int = -1) -> Beatmap | None
      await Beatmap.from_bid(bid: int) -> Beatmap | None

    Properties:
      Beatmap.full -> str # Artist - Title [Version]
      Beatmap.url -> str # https://osu.cmyui.xyz/b/321
      Beatmap.embed -> str # [{url} {full}]

      Beatmap.has_leaderboard -> bool
      Beatmap.awards_ranked_pp -> bool
      Beatmap.as_dict -> dict[str, object]

    Lower level API:
      Beatmap._from_md5_cache(md5: str, check_updates: bool = True) -> Beatmap | None
      Beatmap._from_bid_cache(bid: int, check_updates: bool = True) -> Beatmap | None

      Beatmap._from_md5_sql(md5: str) -> Beatmap | None
      Beatmap._from_bid_sql(bid: int) -> Beatmap | None

      Beatmap._parse_from_osuapi_resp(osuapi_resp: dict[str, object]) -> None

    Note that the BeatmapSet class also provides a similar API.

    Possibly confusing attributes
    -----------
    frozen: `bool`
        Whether the beatmap's status is to be kept when a newer
        version is found in the osu!api.
        # XXX: This is set when a map's status is manually changed.
    """

    def __init__(
        self,
        map_set: BeatmapSet,
        md5: str = "",
        id: int = 0,
        set_id: int = 0,
        artist: str = "",
        title: str = "",
        version: str = "",
        creator: str = "",
        last_update: datetime = DEFAULT_LAST_UPDATE,
        total_length: int = 0,
        max_combo: int = 0,
        status: RankedStatus = RankedStatus.Pending,
        frozen: bool = False,
        plays: int = 0,
        passes: int = 0,
        mode: GameMode = GameMode.VANILLA_OSU,
        bpm: float = 0.0,
        cs: float = 0.0,
        od: float = 0.0,
        ar: float = 0.0,
        hp: float = 0.0,
        diff: float = 0.0,
        filename: str = "",
        server: MapServer = MapServer.OSU,
    ) -> None:
        self.set = map_set

        self.md5 = md5
        self.id = id
        self.set_id = set_id
        self.artist = artist
        self.title = title
        self.version = version
        self.creator = creator
        self.last_update = last_update
        self.total_length = total_length
        self.max_combo = max_combo
        self.status = status
        self.frozen = frozen
        self.plays = plays
        self.passes = passes
        self.mode = mode
        self.bpm = bpm
        self.cs = cs
        self.od = od
        self.ar = ar
        self.hp = hp
        self.diff = diff
        self.filename = filename
        self.server = server

    def __repr__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        """The full osu! formatted name `self`."""
        return f"{self.artist} - {self.title} [{self.version}]"

    @property
    def url(self) -> str:
        """The osu! beatmap url for `self`."""
        return f"https://osu.{app.settings.DOMAIN}/b/{self.id}"

    @property
    def embed(self) -> str:
        """An osu! chat embed to `self`'s osu! beatmap page."""
        return f"[{self.url} {self.full_name}]"

    @property
    def has_leaderboard(self) -> bool:
        """Return whether the map has a ranked leaderboard."""
        return self.status in (
            RankedStatus.Ranked,
            RankedStatus.Approved,
            RankedStatus.Loved,
        )

    @property
    def awards_ranked_pp(self) -> bool:
        """Return whether the map's status awards ranked pp for scores."""
        return self.status in (RankedStatus.Ranked, RankedStatus.Approved)

    @property  # perhaps worth caching some of?
    def as_dict(self) -> dict[str, object]:
        return {
            "md5": self.md5,
            "id": self.id,
            "set_id": self.set_id,
            "artist": self.artist,
            "title": self.title,
            "version": self.version,
            "creator": self.creator,
            "last_update": self.last_update,
            "total_length": self.total_length,
            "max_combo": self.max_combo,
            "status": self.status,
            "plays": self.plays,
            "passes": self.passes,
            "mode": self.mode,
            "bpm": self.bpm,
            "cs": self.cs,
            "od": self.od,
            "ar": self.ar,
            "hp": self.hp,
            "diff": self.diff,
        }

    """ High level API """
    # There are three levels of storage used for beatmaps,
    # the cache (ram), the db (disk), and the osu!api (web).
    # Going down this list gets exponentially slower, so
    # we always prioritze what's fastest when possible.
    # These methods will keep beatmaps reasonably up to
    # date and use the fastest storage available, while
    # populating the higher levels of the cache with new maps.

    @classmethod
    async def from_md5(cls, md5: str, set_id: int = -1) -> Beatmap | None:
        """Fetch a map from the cache, database, or osuapi by md5."""
        bmap = await cls._from_md5_cache(md5)

        if not bmap:
            # map not found in cache

            # to be efficient, we want to cache the whole set
            # at once rather than caching the individual map

            if set_id <= 0:
                # set id not provided - fetch it from the map md5
                rec = await maps_repo.fetch_one(md5=md5)

                if rec is not None:
                    # set found in db
                    set_id = rec["set_id"]
                else:
                    # set not found in db, try api
                    api_response = await lookup_beatmap(beatmap_md5=md5)

                    if api_response is None:
                        return None

                    set_id = api_response.beatmapset_id

            # fetch (and cache) beatmap set
            beatmap_set = await BeatmapSet.from_bsid(set_id)

            if beatmap_set is not None:
                # the beatmap set has been cached - fetch beatmap from cache
                bmap = await cls._from_md5_cache(md5)

                # XXX:HACK in this case, BeatmapSet.from_bsid will have
                # ensured the map is up to date, so we can just return it
                return bmap

        if bmap is not None:
            if bmap.set._cache_expired():
                await bmap.set._update_if_available()

        return bmap

    @classmethod
    async def from_bid(cls, bid: int) -> Beatmap | None:
        """Fetch a map from the cache, database, or osuapi by id."""
        bmap = await cls._from_bid_cache(bid)

        if not bmap:
            # map not found in cache

            # to be efficient, we want to cache the whole set
            # at once rather than caching the individual map

            rec = await maps_repo.fetch_one(id=bid)

            if rec is not None:
                # set found in db
                set_id = rec["set_id"]
            else:
                # set not found in db, try getting via api
                api_response = await lookup_beatmap(beatmap_id=bid)

                if api_response is None:
                    return None

                set_id = api_response.beatmapset_id

            # fetch (and cache) beatmap set
            beatmap_set = await BeatmapSet.from_bsid(set_id)

            if beatmap_set is not None:
                # the beatmap set has been cached - fetch beatmap from cache
                bmap = await cls._from_bid_cache(bid)

                # XXX:HACK in this case, BeatmapSet.from_bsid will have
                # ensured the map is up to date, so we can just return it
                return bmap

        if bmap is not None:
            if bmap.set._cache_expired():
                await bmap.set._update_if_available()

        return bmap

    """ Lower level API """
    # These functions are meant for internal use under
    # all normal circumstances and should only be used
    # if you're really modifying bancho.py by adding new
    # features, or perhaps optimizing parts of the code.

    def _create_beatmap_filename(
        self,
        artist: str,
        title: str,
        version: str,
        creator: str,
    ) -> str:
        return f"{artist} - {title} ({creator}) [{version}].osu"

    def _parse_from_osuapi_resp(
        self,
        beatmap: aiosu.models.beatmap.Beatmap,
        beatmapset: aiosu.models.beatmap.Beatmapset,
    ) -> None:
        """Change internal data with the data in osu!api format."""
        # NOTE: `self` is not guaranteed to have any attributes
        #       initialized when this is called.
        assert beatmap.checksum is not None
        self.md5 = beatmap.checksum
        # self.id = int(osuapi_resp['beatmap_id'])
        self.set_id = beatmap.beatmapset_id

        self.artist, self.title, self.version, self.creator = (
            beatmapset.artist,
            beatmapset.title,
            beatmap.version,
            beatmapset.creator,
        )

        self.filename = self._create_beatmap_filename(
            self.artist,
            self.title,
            self.version,
            self.creator,
        )

        # quite a bit faster than using dt.strptime.
        if beatmap.last_updated is not None:
            self.last_update = beatmap.last_updated.replace(tzinfo=None)

        self.total_length = beatmap.total_length

        if beatmap.max_combo is not None:
            self.max_combo = beatmap.max_combo
        else:
            self.max_combo = 0

        # if a map is 'frozen', we keep its status
        # even after an update from the osu!api.
        if not getattr(self, "frozen", False):
            self.status = RankedStatus.from_osuapi(beatmap.status.id)

        self.mode = GameMode(beatmap.mode.id)

        if beatmap.bpm is not None:
            self.bpm = beatmap.bpm
        else:
            self.bpm = 0.0

        assert beatmap.cs is not None
        assert beatmap.accuracy is not None
        assert beatmap.ar is not None
        assert beatmap.drain is not None

        self.cs = beatmap.cs
        self.od = beatmap.accuracy
        self.ar = beatmap.ar
        self.hp = beatmap.drain

        self.diff = beatmap.difficulty_rating

    @staticmethod
    async def _from_md5_cache(md5: str) -> Beatmap | None:
        """Fetch a map from the cache by md5."""
        return app.state.cache.beatmap.get(md5, None)

    @staticmethod
    async def _from_bid_cache(bid: int) -> Beatmap | None:
        """Fetch a map from the cache by id."""
        return app.state.cache.beatmap.get(bid, None)


class BeatmapSet:
    """A class to represent an osu! beatmap set.

    Like the Beatmap class, this class provides a high level api
    which should always be the preferred method of fetching beatmaps
    due to its housekeeping. It will perform caching & invalidation,
    handle map updates while minimizing osu!api requests, and always
    use the most efficient method available to fetch the beatmap's
    information, while maintaining a low overhead.

    The only methods you should need are:
      await BeatmapSet.from_bsid(bsid: int) -> BeatmapSet | None

      BeatmapSet.all_officially_ranked_or_approved() -> bool
      BeatmapSet.all_officially_loved() -> bool

    Properties:
      BeatmapSet.url -> str # https://osu.cmyui.xyz/s/123

    Lower level API:
      await BeatmapSet._from_bsid_cache(bsid: int) -> BeatmapSet | None
      await BeatmapSet._from_bsid_sql(bsid: int) -> BeatmapSet | None
      await BeatmapSet._from_bsid_osuapi(bsid: int) -> BeatmapSet | None

      BeatmapSet._cache_expired() -> bool
      await BeatmapSet._update_if_available() -> None
      await BeatmapSet._save_to_sql() -> None
    """

    def __init__(
        self,
        id: int,
        last_osuapi_check: datetime,
        maps: list[Beatmap] | None = None,
    ) -> None:
        self.id = id

        self.maps = maps or []
        self.last_osuapi_check = last_osuapi_check

    def __repr__(self) -> str:
        map_names = []
        for bmap in self.maps:
            name = f"{bmap.artist} - {bmap.title}"
            if name not in map_names:
                map_names.append(name)
        return ", ".join(map_names)

    @property
    def url(self) -> str:
        """The online url for this beatmap set."""
        return f"https://osu.{app.settings.DOMAIN}/s/{self.id}"

    def any_beatmaps_have_official_leaderboards(self) -> bool:
        """Whether all the maps in the set have leaderboards on official servers."""
        leaderboard_having_statuses = (
            RankedStatus.Loved,
            RankedStatus.Ranked,
            RankedStatus.Approved,
        )
        return any(bmap.status in leaderboard_having_statuses for bmap in self.maps)

    def _cache_expired(self) -> bool:
        """Whether the cached version of the set is
        expired and needs an update from the osu!api."""
        current_datetime = datetime.now()

        if not self.maps:
            return True

        # the delta between cache invalidations will increase depending
        # on how long it's been since the map was last updated on osu!
        last_map_update = max(bmap.last_update for bmap in self.maps)
        update_delta = current_datetime - last_map_update

        # with a minimum of 2 hours, add 5 hours per year since its update.
        # the formula for this is subject to adjustment in the future.
        check_delta = timedelta(hours=2 + ((5 / 365) * update_delta.days))

        # it's much less likely that a beatmapset who has beatmaps with
        # leaderboards on official servers will be updated.
        if self.any_beatmaps_have_official_leaderboards():
            check_delta *= 4

        # we'll cache for an absolute maximum of 1 day.
        check_delta = min(check_delta, timedelta(days=1))

        return current_datetime > (self.last_osuapi_check + check_delta)

    async def _update_if_available(self) -> None:
        """Fetch the newest data from the api, check for differences
        and propogate any update into our cache & database."""

        try:
            api_response = await get_beatmapset(beatmapset_id=self.id)
        except Exception:
            # we do not want to delete the beatmap in this case, so we simply return
            # but do not set the last check, as we would like to retry these ASAP

            return

        if api_response is not None and api_response.beatmaps is not None:
            old_maps = {bmap.id: bmap for bmap in self.maps}
            new_maps = {int(api_map.id): api_map for api_map in api_response.beatmaps}

            self.last_osuapi_check = datetime.now()

            # delete maps from old_maps where old.id not in new_maps
            # update maps from old_maps where old.md5 != new.md5
            # add maps to old_maps where new.id not in old_maps

            updated_maps: list[Beatmap] = []
            map_md5s_to_delete: set[str] = set()

            # temp value for building the new beatmap
            bmap: Beatmap

            # find maps in our current state that've been deleted, or need updates
            for old_id, old_map in old_maps.items():
                if old_id not in new_maps:
                    # delete map from old_maps
                    assert old_map.md5 is not None

                    map_md5s_to_delete.add(old_map.md5)
                else:
                    new_map = new_maps[old_id]
                    new_ranked_status = RankedStatus.from_osuapi(new_map.status.id)
                    if (
                        old_map.md5 != new_map.checksum
                        or old_map.status != new_ranked_status
                    ):
                        # update map from old_maps
                        bmap = old_maps[old_id]
                        bmap._parse_from_osuapi_resp(new_map, api_response)
                        updated_maps.append(bmap)
                    else:
                        # map is the same, make no changes
                        updated_maps.append(old_map)  # (this line is _maybe_ needed?)

            # find maps that aren't in our current state, and add them
            for new_id, new_map in new_maps.items():
                if new_id not in old_maps:
                    # new map we don't have locally, add it
                    bmap = Beatmap.__new__(Beatmap)
                    bmap.id = new_id

                    bmap._parse_from_osuapi_resp(new_map, api_response)

                    # (some implementation-specific stuff not given by api)
                    bmap.frozen = False
                    bmap.passes = 0
                    bmap.plays = 0

                    bmap.set = self
                    updated_maps.append(bmap)

            # save changes to cache
            self.maps = updated_maps

            # save changes to sql

            if map_md5s_to_delete:
                # delete maps
                await app.state.services.database.execute(
                    "DELETE FROM maps WHERE md5 IN :map_md5s",
                    {"map_md5s": map_md5s_to_delete},
                )

                # delete scores on the maps
                await app.state.services.database.execute(
                    "DELETE FROM scores WHERE map_md5 IN :map_md5s",
                    {"map_md5s": map_md5s_to_delete},
                )

            # update last_osuapi_check
            await app.state.services.database.execute(
                "REPLACE INTO mapsets "
                "(id, server, last_osuapi_check) "
                "VALUES (:id, :server, :last_osuapi_check)",
                {
                    "id": self.id,
                    "server": "osu!",
                    "last_osuapi_check": self.last_osuapi_check,
                },
            )

            # update maps in sql
            await self._save_to_sql()
        elif api_response is None:
            # NOTE: 200 can return an empty array of beatmaps,
            #       so we still delete in this case if the beatmap data is None

            # TODO: a couple of open questions here:
            # - should we delete the beatmap from the database if it's not in the osu!api?
            # - are 404 and 200 the only cases where we should delete the beatmap?
            if self.maps:
                map_md5s_to_delete = {
                    bmap.md5 for bmap in self.maps if bmap.server == MapServer.OSU
                }

                if map_md5s_to_delete:
                    # delete maps
                    await app.state.services.database.execute(
                        "DELETE FROM maps WHERE md5 IN :map_md5s",
                        {"map_md5s": map_md5s_to_delete},
                    )

                    # delete scores on the maps
                    await app.state.services.database.execute(
                        "DELETE FROM scores WHERE map_md5 IN :map_md5s",
                        {"map_md5s": map_md5s_to_delete},
                    )

            if self.maps[0].server == MapServer.OSU:
                # delete set
                await app.state.services.database.execute(
                    "DELETE FROM mapsets WHERE id = :set_id",
                    {"set_id": self.id},
                )

    async def _save_to_sql(self) -> None:
        """Save the object's attributes into the database."""
        await app.state.services.database.execute_many(
            "REPLACE INTO maps ("
            "md5, id, server, set_id, "
            "artist, title, version, creator, "
            "filename, last_update, total_length, "
            "max_combo, status, frozen, "
            "plays, passes, mode, bpm, "
            "cs, od, ar, hp, diff"
            ") VALUES ("
            ":md5, :id, :server, :set_id, "
            ":artist, :title, :version, :creator, "
            ":filename, :last_update, :total_length, "
            ":max_combo, :status, :frozen, "
            ":plays, :passes, :mode, :bpm, "
            ":cs, :od, :ar, :hp, :diff"
            ")",
            [
                {
                    "md5": bmap.md5,
                    "id": bmap.id,
                    "server": "osu!",
                    "set_id": bmap.set_id,
                    "artist": bmap.artist,
                    "title": bmap.title,
                    "version": bmap.version,
                    "creator": bmap.creator,
                    "filename": bmap.filename,
                    "last_update": bmap.last_update,
                    "total_length": bmap.total_length,
                    "max_combo": bmap.max_combo,
                    "status": bmap.status,
                    "frozen": bmap.frozen,
                    "plays": bmap.plays,
                    "passes": bmap.passes,
                    "mode": bmap.mode,
                    "bpm": bmap.bpm,
                    "cs": bmap.cs,
                    "od": bmap.od,
                    "ar": bmap.ar,
                    "hp": bmap.hp,
                    "diff": bmap.diff,
                }
                for bmap in self.maps
            ],
        )

    @staticmethod
    async def _from_bsid_cache(bsid: int) -> BeatmapSet | None:
        """Fetch a mapset from the cache by set id."""
        return app.state.cache.beatmapset.get(bsid, None)

    @classmethod
    async def _from_bsid_sql(cls, bsid: int) -> BeatmapSet | None:
        """Fetch a mapset from the database by set id."""
        last_osuapi_check = await app.state.services.database.fetch_val(
            "SELECT last_osuapi_check FROM mapsets WHERE id = :set_id",
            {"set_id": bsid},
            column=0,  # last_osuapi_check
        )

        if last_osuapi_check is None:
            return None

        bmap_set = cls(id=bsid, last_osuapi_check=last_osuapi_check)

        for row in await maps_repo.fetch_many(set_id=bsid):
            bmap = Beatmap(
                md5=row["md5"],
                id=row["id"],
                set_id=row["set_id"],
                artist=row["artist"],
                title=row["title"],
                version=row["version"],
                creator=row["creator"],
                last_update=row["last_update"],
                total_length=row["total_length"],
                max_combo=row["max_combo"],
                status=RankedStatus(row["status"]),
                frozen=row["frozen"],
                plays=row["plays"],
                passes=row["passes"],
                mode=GameMode(row["mode"]),
                bpm=row["bpm"],
                cs=row["cs"],
                od=row["od"],
                ar=row["ar"],
                hp=row["hp"],
                diff=row["diff"],
                filename=row["filename"],
                map_set=bmap_set,
                server=MapServer(row["server"]),
            )

            # XXX: tempfix for bancho.py <v3.4.1,
            # where filenames weren't stored.
            if not bmap.filename:
                bmap.filename = bmap._create_beatmap_filename(
                    artist=row["artist"],
                    title=row["title"],
                    creator=row["creator"],
                    version=row["version"],
                )
                await maps_repo.partial_update(bmap.id, filename=bmap.filename)

            bmap_set.maps.append(bmap)

        return bmap_set

    @classmethod
    async def _from_bsid_osuapi(cls, bsid: int) -> BeatmapSet | None:
        """Fetch a mapset from the osu!api by set id."""
        api_response = await get_beatmapset(beatmapset_id=bsid)
        if api_response is not None and api_response.beatmaps is not None:
            # api_response = api_data["data"]

            self = cls(id=bsid, last_osuapi_check=datetime.now())

            # XXX: pre-mapset bancho.py support
            # select all current beatmaps
            # that're frozen in the db
            res = await app.state.services.database.fetch_all(
                "SELECT id, status FROM maps WHERE set_id = :set_id AND frozen = 1",
                {"set_id": bsid},
            )

            current_maps = {row["id"]: row["status"] for row in res}

            for api_bmap in api_response.beatmaps:
                # newer version available for this map
                bmap: Beatmap = Beatmap.__new__(Beatmap)
                bmap.id = int(api_bmap.id)

                if bmap.id in current_maps:
                    # map is currently frozen, keep it's status.
                    bmap.status = RankedStatus(current_maps[bmap.id])
                    bmap.frozen = True
                else:
                    bmap.frozen = False

                bmap._parse_from_osuapi_resp(api_bmap, api_response)

                # (some implementation-specific stuff not given by api)
                bmap.passes = 0
                bmap.plays = 0

                bmap.set = self
                self.maps.append(bmap)

            await app.state.services.database.execute(
                "REPLACE INTO mapsets "
                "(id, server, last_osuapi_check) "
                "VALUES (:id, :server, :last_osuapi_check)",
                {
                    "id": self.id,
                    "server": "osu!",
                    "last_osuapi_check": self.last_osuapi_check,
                },
            )

            await self._save_to_sql()
            return self

        return None

    @classmethod
    async def from_bsid(cls, bsid: int) -> BeatmapSet | None:
        """Cache all maps in a set from the osuapi, optionally
        returning beatmaps by their md5 or id."""
        bmap_set = await cls._from_bsid_cache(bsid)
        did_api_request = False

        if not bmap_set:
            bmap_set = await cls._from_bsid_sql(bsid)

            if not bmap_set:
                bmap_set = await cls._from_bsid_osuapi(bsid)

                if not bmap_set:
                    return None

                did_api_request = True

        # TODO: this can be done less often for certain types of maps,
        # such as ones that're ranked on bancho and won't be updated,
        # and perhaps ones that haven't been updated in a long time.
        if not did_api_request and bmap_set._cache_expired():
            await bmap_set._update_if_available()

        # cache the beatmap set, and beatmaps
        # to be efficient in future requests
        cache_beatmap_set(bmap_set)

        return bmap_set


def cache_beatmap(beatmap: Beatmap) -> None:
    """Add the beatmap to the cache."""
    assert beatmap.md5 is not None

    app.state.cache.beatmap[beatmap.md5] = beatmap
    app.state.cache.beatmap[beatmap.id] = beatmap


def cache_beatmap_set(beatmap_set: BeatmapSet) -> None:
    """Add the beatmap set, and each beatmap to the cache."""
    app.state.cache.beatmapset[beatmap_set.id] = beatmap_set

    for beatmap in beatmap_set.maps:
        cache_beatmap(beatmap)
