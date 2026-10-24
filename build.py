"""Gameday Notes data builder.

Downloads nflverse data, picks each team's QB1, RB1-2, WR1-3, TE1-2 from the
latest depth chart, and computes birthdays, career/season totals, round-number
milestones in reach, 2026 league ranks and "vs former team" flags.
Merges two hand-researched inputs from the same folder:
  pfr_leaderboard.json  - Pro Football Reference "Upcoming Milestones and Leaderboard Movement"
  news.json             - notable personal/off-field events
  anniversaries.json    - dated family losses (parents, siblings, children...) for anniversary flags
Writes data.js (window.GAMEDAY = {...}) for the page.

Usage: python3 -I build.py <workdir>
"""
import sys, os, json, glob, math, subprocess, datetime as dt
import pandas as pd

SEASON = 2026
W = sys.argv[1] if len(sys.argv) > 1 else "."
os.chdir(W)
REL = "https://github.com/nflverse/nflverse-data/releases/download"
FILES = {
    "games.csv": f"{REL}/schedules/games.csv",
    "players.csv": f"{REL}/players/players.csv",
    f"depth_charts_{SEASON}.csv": f"{REL}/depth_charts/depth_charts_{SEASON}.csv",
    f"reg/reg_{SEASON}.csv": f"{REL}/stats_player/stats_player_reg_{SEASON}.csv",
    f"stats_player_week_{SEASON}.csv": f"{REL}/stats_player/stats_player_week_{SEASON}.csv",
}
os.makedirs("reg", exist_ok=True)
for y in range(1999, SEASON):
    FILES.setdefault(f"reg/reg_{y}.csv", f"{REL}/stats_player/stats_player_reg_{y}.csv")
fresh = "--no-download" not in sys.argv
for f, u in FILES.items():
    is_current = str(SEASON) in f or f in ("games.csv", "players.csv")
    if fresh and (is_current or not os.path.exists(f)):
        subprocess.run(["curl", "-sfL", "--max-time", "180", "-o", f, u], check=True)

games = pd.read_csv("games.csv")
games = games[games.season == SEASON].copy()
players = pd.read_csv("players.csv", low_memory=False).set_index("gsis_id")
dc = pd.read_csv(f"depth_charts_{SEASON}.csv", low_memory=False)
dc_time = dc.dt.max()
dc = dc[(dc.dt == dc_time) & (dc.pos_abb.isin(["QB", "RB", "WR", "TE"]))]
dc = dc[dc.pos_grp.str.contains("WR")]  # offensive base formation group
WANT = {"QB": 2, "RB": 3, "WR": 5, "TE": 3}
dc = dc.sort_values(["team", "pos_abb", "pos_rank"])
dc = dc[dc.pos_rank <= dc.pos_abb.map(WANT)]

# ---- career + season stats ----
regs = []
for f in sorted(glob.glob("reg/reg_*.csv")):
    regs.append(pd.read_csv(f, low_memory=False))
reg = pd.concat(regs, ignore_index=True).copy()
reg = reg[reg.season_type.isin(["REG"]) | reg.season_type.isna()] if "season_type" in reg else reg
STATS = {
    "games": "Games", "passing_yards": "Passing Yds", "passing_tds": "Passing TD",
    "completions": "Completions", "attempts": "Pass Attempts",
    "carries": "Rush Attempts", "rushing_yards": "Rushing Yds", "rushing_tds": "Rushing TD",
    "receptions": "Receptions", "receiving_yards": "Receiving Yds", "receiving_tds": "Receiving TD",
}
for c in STATS:
    reg[c] = pd.to_numeric(reg[c], errors="coerce").fillna(0)
reg["scrim_yds"] = reg.rushing_yards + reg.receiving_yards
reg["total_td"] = reg.rushing_tds + reg.receiving_tds
STATS.update({"scrim_yds": "Scrimmage Yds", "total_td": "Rush+Rec TD"})
career = reg.groupby("player_id")[list(STATS)].sum()
season = reg[reg.season == SEASON].set_index("player_id")
# teams by season, for former-team flags
team_hist = reg.groupby(["player_id", "recent_team"]).season.agg(["min", "max"]).reset_index()

wk = pd.read_csv(f"stats_player_week_{SEASON}.csv", low_memory=False)
wk = wk[wk.season_type == "REG"]
through_week = int(wk.week.max()) if len(wk) else 0
played = games[games.home_score.notna()]
last_played = played.sort_values("gameday").iloc[-1] if len(played) else None

# 2026 league ranks among all players
RANK_STATS = ["passing_yards", "passing_tds", "rushing_yards", "rushing_tds",
              "receptions", "receiving_yards", "receiving_tds", "scrim_yds"]
s_all = reg[reg.season == SEASON].copy()
ranks = {}
for c in RANK_STATS:
    col = s_all[["player_id", c]]
    col = col[col[c] > 0]
    r = col[c].rank(ascending=False, method="min")
    for pid, v, rk in zip(col.player_id, col[c], r):
        ranks.setdefault(pid, {})[c] = (int(rk), float(v))

# milestone step sizes (career round numbers)
STEPS = {"passing_yards": 5000, "passing_tds": 25, "completions": 500, "attempts": 1000,
         "rushing_yards": 1000, "rushing_tds": 10, "carries": 500, "receptions": 100,
         "receiving_yards": 1000, "receiving_tds": 10, "scrim_yds": 1000, "total_td": 10,
         "games": 50}
SEASON_MARKS = {"passing_yards": [3000, 4000, 5000], "passing_tds": [20, 30, 40],
                "rushing_yards": [500, 1000, 1500, 2000], "rushing_tds": [10, 15],
                "receptions": [50, 100], "receiving_yards": [500, 1000, 1500],
                "receiving_tds": [10, 15], "scrim_yds": [1000, 1500, 2000]}
POS_STATS = {"QB": ["passing_yards", "passing_tds", "completions", "attempts", "rushing_yards", "rushing_tds", "games"],
             "RB": ["rushing_yards", "rushing_tds", "carries", "receptions", "receiving_yards", "scrim_yds", "total_td", "games"],
             "WR": ["receptions", "receiving_yards", "receiving_tds", "scrim_yds", "total_td", "games"],
             "TE": ["receptions", "receiving_yards", "receiving_tds", "total_td", "games"]}
POS_RANKS = {"QB": ["passing_yards", "passing_tds", "rushing_yards"],
             "RB": ["rushing_yards", "rushing_tds", "scrim_yds", "receptions"],
             "WR": ["receiving_yards", "receptions", "receiving_tds"],
             "TE": ["receiving_yards", "receptions", "receiving_tds"]}

NOUN = {"passing_yards": "passing yards", "passing_tds": "passing TDs", "completions": "completions",
        "attempts": "pass attempts", "carries": "carries", "rushing_yards": "rushing yards",
        "rushing_tds": "rushing TDs", "receptions": "receptions", "receiving_yards": "receiving yards",
        "receiving_tds": "receiving TDs", "scrim_yds": "scrimmage yards", "total_td": "rushing + receiving TDs"}

def fmt(n):
    return f"{int(round(n)):,}"

def milestones(pid, pos):
    out = []
    if pid not in career.index:
        return out
    c = career.loc[pid]
    g = max(c["games"], 1)
    sg = season.loc[pid] if pid in season.index else None
    for st in POS_STATS[pos]:
        cur = c[st]
        step = STEPS[st]
        if st == "games":
            nxt = (int(cur) // step + 1) * step
            need = nxt - cur
            if need == 1:
                out.append({"kind": "career", "stat": STATS[st], "cur": int(cur), "target": nxt,
                            "need": 1, "tier": "next", "text": f"Plays career game No. {nxt} today"})
            continue
        if cur <= 0:
            continue
        nxt = (math.floor(cur / step) + 1) * step
        need = nxt - cur
        # use recent per-game pace (this season if available) to judge reach
        pace = cur / g
        if sg is not None and sg["games"] > 0:
            pace = max(pace, sg[st] / sg["games"]) if st in sg else pace
        if pace <= 0:
            continue
        tier = "next" if need <= pace * 1.1 else ("soon" if need <= pace * 3 else None)
        if tier:
            out.append({"kind": "career", "stat": STATS[st], "cur": int(cur), "target": int(nxt),
                        "need": int(math.ceil(need)), "tier": tier,
                        "text": f"{fmt(need)} away from {fmt(nxt)} career {NOUN[st]}"})
    if sg is not None and sg["games"] > 0:
        for st, marks in SEASON_MARKS.items():
            if st not in POS_STATS[pos] and st not in ("scrim_yds",):
                continue
            if pos in ("WR", "TE") and st.startswith("rush"):
                continue
            cur = sg[st] if st in sg else 0
            pace = cur / sg["games"]
            for m in marks:
                if cur < m and pace > 0:
                    need = m - cur
                    tier = "next" if need <= pace * 1.1 else None
                    if tier:
                        out.append({"kind": "season", "stat": STATS[st], "cur": int(cur), "target": m,
                                    "need": int(math.ceil(need)), "tier": tier,
                                    "text": f"{fmt(need)} away from {fmt(m)} {NOUN[st]} this season"})
                    break
    order = {"next": 0, "soon": 1}
    out.sort(key=lambda m: (order[m["tier"]], m["kind"] != "career"))
    return out

def iso(d):
    try:
        return str(pd.to_datetime(d).date())
    except Exception:
        return None

tracked = []
for _, row in dc.iterrows():
    pid = row.gsis_id
    if not isinstance(pid, str):
        continue
    p = players.loc[pid] if pid in players.index else None
    pos = row.pos_abb
    rk = ranks.get(pid, {})
    lr = []
    for st in POS_RANKS[pos]:
        if st in rk and rk[st][0] <= 32:
            lr.append({"stat": STATS[st], "rank": rk[st][0], "value": int(rk[st][1])})
    c = career.loc[pid] if pid in career.index else None
    s = season.loc[pid] if pid in season.index else None
    th = team_hist[team_hist.player_id == pid]
    former = [{"team": t, "from": int(a), "to": int(b)} for t, a, b in zip(th.recent_team, th["min"], th["max"])
              if t != row.team]
    def stat_line(src):
        if src is None:
            return None
        keys = {"QB": ["games", "completions", "attempts", "passing_yards", "passing_tds", "rushing_yards", "rushing_tds"],
                "RB": ["games", "carries", "rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"],
                "WR": ["games", "receptions", "receiving_yards", "receiving_tds"],
                "TE": ["games", "receptions", "receiving_yards", "receiving_tds"]}[pos]
        return {k: int(src[k]) for k in keys}
    tracked.append({
        "id": pid, "name": row.player_name, "team": row.team, "pos": pos, "depth": int(row.pos_rank),
        "birth": iso(p.birth_date) if p is not None else None,
        "college": (p.college_name if p is not None and isinstance(p.college_name, str) else None),
        "draft": (f"{int(p.draft_year)} Rd {int(p.draft_round)}, No. {int(p.draft_pick)}"
                  if p is not None and not pd.isna(p.draft_round) else
                  ("Undrafted" if p is not None and not pd.isna(p.rookie_season) else None)),
        "exp": int(p.years_of_experience) if p is not None and not pd.isna(p.years_of_experience) else None,
        "pfr": p.pfr_id if p is not None and isinstance(p.pfr_id, str) else None,
        "headshot": p.headshot if p is not None and isinstance(p.headshot, str) else None,
        "career": stat_line(c), "season": stat_line(s),
        "milestones": milestones(pid, pos), "ranks": lr, "former": former,
    })

sched = []
for _, g in games.iterrows():
    sched.append({"id": g.game_id, "week": int(g.week), "type": g.game_type, "date": g.gameday,
                  "day": g.weekday, "time": g.gametime if isinstance(g.gametime, str) else "",
                  "away": g.away_team, "home": g.home_team,
                  "as": None if pd.isna(g.away_score) else int(g.away_score),
                  "hs": None if pd.isna(g.home_score) else int(g.home_score),
                  "stadium": g.stadium if isinstance(g.stadium, str) else ""})

def load(name, default):
    try:
        with open(name) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default

pfr = load("pfr_leaderboard.json", {"asof": None, "milestones": [], "leaderboards": []})
news = load("news.json", {"asof": None, "items": []})
anniv = load("anniversaries.json", {"asof": None, "researched": [], "items": []})
out = {
    "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "season": SEASON, "throughWeek": through_week,
    "lastGame": None if last_played is None else f"{last_played.away_team} at {last_played.home_team}, {pd.to_datetime(last_played.gameday):%a %b} {pd.to_datetime(last_played.gameday).day}",
    "depthChartAsOf": dc_time,
    "games": sched, "players": tracked, "pfr": pfr, "news": news, "anniv": anniv,
}
with open("data.js", "w") as fh:
    fh.write("window.GAMEDAY=" + json.dumps(out, separators=(",", ":")) + ";\n")
print(f"players={len(tracked)} games={len(sched)} throughWeek={through_week} "
      f"milestones={sum(len(p['milestones']) for p in tracked)} news={len(news.get('items', []))}")
