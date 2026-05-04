"""
Pro Hockey Veteran Tracker — build script
==========================================
Runs weekly via GitHub Actions (see .github/workflows/weekly_update.yml).
Can also be run locally: `python build_tracker.py`

What it does:
  1. Loads historical career CSVs from data/
  2. Scrapes the current season from EliteProspects
  3. Computes veteran status (260-GP threshold across all tracked leagues)
  4. Writes docs/index.html — the self-contained web app served by GitHub Pages
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import TopDownHockey_Scraper.TopDownHockey_EliteProspects_Scraper as tdhepscrape

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR  = Path("data")
DOCS_DIR  = Path("docs")
MANUAL_DIR = Path("manual")
DOCS_DIR.mkdir(exist_ok=True)

LEAGUES = ["nhl", "ahl", "echl", "khl", "shl", "liiga", "czechia", "slovakia", "del", "nl"]

LEAGUE_CSV = {
    "nhl":      "nhl_career_1516_2425.csv",
    "ahl":      "ahl_career_1516_2425.csv",
    "echl":     "echl_career_1516_2425.csv",
    "khl":      "khl_career_1516_2425.csv",
    "shl":      "shl_career_1516_2425.csv",
    "liiga":    "liiga_career_1516_2425.csv",
    "czechia":  "czechia_career_1516_2425.csv",
    "slovakia": "slovakia_career_1516_2425.csv",
    "del":      "del_career_1516_2425.csv",
    "nl":       "nl_career_1516_2425.csv",
}

VET_THRESHOLD = 260
UFA_THRESHOLD = 190   # Non-Vet UFA: 190–259 career GP

# NHLe conversion factors — applied per season-league row before career aggregation.
# Source: Desjardins / Bacon / Vollman consensus estimates.
# NHL = 1.0 by definition; ECHL is the baseline for this tracker.
NHLE_FACTORS = {
    "nhl":      1.00,
    "khl":      0.62,
    "ahl":      0.44,
    "shl":      0.43,
    "liiga":    0.42,
    "nl":       0.40,
    "del":      0.37,
    "czechia":  0.37,
    "slovakia": 0.28,
    "echl":     0.27,
}

# League tier for sorting call-up/send-down display (lower = higher tier)
LEAGUE_TIER = {
    "nhl": 1, "khl": 2, "ahl": 2,
    "shl": 3, "liiga": 3, "echl": 3,
    "del": 4, "czechia": 4, "nl": 4, "slovakia": 4,
}

LEAGUE_LABELS = {
    "nhl": "NHL", "ahl": "AHL", "echl": "ECHL", "khl": "KHL",
    "shl": "SHL", "liiga": "Liiga", "czechia": "Czechia",
    "slovakia": "Slovakia", "del": "DEL", "nl": "NL",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def current_season_str() -> str:
    """Return e.g. '2025-2026' based on today's date.
    Hockey seasons start in September, so Oct–Aug belong to the season
    that started the previous calendar year.
    """
    today = date.today()
    if today.month >= 9:
        start = today.year
    else:
        start = today.year - 1
    return f"{start}-{start + 1}"


def load_historical() -> pd.DataFrame:
    frames = []
    for league, fname in LEAGUE_CSV.items():
        path = DATA_DIR / fname
        if not path.exists():
            print(f"  WARNING: {path} not found — skipping.")
            continue
        df = pd.read_csv(path)
        frames.append(df)
        print(f"  Loaded {len(df):,} rows from {fname}")
    return pd.concat(frames, ignore_index=True)


def load_manual() -> pd.DataFrame | None:
    """
    Check manual/ folder for a preprocessed current_season.csv.
    Returns the dataframe if found, None otherwise.
    """
    manual_file = MANUAL_DIR / "current_season.csv"
    if manual_file.exists():
        df = pd.read_csv(manual_file)
        print(f"  ✅  Loaded manual fallback: {manual_file} ({len(df):,} rows)")
        return df
    return None


def clean_numeric(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["gp", "g", "a", "tp", "pim"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
    df["ppg"]  = pd.to_numeric(df["ppg"],  errors="coerce").fillna(0.0)
    df["+/-"]  = pd.to_numeric(df["+/-"],  errors="coerce").fillna(0).astype("int64")
    return df


def compute_veterans(df: pd.DataFrame, current_season: str) -> pd.DataFrame:
    not_current = df["season"] != current_season

    # Legacy: already had 260+ GP before this season
    legacy_gp = df[not_current].groupby("link")["gp"].sum()
    df["legacy_veteran"] = df["link"].map(legacy_gp).fillna(0) >= VET_THRESHOLD

    # New vet: crossed the threshold during this season
    pre_gp   = df[not_current].groupby("link")["gp"].sum()
    total_gp = df.groupby("link")["gp"].sum()
    df["new_veteran"] = df["link"].map(
        lambda x: (pre_gp.get(x, 0) < VET_THRESHOLD) and (total_gp.get(x, 0) >= VET_THRESHOLD)
    )
    return df


def build_summary(df: pd.DataFrame, current_season: str) -> pd.DataFrame:
    # Apply NHLe factor per season-league row BEFORE aggregating —
    # this gives a true career NHLe stat line weighted by league strength.
    df = df.copy()
    df["nhle_factor"] = df["league"].map(NHLE_FACTORS).fillna(0.27)
    df["nhle_g"]  = (df["g"]  * df["nhle_factor"])
    df["nhle_a"]  = (df["a"]  * df["nhle_factor"])
    df["nhle_tp"] = (df["tp"] * df["nhle_factor"])

    df_sorted = df.sort_values("season", ascending=False)

    vet_df = df_sorted.groupby("link").agg(
        player          =("player",          "first"),
        position        =("position",        "first"),
        total_gp        =("gp",              "sum"),
        total_g         =("g",               "sum"),
        total_a         =("a",               "sum"),
        total_tp        =("tp",              "sum"),
        total_pim       =("pim",             "sum"),
        total_pm        =("+/-",             "sum"),
        nhle_g          =("nhle_g",          "sum"),
        nhle_a          =("nhle_a",          "sum"),
        nhle_tp         =("nhle_tp",         "sum"),
        legacy_veteran  =("legacy_veteran",  "first"),
        new_veteran     =("new_veteran",     "first"),
        league          =("league",          "first"),
    ).reset_index()

    vet_df["total_ppg"] = (
        vet_df["total_tp"] / vet_df["total_gp"].replace(0, 1)
    ).round(2)

    # Round NHLe counting stats and compute NHLe PPG
    vet_df["nhle_g"]   = vet_df["nhle_g"].round(1)
    vet_df["nhle_a"]   = vet_df["nhle_a"].round(1)
    vet_df["nhle_tp"]  = vet_df["nhle_tp"].round(1)
    vet_df["nhle_ppg"] = (
        vet_df["nhle_tp"] / vet_df["total_gp"].replace(0, 1)
    ).round(2)

    # Active = played at least 1 GP in current season
    cur_gp = df[df["season"] == current_season].groupby("link")["gp"].sum()
    vet_df["active"] = vet_df["link"].map(cur_gp).fillna(0) > 0

    # Call-Up / Send-Down: all leagues in each player's most recent season.
    # Uses hybrid fallback — if not in current season, uses last season they appeared.
    # Shows "—" for players who only played in one league that season.
    most_recent_season = df.groupby("link")["season"].max()
    df["_mrs"] = df["link"].map(most_recent_season)
    mrs_df = df[df["season"] == df["_mrs"]]
    cusd_map = mrs_df.groupby("link")["league"].apply(
        lambda x: sorted(set(x), key=lambda lg: LEAGUE_TIER.get(lg, 99))
    )
    def fmt_cusd(lgs):
        if len(lgs) < 2:
            return "—"
        return " ↕ ".join(LEAGUE_LABELS.get(lg, lg.upper()) for lg in lgs)
    vet_df["call_up_send_down"] = vet_df["link"].map(cusd_map).map(fmt_cusd).fillna("—")

    # Non-Vet UFA: 190–259 career GP, not already a veteran
    vet_df["non_vet_ufa"] = (
        (vet_df["total_gp"] >= UFA_THRESHOLD) &
        (vet_df["total_gp"] < VET_THRESHOLD) &
        (~vet_df["legacy_veteran"]) &
        (~vet_df["new_veteran"])
    )

    # Clean player name — strip trailing "(POS)" added by scraper
    vet_df["player"] = vet_df["player"].str.replace(r"\s*\([^)]+\)\s*$", "", regex=True).str.strip()

    cols = [
        "player", "position", "link",
        "total_gp", "total_g", "total_a", "total_tp", "total_ppg",
        "total_pim", "total_pm",
        "nhle_g", "nhle_a", "nhle_tp", "nhle_ppg",
        "legacy_veteran", "new_veteran", "non_vet_ufa",
        "league", "call_up_send_down", "active",
    ]
    return vet_df[cols]


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pro Hockey Veteran Tracker</title>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0d1117; --surface: #161b22; --surface2: #1c2330; --border: #2a3441;
    --gold: #e8b84b; --gold-dim: #a07e2a; --green: #2ea043; --red: #da3633;
    --blue: #58a6ff; --orange: #f0883e; --text: #e6edf3; --text-muted: #8b949e;
  }}
  body {{ font-family: 'Barlow', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }}

  .header {{ background: linear-gradient(135deg,#0d1117 0%,#1a2030 50%,#0d1117 100%); border-bottom: 2px solid var(--gold); padding: 20px 32px; display: flex; align-items: center; gap: 20px; }}
  .header-icon {{ width:48px;height:48px;background:var(--gold);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0; }}
  .header-text {{ display:flex;flex-direction:column;gap:3px; }}
  .header-title-row {{ display:flex;align-items:center;gap:10px; }}
  .header-text h1 {{ font-family:'Barlow Condensed',sans-serif;font-size:28px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:var(--text); }}
  .header-text .brand {{ font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--gold); }}
  .info-btn {{ display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;border:1.5px solid var(--text-muted);color:var(--text-muted);font-size:11px;font-weight:700;cursor:pointer;position:relative;flex-shrink:0;transition:all .2s;font-family:'Barlow Condensed',sans-serif; }}
  .info-btn:hover {{ border-color:var(--gold);color:var(--gold); }}
  .info-panel {{ display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:24px;width:520px;max-width:90vw;max-height:80vh;overflow-y:auto;z-index:1000;box-shadow:0 20px 60px rgba(0,0,0,.7); }}
  .info-panel.open {{ display:block; }}
  .info-overlay {{ display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:999; }}
  .info-overlay.open {{ display:block; }}
  .info-panel-title {{ font-family:'Barlow Condensed',sans-serif;font-size:15px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:var(--gold);margin-bottom:16px;display:flex;justify-content:space-between;align-items:center; }}
  .info-close {{ background:transparent;border:none;color:var(--text-muted);font-size:18px;cursor:pointer;line-height:1;padding:0; }}
  .info-close:hover {{ color:var(--text); }}
  .info-section {{ margin-bottom:18px; }}
  .info-section:last-child {{ margin-bottom:0; }}
  .info-section-head {{ font-family:'Barlow Condensed',sans-serif;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border);padding-bottom:5px;margin-bottom:10px; }}
  .info-row {{ display:flex;gap:12px;margin-bottom:8px;align-items:flex-start; }}
  .info-row:last-child {{ margin-bottom:0; }}
  .info-term {{ font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;color:var(--gold);white-space:nowrap;min-width:120px;padding-top:1px; }}
  .info-def {{ font-size:12px;color:var(--text-muted);line-height:1.5; }}
  .info-note {{ background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px 12px;font-size:11px;color:var(--text-muted);line-height:1.5;margin-top:14px; }}
  .header-meta {{ margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:4px; }}
  .header-season {{ background:var(--surface2);border:1px solid var(--gold-dim);border-radius:6px;padding:6px 14px;font-family:'Barlow Condensed',sans-serif;font-size:14px;font-weight:700;color:var(--gold);letter-spacing:1px; }}
  .header-updated {{ font-size:11px;color:var(--text-muted); }}

  .stats-bar {{ display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border-bottom:1px solid var(--border); }}
  .stat-card {{ background:var(--surface);padding:16px 24px;text-align:center; }}
  .stat-card .num {{ font-family:'Barlow Condensed',sans-serif;font-size:32px;font-weight:800;line-height:1; }}
  .stat-card .label {{ font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:var(--text-muted);margin-top:4px; }}
  .num-gold {{ color:var(--gold); }} .num-green {{ color:var(--green); }} .num-blue {{ color:var(--blue); }} .num-white {{ color:var(--text); }}

  .controls {{ padding:16px 24px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end; }}
  .control-group {{ display:flex;flex-direction:column;gap:5px; }}
  .control-group label {{ font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);font-weight:600; }}
  input[type="text"], select {{ background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:'Barlow',sans-serif;font-size:14px;padding:8px 12px;outline:none;transition:border-color .2s; }}
  input[type="text"] {{ min-width:260px; }}
  input[type="text"]:focus, select:focus {{ border-color:var(--gold); }}
  select {{ cursor:pointer;min-width:140px; }}
  /* Custom multiselect */
  .ms-wrap {{ position:relative; }}
  .ms-trigger {{ background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-family:'Barlow',sans-serif;font-size:14px;padding:8px 28px 8px 12px;cursor:pointer;min-width:160px;text-align:left;transition:border-color .2s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;width:100%; }}
  .ms-trigger:focus,.ms-trigger.open {{ border-color:var(--gold); }}
  .ms-trigger::after {{ content:'▾';position:absolute;right:10px;top:50%;transform:translateY(-50%);color:var(--text-muted);pointer-events:none; }}
  .ms-dropdown {{ display:none;position:absolute;top:calc(100% + 4px);left:0;background:var(--surface2);border:1px solid var(--border);border-radius:6px;min-width:160px;z-index:200;padding:4px 0;box-shadow:0 8px 24px rgba(0,0,0,.4); }}
  .ms-wrap.open .ms-dropdown {{ display:block; }}
  .ms-option {{ display:flex;align-items:center;gap:8px;padding:7px 12px;cursor:pointer;font-size:13px;transition:background .1s; }}
  .ms-option:hover {{ background:var(--surface); }}
  .ms-option input[type=checkbox] {{ accent-color:var(--gold);width:13px;height:13px;cursor:pointer;flex-shrink:0; }}
  .ms-option.selected {{ color:var(--gold); }}
  .btn-reset {{ background:transparent;border:1px solid var(--border);border-radius:6px;color:var(--text-muted);font-family:'Barlow',sans-serif;font-size:13px;padding:8px 16px;cursor:pointer;transition:all .2s;align-self:flex-end; }}
  .btn-reset:hover {{ border-color:var(--gold);color:var(--gold); }}
  .results-count {{ margin-left:auto;align-self:flex-end;font-size:13px;color:var(--text-muted);white-space:nowrap; }}
  .results-count span {{ color:var(--text);font-weight:600; }}

  .threshold-note {{ font-size:11px;color:var(--text-muted);padding:7px 24px;background:var(--surface);border-bottom:1px solid var(--border); }}
  .threshold-note strong {{ color:var(--gold); }}

  .table-wrap {{ overflow-x:auto;padding-bottom:60px; }}
  table {{ width:100%;border-collapse:collapse;font-size:13px; }}
  thead {{ position:sticky;top:0;z-index:10;background:var(--surface2); }}
  th {{ padding:10px 14px;text-align:left;font-family:'Barlow Condensed',sans-serif;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--text-muted);border-bottom:2px solid var(--border);white-space:nowrap;cursor:pointer;user-select:none;transition:color .15s; }}
  th:hover {{ color:var(--gold); }} th.sorted {{ color:var(--gold); }} th .arr {{ margin-left:4px;opacity:.5; }} th.sorted .arr {{ opacity:1; }}
  td {{ padding:9px 14px;border-bottom:1px solid var(--border);vertical-align:middle;white-space:nowrap; }}
  tr:hover td {{ background:var(--surface2); }}

  .player-name a {{ color:var(--text);font-weight:600;text-decoration:none;transition:color .15s; }}
  .player-name a:hover {{ color:var(--gold);text-decoration:underline; }}
  .pos-badge {{ display:inline-block;background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:2px 6px;font-size:11px;font-weight:600;font-family:'Barlow Condensed',sans-serif;color:var(--text-muted); }}
  .lg {{ display:inline-block;border-radius:4px;padding:2px 7px;font-size:11px;font-weight:700;font-family:'Barlow Condensed',sans-serif;letter-spacing:.5px;text-transform:uppercase; }}
  .lg-nhl{{background:#003153;color:#a8d0f0}} .lg-ahl{{background:#1a0530;color:#d0a8f0}} .lg-echl{{background:#001a10;color:#a8f0c8}}
  .lg-khl{{background:#200000;color:#f0a8a8}} .lg-shl{{background:#001520;color:#a8d8f0}} .lg-liiga{{background:#1a1000;color:#f0dca8}}
  .lg-czechia{{background:#100018;color:#d4a8f0}} .lg-slovakia{{background:#001a0a;color:#a8f0b8}} .lg-del{{background:#1a0800;color:#f0bca8}} .lg-nl{{background:#0a1a00;color:#c8f0a8}}
  .vb {{ display:inline-flex;align-items:center;gap:5px;border-radius:5px;padding:3px 9px;font-size:11px;font-weight:700;font-family:'Barlow Condensed',sans-serif;letter-spacing:.5px;text-transform:uppercase;white-space:nowrap; }}
  .vb-legacy {{ background:#2a1f00;border:1px solid var(--gold-dim);color:var(--gold); }}
  .vb-new {{ background:#001828;border:1px solid #1a6b9a;color:var(--blue); }}
  .vb-ufa {{ background:#1f0e00;border:1px solid #8a4a00;color:var(--orange); }}
  .vb-none {{ background:transparent;border:1px solid var(--border);color:var(--text-muted); }}
  .dot {{ display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px; }}
  .dot-on {{ background:var(--green);box-shadow:0 0 6px var(--green); }} .dot-off {{ background:var(--border); }}
  .gp-wrap {{ display:flex;align-items:center;gap:8px; }}
  .gp-bg {{ width:70px;height:5px;background:var(--border);border-radius:3px;overflow:hidden;flex-shrink:0; }}
  .gp-fill {{ height:100%;border-radius:3px; }}
  .fill-gold {{ background:var(--gold); }} .fill-grn {{ background:var(--green); }} .fill-mut {{ background:var(--text-muted); }}
  .sn {{ font-family:'Barlow Condensed',sans-serif;font-size:14px; }}
  .sn-hi {{ color:var(--text);font-weight:600; }} .sn-ppg {{ color:var(--gold); }} .sn-nhle {{ color:#7dd3fc; }}

  /* Tab toggle */
  .tab-bar {{ display:flex;align-items:center;gap:0;background:var(--surface);border-bottom:1px solid var(--border);padding:0 24px; }}
  .tab-btn {{ font-family:'Barlow Condensed',sans-serif;font-size:13px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;padding:12px 20px;border:none;border-bottom:3px solid transparent;background:transparent;color:var(--text-muted);cursor:pointer;transition:all .2s;margin-bottom:-1px; }}
  .tab-btn:hover {{ color:var(--text); }}
  .tab-btn.active {{ color:var(--gold);border-bottom-color:var(--gold); }}
  .tab-note {{ margin-left:auto;font-size:11px;color:var(--text-muted);padding:12px 0; }}
  .no-results {{ text-align:center;padding:60px 20px;color:var(--text-muted);font-size:16px; }}
  .no-results .ico {{ font-size:48px;margin-bottom:12px; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-icon">🏒</div>
  <div class="header-text">
    <div class="header-title-row">
      <h1>Pro Hockey Veteran Tracker</h1>
      <div class="info-btn" onclick="toggleInfo()">i</div>
    </div>
    <div class="brand">Batt Analytics</div>
  </div>
  <div class="header-meta">
    <div class="header-season">{season} SEASON</div>
    <div class="header-updated">{updated}</div>
  </div>
</div>

<div class="info-overlay" id="info-overlay" onclick="toggleInfo()"></div>
<div class="info-panel" id="info-panel">
  <div class="info-panel-title">
    Field Guide
    <button class="info-close" onclick="toggleInfo()">✕</button>
  </div>

  <div class="info-section">
    <div class="info-section-head">Veteran Status</div>
    <div class="info-row"><div class="info-term">⭐ Veteran</div><div class="info-def">260+ career GP. Counts against the ECHL veteran roster limit.</div></div>
    <div class="info-row"><div class="info-term">🆕 New Vet</div><div class="info-def">Crossed 260 GP this season. Was a non-veteran at season start.</div></div>
    <div class="info-row"><div class="info-term">🟠 Non-Vet UFA</div><div class="info-def">190–259 GP. Not yet a veteran but UFA-eligible. Watch as a future vet risk.</div></div>
    <div class="info-row"><div class="info-term">245/260</div><div class="info-def">Under threshold. The progress bar shows how close the player is to 260 GP.</div></div>
  </div>

  <div class="info-section">
    <div class="info-section-head">Columns</div>
    <div class="info-row"><div class="info-term">GP</div><div class="info-def">Career games played across all 10 tracked leagues. This number determines veteran status.</div></div>
    <div class="info-row"><div class="info-term">G / A / PTS / PPG / PIM</div><div class="info-def">Career totals across all leagues. Raw and unadjusted for league strength.</div></div>
    <div class="info-row"><div class="info-term">+/−</div><div class="info-def">Career plus/minus. Not available in all leagues.</div></div>
    <div class="info-row"><div class="info-term">Current League</div><div class="info-def">The league the player most recently appeared in.</div></div>
    <div class="info-row"><div class="info-term">Call-Up / Send-Down</div><div class="info-def">Leagues the player appeared in during their most recent season. Two or more (e.g. NHL ↕ AHL) means they moved between levels that year. — means single league only.</div></div>
    <div class="info-row"><div class="info-term">Active</div><div class="info-def">🟢 played this season &nbsp;·&nbsp; ⚫ inactive (injured, unsigned, or retired)</div></div>
  </div>

  <div class="info-section">
    <div class="info-section-head">NHLe Stats Tab</div>
    <div class="info-row"><div class="info-term">What is NHLe?</div><div class="info-def">NHL Equivalency. Normalizes scoring across leagues — a 0.80 PPG player in the ECHL is not the same as 0.80 in the AHL. NHLe converts each season using a league strength factor before summing, so career totals are properly weighted.</div></div>
    <div class="info-row"><div class="info-term">Factors</div><div class="info-def">NHL 1.00 · KHL 0.62 · AHL 0.44 · SHL 0.43 · Liiga 0.42 · NL 0.40 · DEL/Czechia 0.37 · Slovakia 0.28 · ECHL 0.27</div></div>
  </div>

  <div class="info-note">Data source: EliteProspects · Updated weekly every Monday · Regular season only</div>
</div>

<div class="stats-bar">
  <div class="stat-card"><div class="num num-white">{total}</div><div class="label">Total Players</div></div>
  <div class="stat-card"><div class="num num-gold">{legacy}</div><div class="label">Legacy Veterans</div></div>
  <div class="stat-card"><div class="num num-blue">{new_vets}</div><div class="label">New Veterans</div></div>
  <div class="stat-card"><div class="num" style="color:var(--orange)">{ufa_count}</div><div class="label">Non-Vet UFAs</div></div>
  <div class="stat-card"><div class="num num-green">{active}</div><div class="label">Active This Season</div></div>
</div>

<div class="threshold-note">
  <strong>Veteran threshold: 260 career GP</strong> across NHL · AHL · ECHL · KHL · SHL · Liiga · Czechia · Slovakia · DEL · NL. &nbsp;
  <strong>Legacy</strong> = crossed threshold before {season}. &nbsp;<strong>New Vet</strong> = crossed threshold during {season}. &nbsp;
  <strong style="color:var(--orange)">Non-Vet UFA</strong> = 190–259 career GP (UFA-eligible but not yet a veteran).
</div>

<div class="controls">
  <div class="control-group">
    <label>Search Player</label>
    <input type="text" id="search" placeholder="Player name…" autocomplete="off">
  </div>
  <div class="control-group">
    <label>Veteran Status</label>
    <div class="ms-wrap" id="ms-vet">
      <button class="ms-trigger" id="ms-vet-trigger" onclick="toggleMs('ms-vet')">Any Veteran</button>
      <div class="ms-dropdown">
        <div class="ms-option" onclick="toggleVet('legacy',this)"><input type="checkbox" value="legacy"> ⭐ Legacy Veterans</div>
        <div class="ms-option" onclick="toggleVet('new',this)"><input type="checkbox" value="new"> 🆕 New Veterans</div>
        <div class="ms-option" onclick="toggleVet('ufa',this)"><input type="checkbox" value="ufa"> 🟠 Non-Vet UFA (190–259 GP)</div>
        <div class="ms-option" onclick="toggleVet('none',this)"><input type="checkbox" value="none"> Under Threshold (&lt;190 GP)</div>
      </div>
    </div>
  </div>
  <div class="control-group">
    <label>Current League</label>
    <div class="ms-wrap" id="ms-league">
      <button class="ms-trigger" id="ms-league-trigger" onclick="toggleMs('ms-league')">All Leagues</button>
      <div class="ms-dropdown">
        <div class="ms-option" onclick="toggleLeague('nhl',this)"><input type="checkbox" value="nhl"> NHL</div>
        <div class="ms-option" onclick="toggleLeague('ahl',this)"><input type="checkbox" value="ahl"> AHL</div>
        <div class="ms-option" onclick="toggleLeague('echl',this)"><input type="checkbox" value="echl"> ECHL</div>
        <div class="ms-option" onclick="toggleLeague('khl',this)"><input type="checkbox" value="khl"> KHL</div>
        <div class="ms-option" onclick="toggleLeague('shl',this)"><input type="checkbox" value="shl"> SHL</div>
        <div class="ms-option" onclick="toggleLeague('liiga',this)"><input type="checkbox" value="liiga"> Liiga</div>
        <div class="ms-option" onclick="toggleLeague('czechia',this)"><input type="checkbox" value="czechia"> Czechia</div>
        <div class="ms-option" onclick="toggleLeague('slovakia',this)"><input type="checkbox" value="slovakia"> Slovakia</div>
        <div class="ms-option" onclick="toggleLeague('del',this)"><input type="checkbox" value="del"> DEL</div>
        <div class="ms-option" onclick="toggleLeague('nl',this)"><input type="checkbox" value="nl"> NL</div>
      </div>
    </div>
  </div>
  <div class="control-group">
    <label>Call-Up / Send-Down</label>
    <div class="ms-wrap" id="ms-cusd">
      <button class="ms-trigger" id="ms-cusd-trigger" onclick="toggleMs('ms-cusd')">All Players</button>
      <div class="ms-dropdown">
        <div class="ms-option" onclick="toggleCusd('any',this)"><input type="checkbox" value="any"> Any Movement</div>
        <div class="ms-option" onclick="toggleCusd('NHL ↕ AHL',this)"><input type="checkbox" value="NHL ↕ AHL"> NHL ↕ AHL</div>
        <div class="ms-option" onclick="toggleCusd('AHL ↕ ECHL',this)"><input type="checkbox" value="AHL ↕ ECHL"> AHL ↕ ECHL</div>
        <div class="ms-option" onclick="toggleCusd('NHL ↕ ECHL',this)"><input type="checkbox" value="NHL ↕ ECHL"> NHL ↕ ECHL</div>
        <div class="ms-option" onclick="toggleCusd('NHL ↕ AHL ↕ ECHL',this)"><input type="checkbox" value="NHL ↕ AHL ↕ ECHL"> NHL ↕ AHL ↕ ECHL</div>
      </div>
    </div>
  </div>
  <div class="control-group">
    <label>Position</label>
    <select id="fp">
      <option value="">All Positions</option>
      <option value="F">Forwards</option>
      <option value="D">Defense</option>
    </select>
  </div>
  <div class="control-group">
    <label>Active Status</label>
    <select id="fa">
      <option value="">All</option>
      <option value="1">Active ({season})</option>
      <option value="0">Inactive</option>
    </select>
  </div>
  <button class="btn-reset" onclick="reset()">↺ Reset</button>
  <div class="results-count">Showing <span id="rc">—</span> players</div>
</div>

<div class="tab-bar">
  <button class="tab-btn active" id="tab-std" onclick="switchTab('std')">📊 Standard Stats</button>
  <button class="tab-btn" id="tab-nhle" onclick="switchTab('nhle')">🏒 NHLe Stats</button>
  <span class="tab-note" id="tab-note">Career totals · GP, G, A, PTS, PPG, PIM, +/−</span>
</div>

<div class="table-wrap">
  <table>
    <thead id="thead-std"><tr>
      <th onclick="sort('player')" data-c="player">Player <span class="arr">↕</span></th>
      <th onclick="sort('position')" data-c="position">Pos <span class="arr">↕</span></th>
      <th onclick="sort('league')" data-c="league">Current League <span class="arr">↕</span></th>
      <th onclick="sort('total_gp')" data-c="total_gp">GP <span class="arr">↕</span></th>
      <th onclick="sort('total_g')" data-c="total_g">G <span class="arr">↕</span></th>
      <th onclick="sort('total_a')" data-c="total_a">A <span class="arr">↕</span></th>
      <th onclick="sort('total_tp')" data-c="total_tp">PTS <span class="arr">↕</span></th>
      <th onclick="sort('total_ppg')" data-c="total_ppg">PPG <span class="arr">↕</span></th>
      <th onclick="sort('total_pim')" data-c="total_pim">PIM <span class="arr">↕</span></th>
      <th onclick="sort('total_pm')" data-c="total_pm">+/− <span class="arr">↕</span></th>
      <th onclick="sort('call_up_send_down')" data-c="call_up_send_down">Call-Up / Send-Down <span class="arr">↕</span></th>
      <th onclick="sort('legacy_veteran')" data-c="legacy_veteran">Status <span class="arr">↕</span></th>
      <th onclick="sort('active')" data-c="active">Active <span class="arr">↕</span></th>
    </tr></thead>
    <thead id="thead-nhle" style="display:none"><tr>
      <th onclick="sort('player')" data-c="player">Player <span class="arr">↕</span></th>
      <th onclick="sort('position')" data-c="position">Pos <span class="arr">↕</span></th>
      <th onclick="sort('league')" data-c="league">Current League <span class="arr">↕</span></th>
      <th onclick="sort('total_gp')" data-c="total_gp">GP <span class="arr">↕</span></th>
      <th onclick="sort('nhle_g')" data-c="nhle_g">NHLe G <span class="arr">↕</span></th>
      <th onclick="sort('nhle_a')" data-c="nhle_a">NHLe A <span class="arr">↕</span></th>
      <th onclick="sort('nhle_tp')" data-c="nhle_tp">NHLe PTS <span class="arr">↕</span></th>
      <th onclick="sort('nhle_ppg')" data-c="nhle_ppg">NHLe PPG <span class="arr">↕</span></th>
      <th onclick="sort('call_up_send_down')" data-c="call_up_send_down">Call-Up / Send-Down <span class="arr">↕</span></th>
      <th onclick="sort('legacy_veteran')" data-c="legacy_veteran">Status <span class="arr">↕</span></th>
      <th onclick="sort('active')" data-c="active">Active <span class="arr">↕</span></th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table>
  <div id="nr" class="no-results" style="display:none"><div class="ico">🔍</div>No players match your filters.</div>
</div>

<script>
const D={json_data};
const LG={{'nhl':'NHL','ahl':'AHL','echl':'ECHL','khl':'KHL','shl':'SHL','liiga':'Liiga','czechia':'Czechia','slovakia':'Slovakia','del':'DEL','nl':'NL'}};
const NHLE_NOTE='NHLe normalizes scoring across leagues · career totals weighted by league strength (KHL=0.62, AHL=0.44, SHL=0.43, Liiga=0.42, NL=0.40, DEL/Czechia=0.37, Slovakia=0.28, ECHL=0.27)';
const STD_NOTE='Career totals · GP, G, A, PTS, PPG, PIM, +/−';
let sc='total_gp',sa=false,filtered=[],shown=200,curTab='std';
let selectedLeagues=new Set();
let selectedCusd=new Set();
let selectedVet=new Set(['legacy','new']); // default: any veteran

// --- Multiselect: Veteran Status ---
function toggleVet(val,el){{
  const cb=el.querySelector('input[type=checkbox]');
  cb.checked=!cb.checked;
  if(cb.checked){{selectedVet.add(val);el.classList.add('selected');}}
  else{{selectedVet.delete(val);el.classList.remove('selected');}}
  const trigger=document.getElementById('ms-vet-trigger');
  if(selectedVet.size===0){{trigger.textContent='All Players';}}
  else if(selectedVet.has('legacy')&&selectedVet.has('new')&&selectedVet.size===2){{trigger.textContent='Any Veteran';}}
  else{{
    const labels={{'legacy':'Legacy Vets','new':'New Vets','ufa':'Non-Vet UFA','none':'Under Threshold'}};
    trigger.textContent=[...selectedVet].map(v=>labels[v]).join(', ');
  }}
  applyFilters();
}}

// --- Multiselect: Current League ---
function toggleMs(id){{
  const wrap=document.getElementById(id);
  wrap.classList.toggle('open');
  document.getElementById(id+'-trigger').classList.toggle('open',wrap.classList.contains('open'));
}}
function toggleLeague(val,el){{
  const cb=el.querySelector('input[type=checkbox]');
  cb.checked=!cb.checked;
  if(cb.checked){{selectedLeagues.add(val);el.classList.add('selected');}}
  else{{selectedLeagues.delete(val);el.classList.remove('selected');}}
  const trigger=document.getElementById('ms-league-trigger');
  trigger.textContent=selectedLeagues.size===0?'All Leagues':[...selectedLeagues].map(v=>LG[v]).join(', ');
  applyFilters();
}}

// --- Multiselect: Call-Up / Send-Down ---
function toggleCusd(val,el){{
  const cb=el.querySelector('input[type=checkbox]');
  cb.checked=!cb.checked;
  if(cb.checked){{selectedCusd.add(val);el.classList.add('selected');}}
  else{{selectedCusd.delete(val);el.classList.remove('selected');}}
  const trigger=document.getElementById('ms-cusd-trigger');
  if(selectedCusd.size===0){{trigger.textContent='All Players';}}
  else if(selectedCusd.has('any')){{trigger.textContent='Any Movement';}}
  else{{trigger.textContent=[...selectedCusd].join(', ');}}
  applyFilters();
}}

// Close all multiselects when clicking outside
document.addEventListener('click',e=>{{
  ['ms-vet','ms-league','ms-cusd'].forEach(id=>{{
    if(!e.target.closest(`#${{id}}`)){{
      document.getElementById(id).classList.remove('open');
      document.getElementById(id+'-trigger').classList.remove('open');
    }}
  }});
}});

function toggleInfo(){{
  document.getElementById('info-panel').classList.toggle('open');
  document.getElementById('info-overlay').classList.toggle('open');
}}
function isF(p){{if(!p)return false;const u=p.toUpperCase();return /\\b(F|C|LW|RW|W)\\b/.test(u)&&!/\\bD\\b/.test(u.replace(/D\\/F/,''));}}
function isD(p){{return p&&/\\bD\\b/.test(p.toUpperCase());}}
function vs(r){{return r.legacy_veteran?'legacy':r.new_veteran?'new':r.non_vet_ufa?'ufa':'none';}}

function switchTab(tab){{
  curTab=tab;
  document.getElementById('tab-std').classList.toggle('active',tab==='std');
  document.getElementById('tab-nhle').classList.toggle('active',tab==='nhle');
  document.getElementById('thead-std').style.display=tab==='std'?'':'none';
  document.getElementById('thead-nhle').style.display=tab==='nhle'?'':'none';
  document.getElementById('tab-note').textContent=tab==='nhle'?NHLE_NOTE:STD_NOTE;
  if(tab==='nhle'&&sc==='total_tp')sc='nhle_tp';
  if(tab==='std'&&sc==='nhle_tp')sc='total_tp';
  sortArr();render();
}}
function applyFilters(){{
  const s=document.getElementById('search').value.trim().toLowerCase();
  const fp=document.getElementById('fp').value;
  const fa=document.getElementById('fa').value;
  filtered=D.filter(r=>{{
    if(s&&!r.player.toLowerCase().includes(s))return false;
    const v=vs(r);
    if(selectedVet.size>0&&!selectedVet.has(v))return false;
    if(selectedLeagues.size>0&&!selectedLeagues.has(r.league))return false;
    if(selectedCusd.size>0){{
      if(selectedCusd.has('any')){{
        if(r.call_up_send_down==='—')return false;
      }} else {{
        if(![...selectedCusd].includes(r.call_up_send_down))return false;
      }}
    }}
    if(fp==='F'&&!isF(r.position))return false;
    if(fp==='D'&&!isD(r.position))return false;
    if(fa==='1'&&!r.active)return false;
    if(fa==='0'&&r.active)return false;
    return true;
  }});
  sortArr();shown=200;render();
}}
function sortArr(){{
  filtered.sort((a,b)=>{{
    let av=a[sc],bv=b[sc];
    if(typeof av==='string')av=av.toLowerCase();
    if(typeof bv==='string')bv=bv.toLowerCase();
    if(av===bv)return 0;
    return(sa?1:-1)*(av<bv?-1:1);
  }});
}}
function sort(col){{
  if(sc===col)sa=!sa;else{{sc=col;sa=false;}}
  document.querySelectorAll('th').forEach(t=>{{t.classList.remove('sorted');const a=t.querySelector('.arr');if(a)a.textContent='↕';}});
  document.querySelectorAll(`th[data-c="${{col}}"]`).forEach(th=>{{th.classList.add('sorted');th.querySelector('.arr').textContent=sa?'↑':'↓';}});
  sortArr();render();
}}
function lgB(lg){{return `<span class="lg lg-${{lg}}">${{LG[lg]||lg.toUpperCase()}}</span>`;}}
function vetB(r){{
  const v=vs(r);
  if(v==='legacy')return'<span class="vb vb-legacy">⭐ Veteran</span>';
  if(v==='new')return'<span class="vb vb-new">🆕 New Vet</span>';
  if(v==='ufa')return'<span class="vb vb-ufa">🟠 Non-Vet UFA</span>';
  return`<span class="vb vb-none">${{r.total_gp}}/260</span>`;
}}
function gpB(gp){{
  const p=Math.min(100,Math.round(gp/260*100));
  const c=gp>=260?'fill-gold':gp>=200?'fill-grn':'fill-mut';
  return`<div class="gp-wrap"><span class="sn sn-hi">${{gp}}</span><div class="gp-bg"><div class="gp-fill ${{c}}" style="width:${{p}}%"></div></div></div>`;
}}
function pmCell(pm){{
  const col=pm>0?'color:var(--green)':pm<0?'color:var(--red)':'color:var(--text-muted)';
  return`<span class="sn" style="${{col}}">${{pm>0?'+'+pm:pm}}</span>`;
}}
function cusdCell(v){{
  if(!v||v==='—')return`<span style="color:var(--text-muted)">—</span>`;
  const parts=v.split(' ↕ ');
  return parts.map(p=>`<span class="lg lg-${{p.toLowerCase()}}">${{p}}</span>`).join('<span style="color:var(--text-muted);margin:0 2px">↕</span>');
}}
function render(){{
  const tb=document.getElementById('tb');
  const nr=document.getElementById('nr');
  const isNhle=curTab==='nhle';
  document.getElementById('rc').textContent=filtered.length.toLocaleString();
  if(!filtered.length){{tb.innerHTML='';nr.style.display='block';return;}}
  nr.style.display='none';
  const rows=filtered.slice(0,shown).map(r=>{{
    const base=`<td class="player-name"><a href="${{r.link}}" target="_blank" rel="noopener">${{r.player}}</a></td><td><span class="pos-badge">${{r.position||'—'}}</span></td><td>${{lgB(r.league)}}</td><td>${{gpB(r.total_gp)}}</td>`;
    const std=`<td class="sn">${{r.total_g}}</td><td class="sn">${{r.total_a}}</td><td class="sn sn-hi">${{r.total_tp}}</td><td class="sn ${{r.total_ppg>=0.75?'sn-ppg':''}}">${{r.total_ppg.toFixed(2)}}</td><td class="sn">${{r.total_pim}}</td><td>${{pmCell(r.total_pm)}}</td>`;
    const nhle=`<td class="sn sn-nhle">${{r.nhle_g.toFixed(1)}}</td><td class="sn sn-nhle">${{r.nhle_a.toFixed(1)}}</td><td class="sn sn-nhle" style="font-weight:600">${{r.nhle_tp.toFixed(1)}}</td><td class="sn ${{r.nhle_ppg>=0.40?'sn-ppg':''}}">${{r.nhle_ppg.toFixed(2)}}</td>`;
    const tail=`<td>${{cusdCell(r.call_up_send_down)}}</td><td>${{vetB(r)}}</td><td><span class="dot ${{r.active?'dot-on':'dot-off'}}"></span>${{r.active?'Active':'<span style="color:var(--text-muted)">Inactive</span>'}}</td>`;
    return`<tr>${{base}}${{isNhle?nhle:std}}${{tail}}</tr>`;
  }}).join('');
  tb.innerHTML=rows;
  if(filtered.length>shown){{
    const rem=filtered.length-shown;
    const tr=document.createElement('tr');
    tr.innerHTML=`<td colspan="${{isNhle?11:13}}" style="text-align:center;padding:16px"><button onclick="loadMore()" style="background:var(--surface2);border:1px solid var(--border);color:var(--text);font-family:Barlow,sans-serif;font-size:13px;padding:8px 24px;border-radius:6px;cursor:pointer">Load ${{Math.min(rem,200)}} more (${{rem}} remaining)</button></td>`;
    tb.appendChild(tr);
  }}
}}
function loadMore(){{shown+=200;render();}}
function reset(){{
  document.getElementById('search').value='';
  ['fp','fa'].forEach(id=>document.getElementById(id).selectedIndex=0);
  selectedVet=new Set(['legacy','new']);
  document.querySelectorAll('#ms-vet .ms-option').forEach(el=>{{
    const v=el.querySelector('input').value;
    const checked=v==='legacy'||v==='new';
    el.querySelector('input').checked=checked;
    el.classList.toggle('selected',checked);
  }});
  document.getElementById('ms-vet-trigger').textContent='Any Veteran';
  selectedLeagues.clear();
  document.querySelectorAll('#ms-league .ms-option').forEach(el=>{{el.classList.remove('selected');el.querySelector('input').checked=false;}});
  document.getElementById('ms-league-trigger').textContent='All Leagues';
  selectedCusd.clear();
  document.querySelectorAll('#ms-cusd .ms-option').forEach(el=>{{el.classList.remove('selected');el.querySelector('input').checked=false;}});
  document.getElementById('ms-cusd-trigger').textContent='All Players';
  applyFilters();
}}
['search'].forEach(id=>document.getElementById(id).addEventListener('input',applyFilters));
['fp','fa'].forEach(id=>document.getElementById(id).addEventListener('change',applyFilters));
// Boot: default to any veteran (legacy + new checked)
document.querySelectorAll('#ms-vet .ms-option').forEach(el=>{{
  const v=el.querySelector('input').value;
  if(v==='legacy'||v==='new'){{el.querySelector('input').checked=true;el.classList.add('selected');}}
}});
applyFilters();
</script>
</body>
</html>"""


def build_html(vet_df: pd.DataFrame, current_season: str, data_source: str = "scraped") -> str:
    records = json.loads(
        vet_df.to_json(orient="records")
    )

    legacy_count  = int(vet_df["legacy_veteran"].sum())
    new_count     = int(vet_df["new_veteran"].sum())
    ufa_count     = int(vet_df["non_vet_ufa"].sum())
    active_count  = int(vet_df["active"].sum())
    total_count   = len(vet_df)
    updated       = date.today().strftime("%B %d, %Y")
    season_label  = current_season.replace("-", "–")
    source_label  = f"⚠️ Manual data load — {updated}" if data_source == "manual" else f"Updated {updated}"

    html = HTML_TEMPLATE.format(
        json_data  = json.dumps(records, separators=(",", ":")),
        season     = season_label,
        updated    = source_label,
        total      = f"{total_count:,}",
        legacy     = f"{legacy_count:,}",
        new_vets   = f"{new_count:,}",
        ufa_count  = f"{ufa_count:,}",
        active     = f"{active_count:,}",
    )
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    current_season = current_season_str()
    print(f"\n{'='*60}")
    print(f"  Pro Hockey Veteran Tracker — build script")
    print(f"  Season: {current_season}  |  Date: {date.today()}")
    print(f"{'='*60}\n")

    # 1. Load historical data
    print("Loading historical career CSVs...")
    hist_df = load_historical()
    print(f"  Total historical rows: {len(hist_df):,}\n")

    # 2. Manual file takes priority if present — scraper is fallback
    current_stats = None
    data_source = "scraped"

    manual_stats = load_manual()
    if manual_stats is not None:
        print(f"  Manual file found — using manual data, skipping scraper.\n")
        current_stats = manual_stats
        data_source = "manual"
    else:
        print(f"Scraping {current_season} from EliteProspects...")
        try:
            current_stats = tdhepscrape.get_skaters(LEAGUES, current_season)
            # Validate scrape — if all leagues returned 0 GP it's a silent failure
            total_gp = pd.to_numeric(current_stats.get("gp", pd.Series()), errors="coerce").sum()
            if total_gp == 0:
                raise RuntimeError("Scraper returned data but all GP values are 0 — likely a silent failure.")
            print(f"  Scraped {len(current_stats):,} rows\n")
        except Exception as e:
            print(f"  ⚠️  Scraper failed: {e}")
            print(f"  No manual fallback found in '{MANUAL_DIR}/'.")
            print(f"  To use manual data:")
            print(f"    1. Run prepare_manual.py locally")
            print(f"    2. Upload manual/current_season.csv to GitHub")
            print(f"    3. Re-trigger this workflow")
            raise RuntimeError(
                "Scraper failed and no manual fallback available. "
                "See above for instructions."
            )

    # 3. Combine & clean
    print("Processing data...")
    combined = pd.concat([hist_df, current_stats], ignore_index=True)
    combined = clean_numeric(combined)

    # 4. Compute veteran status
    combined = compute_veterans(combined, current_season)

    # 5. Build per-player summary
    vet_df = build_summary(combined, current_season)
    print(f"  Players in database:  {len(vet_df):,}")
    print(f"  Legacy veterans:      {vet_df['legacy_veteran'].sum():,}")
    print(f"  New veterans:         {vet_df['new_veteran'].sum():,}")
    print(f"  Non-Vet UFAs:         {vet_df['non_vet_ufa'].sum():,}")
    print(f"  Active this season:   {vet_df['active'].sum():,}")
    print(f"  Data source:          {data_source}\n")

    # 6. Write HTML to docs/index.html (served by GitHub Pages)
    html = build_html(vet_df, current_season, data_source)
    out_path = DOCS_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  ✅  Wrote {out_path}  ({out_path.stat().st_size / 1_048_576:.1f} MB)")

    # 7. Also save the raw CSV for reference / auditing
    csv_path = DOCS_DIR / "pro_hockey_vets_latest.csv"
    vet_df.to_csv(csv_path, index=False)
    print(f"  ✅  Wrote {csv_path}\n")

    print("Build complete.\n")


if __name__ == "__main__":
    main()
