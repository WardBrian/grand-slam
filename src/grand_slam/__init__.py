from dataclasses import dataclass, field
import json
import time
import datetime
import requests
from typing import TYPE_CHECKING, Optional
from importlib.resources import files


import tzlocal
import bullpen
from bullpen.api.update import UpdateStatus
from bullpen.logging import LOGGER
from bullpen.util import scrolling_text
from bullpen.time_formats import TIME_FORMAT_12H

if TYPE_CHECKING:
    from RGBMatrixEmulator.emulation.canvas import Canvas

ATP_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard"
WTA_URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard"

UPDATE_RATE = 30


def _get(url: str) -> dict:
    resp = requests.get(url, timeout=(5, 15))
    resp.raise_for_status()
    return resp.json()


class Config(bullpen.api.PluginConfig):
    def __init__(self, config: bullpen.api.config.MLBConfig) -> None:
        self.today = config.parse_today()
        self.scrolling_speed = config.scrolling_speed
        time_format = config.time_format
        self.time_fmt_str = "{}:%M".format(time_format)
        if time_format == TIME_FORMAT_12H:
            self.time_fmt_str += "%p"
        self.tournament_ids = config.plugin_config.get("tournament_ids", [])


ROUND_ABBR = {
    "Round 1": "R1",
    "Round 2": "R2",
    "Round 3": "R3",
    "Round 4": "R4",
    "Round of 128": "R128",
    "Round of 64": "R64",
    "Round of 32": "R32",
    "Round of 16": "R16",
    "Quarterfinal": "QF",
    "Semifinal": "SF",
    "Final": "F",
    "Qualifying 1st Round": "Q1",
    "Qualifying 2nd Round": "Q2",
    "Qualifying 3rd Round": "Q3",
    "Qualifying Final": "QF (Q)",
}


@dataclass
class Match:
    tournament: str
    kind: str  # "pregame" | "ingame" | "postgame"
    away_name: str
    home_name: str
    round_name: Optional[str] = None
    display_time: Optional[str] = None
    venue: Optional[str] = None
    away_sets: list = field(default_factory=list)  # ingame/postgame: per-set game counts
    home_sets: list = field(default_factory=list)
    away_serving: bool = False  # ingame only
    home_serving: bool = False
    away_winner: Optional[bool] = None  # postgame only
    home_winner: Optional[bool] = None
    status_note: Optional[str] = None  # postgame only -- "Retired"/"Walkover", real non-"Final" outcomes


class Data(bullpen.api.PluginData):
    def __init__(self, config: Config) -> None:
        self.today = config.today
        self.year = self.today.year
        self.time_fmt_str = config.time_fmt_str
        self.tournament_ids = config.tournament_ids

        self.starttime = time.time()
        self.matches: list[Match] = []
        self.match_idx = 0

        self.update(True)

    def update(self, force=False) -> UpdateStatus:
        if force or self.__should_update():
            try:
                matches = []
                for url in (ATP_URL, WTA_URL):
                    data = _get(url)
                    for e in data.get("events", []):
                        if self.tournament_ids and e.get("id") not in self.tournament_ids:
                            continue
                        tname = e.get("name") or e.get("shortName") or "Tournament"
                        for g in e.get("groupings", []):
                            for c in g.get("competitions", []):
                                try:
                                    m = self.parse_match(tname, c)
                                    if m is not None:
                                        matches.append(m)
                                except Exception as e:
                                    LOGGER.exception("Failed to parse match: %s", e)
                                    pass
                self.match_idx = self.match_idx % len(matches) if matches else 0
                self.matches = matches
            except Exception as e:
                LOGGER.exception("Failed to fetch grand slam data: %s", e)
                return UpdateStatus.FAIL
            finally:
                self.starttime = time.time()

            return UpdateStatus.SUCCESS
        return UpdateStatus.DEFERRED

    def parse_match(self, tournament: str, c: dict) -> Optional[Match]:
        status = (c.get("status") or {}).get("type") or {}
        kind = status.get("state")
        if kind is None:
            return None
        kind = kind + "game"

        date = c.get("date")
        date = datetime.datetime.fromisoformat(date)
        date = date.astimezone(tzlocal.get_localzone())
        if date.date() != self.today:
            return None

        competitors = c.get("competitors") or []
        away = next((x for x in competitors if x.get("homeAway") == "away"), None)
        home = next((x for x in competitors if x.get("homeAway") == "home"), None)
        if not away or not home:
            return None

        round_name = (c.get("round") or {}).get("displayName")
        venue_obj = c.get("venue") or {}
        venue = venue_obj.get("court") or venue_obj.get("fullName")

        m = Match(
            tournament=tournament,
            kind=kind,
            round_name=round_name,
            away_name=competitor_name(away),
            home_name=competitor_name(home),
            venue=venue,
            display_time=date.strftime(self.time_fmt_str),
        )

        if kind == "pregame":
            return m

        # `linescores` are per-competitor, per-set game counts -- confirmed live, real shape, no
        # combined-string ambiguity to resolve here (see common.py's own docstring).
        m.away_sets = [int(ls["value"]) for ls in (away.get("linescores") or []) if "value" in ls]
        m.home_sets = [int(ls["value"]) for ls in (home.get("linescores") or []) if "value" in ls]

        if kind == "ingame":
            m.away_serving = bool(away.get("possession"))
            m.home_serving = bool(home.get("possession"))
        else:  # postgame
            m.away_winner = away.get("winner")
            m.home_winner = home.get("winner")
            desc = status.get("description")
            if desc and desc != "Final":
                m.status_note = desc  # real, confirmed values seen live: "Retired", "Walkover"

        return m

    def __should_update(self):
        endtime = time.time()
        time_delta = endtime - self.starttime
        return time_delta >= UPDATE_RATE


def competitor_name(c: dict) -> str:
    if c.get("type") == "team":
        # Doubles competitors
        roster = c.get("roster") or {}
        return roster.get("shortDisplayName") or roster.get("displayName") or "?"
    athlete = c.get("athlete") or {}
    name = athlete.get("shortName") or athlete.get("displayName") or "?"
    return name.split(" ", 1)[1]


class Renderer(bullpen.api.PluginRenderer[Data]):

    def __init__(self, config: Config, layout: bullpen.api.Layout, colors: bullpen.api.Color):

        self.scrolling_speed = config.scrolling_speed
        self.time_fmt_str = config.time_fmt_str

        self.scrolls = -1

        self.bg = colors.graphics_color("default.background")

        self.tournament_coords = layout.coords("grand_slam.tournament")
        self.tournament_font = layout.font("grand_slam.tournament")
        self.tournament_color = colors.graphics_color("grand_slam.tournament")

        self.player_font = layout.font("grand_slam.player")
        self.player_color = colors.graphics_color("grand_slam.player")
        self.serving_color = colors.graphics_color("grand_slam.serving")
        self.winner_color = colors.graphics_color("grand_slam.winner")

        self.p1_coords = layout.coords("grand_slam.p1")
        self.p2_coords = layout.coords("grand_slam.p2")

        self.time_coords = layout.coords("grand_slam.time")
        self.time_font = layout.font("grand_slam.time")
        self.time_color = colors.graphics_color("grand_slam.time")

    def can_render(self, data):
        return bool(data.matches)

    def wait_time(self) -> float:
        return self.scrolling_speed

    def render(
        self, data: Data, canvas: "Canvas", graphics: bullpen.api.renderer.graphics, scrolling_text_pos: int
    ) -> int:

        canvas.Fill(self.bg.red, self.bg.green, self.bg.blue)

        if scrolling_text_pos == canvas.width:
            self.scrolls += 1
            if self.scrolls and self.scrolls % 2 == 0:
                data.match_idx += 1
                data.match_idx = data.match_idx % len(data.matches)
                LOGGER.debug("Moving to trains starting at stop %d", data.match_idx)

        match = data.matches[data.match_idx]

        title_text = match.tournament
        if match.round_name:
            title_text += f" - {ROUND_ABBR.get(match.round_name, match.round_name)}"

        lengths = []
        lengths.append(
            scrolling_text(
                canvas,
                graphics,
                self.tournament_coords["x"],
                self.tournament_coords["y"],
                self.tournament_coords["width"],
                self.tournament_font,
                self.tournament_color,
                self.bg,
                title_text,
                scrolling_text_pos,
                force_scroll=False,
            )
        )

        p1_score = " ".join(str(s) for s in match.away_sets)
        p2_score = " ".join(str(s) for s in match.home_sets)
        font_width = self.player_font["size"]["width"]
        length = max(font_width * len(p1_score), font_width * len(p2_score))

        avail = canvas.width - self.p1_coords["x"]
        name_width = avail - length
        p1_color = self.player_color
        if match.away_serving:
            p1_color = self.serving_color
        if match.away_winner:
            p1_color = self.winner_color
        lengths.append(
            scrolling_text(
                canvas,
                graphics,
                self.p1_coords["x"],
                self.p1_coords["y"],
                name_width,
                self.player_font,
                self.player_color,
                self.bg,
                match.away_name,
                scrolling_text_pos,
                center=False,
                force_scroll=False,
            )
        )

        graphics.DrawText(
            canvas,
            self.player_font["font"],
            self.p1_coords["x"] + name_width,
            self.p1_coords["y"],
            p1_color,
            p1_score,
        )

        avail = canvas.width - self.p2_coords["x"]
        name_width = avail - length
        p2_color = self.player_color
        if match.home_serving:
            p2_color = self.serving_color
        if match.home_winner:
            p2_color = self.winner_color
        lengths.append(
            scrolling_text(
                canvas,
                graphics,
                self.p2_coords["x"],
                self.p2_coords["y"],
                name_width,
                self.player_font,
                p2_color,
                self.bg,
                match.home_name,
                scrolling_text_pos,
                center=False,
                force_scroll=False,
            )
        )

        graphics.DrawText(
            canvas,
            self.player_font["font"],
            self.p2_coords["x"] + name_width,
            self.p2_coords["y"],
            self.player_color,
            p2_score,
        )

        if match.kind == "pregame":
            lengths.append(
                scrolling_text(
                    canvas,
                    graphics,
                    self.time_coords["x"],
                    self.time_coords["y"],
                    self.time_coords["width"],
                    self.time_font,
                    self.time_color,
                    self.bg,
                    match.display_time,
                    scrolling_text_pos,
                    force_scroll=False,
                )
            )
        elif match.kind == "postgame" and match.status_note:
            lengths.append(
                scrolling_text(
                    canvas,
                    graphics,
                    self.time_coords["x"],
                    self.time_coords["y"],
                    self.time_coords["width"],
                    self.time_font,
                    self.time_color,
                    self.bg,
                    match.status_note,
                    scrolling_text_pos,
                    force_scroll=False,
                )
            )

        return max(lengths)


def load() -> bullpen.api.PLUGIN_DEFINITION:
    return Config, Data, Renderer
