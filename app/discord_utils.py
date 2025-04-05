from __future__ import annotations

import app.settings
from app.discord import Embed
from app.discord import Thumbnail
from app.objects.beatmap import Beatmap
from app.objects.beatmap import BeatmapSet
from app.objects.beatmap import RankedStatus
from app.objects.player import Player


def create_beatmapset_status_change_embed(
    bmapset: BeatmapSet,
    status: RankedStatus,
    player: Player,
) -> Embed:
    embed = Embed(
        title=f"New beatmapset added to {status}:",
        url=f"https://{app.settings.DOMAIN}/b/{bmapset.maps[0].id}",
        thumbnail=Thumbnail(url=f"https://b.ppy.sh/thumb/{bmapset.id}l.jpg"),
    )
    embed.add_field(
        name=f"{bmapset.maps[0].artist} - {bmapset.maps[0].title}",
        value=(f"**Difficulties: ** {len(bmapset.maps)}"),
        inline=False,
    )
    embed.set_footer(
        text=f"Nominator: {player.name}",
        icon_url=f"https://a.{app.settings.DOMAIN}/{player.id}",
    )

    return embed


def create_beatmap_status_change_embed(
    bmap: Beatmap,
    status: RankedStatus,
    player: Player,
) -> Embed:
    star_rating = f"{int(bmap.diff*100)/100}🌟"
    embed = Embed(
        title=f"New beatmap added to {status}:",
        url=f"https://{app.settings.DOMAIN}/b/{bmap.id}",
        thumbnail=Thumbnail(url=f"https://b.ppy.sh/thumb/{bmap.set_id}l.jpg"),
    )
    embed.add_field(
        name=f"{bmap.artist} - {bmap.title} [{bmap.version}]",
        value=f"**{star_rating}** - **CS** {bmap.cs} - **AR** {bmap.ar} - **BPM** {bmap.bpm}",
        inline=False,
    )
    embed.set_footer(
        text=f"Nominator: {player.name}",
        icon_url=f"https://a.{app.settings.DOMAIN}/{player.id}",
    )

    return embed
