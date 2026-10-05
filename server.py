"""Read-only Yahoo Fantasy Hockey MCP server (remote / streamable HTTP).

Built on the same yahoo_fantasy_api library the community Yahoo Fantasy MCP
servers use. Only GET-style read calls are exposed; there are no tools that
change rosters, lineups, adds or drops.
"""
import contextlib
import datetime
import os

import uvicorn
import yahoo_fantasy_api as yfa
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from yahoo_oauth import OAuth2

SECRET = os.environ["MCP_SECRET"]  # long random string; becomes part of the URL
OAUTH_FILE = os.environ.get("OAUTH_FILE", "oauth2.json")
SPORT = os.environ.get("YAHOO_SPORT", "nhl")
DEFAULT_LEAGUE = os.environ.get("DEFAULT_LEAGUE_ID")  # e.g. "453.l.12345"

# On a host, the token file arrives as an env var; write it out on first start.
if not os.path.exists(OAUTH_FILE) and os.environ.get("YAHOO_OAUTH_JSON"):
    with open(OAUTH_FILE, "w") as f:
        f.write(os.environ["YAHOO_OAUTH_JSON"])

_sc = None
_leagues = {}

def sc():
    """OAuth session, refreshed when the access token has expired."""
    global _sc
    if _sc is None:
        _sc = OAuth2(None, None, from_file=OAUTH_FILE)
    if not _sc.token_is_valid():
        _sc.refresh_access_token()
    return _sc

def league(league_id=None):
    s = sc()
    lid = league_id or DEFAULT_LEAGUE
    if not lid:
        lid = yfa.Game(s, SPORT).league_ids()[-1]
    if lid not in _leagues:
        _leagues[lid] = yfa.League(s, lid)
    return _leagues[lid]

def _day(day):
    return datetime.date.fromisoformat(day) if day else None

mcp = FastMCP("yahoo-fantasy-hockey-readonly", host="0.0.0.0", stateless_http=True)

@mcp.tool()
def list_leagues():
    """List your Yahoo NHL fantasy league keys (like '453.l.12345')."""
    return yfa.Game(sc(), SPORT).league_ids()

@mcp.tool()
def league_settings(league_id: str | None = None):
    """League settings: scoring, roster slots, trade/waiver rules."""
    return league(league_id).settings()

@mcp.tool()
def teams(league_id: str | None = None):
    """All teams in the league with their team keys."""
    return league(league_id).teams()

@mcp.tool()
def standings(league_id: str | None = None):
    """Current league standings."""
    return league(league_id).standings()

@mcp.tool()
def my_roster(league_id: str | None = None, day: str | None = None):
    """Your roster with slots. day is optional, as YYYY-MM-DD."""
    lg = league(league_id)
    return lg.to_team(lg.team_key()).roster(day=_day(day))

@mcp.tool()
def team_roster(team_key: str, league_id: str | None = None, day: str | None = None):
    """Another team's roster. Get team keys from the teams tool."""
    return league(league_id).to_team(team_key).roster(day=_day(day))

@mcp.tool()
def matchups(league_id: str | None = None, week: int | None = None):
    """Head-to-head matchups for a week (current week if omitted)."""
    return league(league_id).matchups(week=week)

@mcp.tool()
def free_agents(position: str, league_id: str | None = None, limit: int = 25):
    """Available free agents at a position: C, LW, RW, D or G."""
    return league(league_id).free_agents(position)[:limit]

@mcp.tool()
def player_details(name: str, league_id: str | None = None):
    """Look up a player by name."""
    return league(league_id).player_details(name)

@mcp.tool()
def recent_transactions(league_id: str | None = None, count: int = 15):
    """Recent adds, drops and trades in the league."""
    return league(league_id).transactions("add,drop,trade", count)

mcp_app = mcp.streamable_http_app()

@contextlib.asynccontextmanager
async def lifespan(_):
    async with mcp.session_manager.run():
        yield

async def health(_):
    return PlainTextResponse("ok")

app = Starlette(
    routes=[Route("/health", health), Mount(f"/{SECRET}", app=mcp_app)],
    lifespan=lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
