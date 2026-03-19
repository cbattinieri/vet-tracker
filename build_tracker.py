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
    df_sorted = df.sort_values("season", ascending=False)

    vet_df = df_sorted.groupby(["player", "position", "link"]).agg(
        total_gp        =("gp",              "sum"),
        total_g         =("g",               "sum"),
        total_a         =("a",               "sum"),
        total_tp        =("tp",              "sum"),
        total_pim       =("pim",             "sum"),
        total_pm        =("+/-",             "sum"),
        legacy_veteran  =("legacy_veteran",  "first"),
        new_veteran     =("new_veteran",     "first"),
        league          =("league",          "first"),
    ).reset_index()

    vet_df["total_ppg"] = (
        vet_df["total_tp"] / vet_df["total_gp"].replace(0, 1)
    ).round(2)

    # Active = played at least 1 GP in current season
    cur_gp = df[df["season"] == current_season].groupby("link")["gp"].sum()
    vet_df["active"] = vet_df["link"].map(cur_gp).fillna(0) > 0

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
        "legacy_veteran", "new_veteran", "non_vet_ufa", "league", "active",
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
  .header-text h1 {{ font-family:'Barlow Condensed',sans-serif;font-size:28px;font-weight:800;letter-spacing:1px;text-transform:uppercase; }}
  .header-text p {{ font-size:13px;color:var(--text-muted);margin-top:2px; }}
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
  .sn-hi {{ color:var(--text);font-weight:600; }} .sn-ppg {{ color:var(--gold); }}
  .no-results {{ text-align:center;padding:60px 20px;color:var(--text-muted);font-size:16px; }}
  .no-results .ico {{ font-size:48px;margin-bottom:12px; }}
</style>
</head>
<body>

<div class="header">
  <div class="header-icon">🏒</div>
  <div class="header-text">
    <h1>Pro Hockey Veteran Tracker</h1>
    <p>ECHL veteran status · 260 career GP threshold across 10 pro leagues</p>
  </div>
  <div class="header-meta">
    <div class="header-season">{season} SEASON</div>
    <div class="header-updated">Updated {updated}</div>
  </div>
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
    <select id="fv">
      <option value="">All Players</option>
      <option value="legacy">⭐ Legacy Veterans</option>
      <option value="new">🆕 New Veterans</option>
      <option value="any">Any Veteran</option>
      <option value="ufa">🟠 Non-Vet UFA (190–259 GP)</option>
      <option value="none">Under Threshold (&lt;190 GP)</option>
    </select>
  </div>
  <div class="control-group">
    <label>League</label>
    <select id="fl">
      <option value="">All Leagues</option>
      <option value="nhl">NHL</option><option value="ahl">AHL</option>
      <option value="echl">ECHL</option><option value="khl">KHL</option>
      <option value="shl">SHL</option><option value="liiga">Liiga</option>
      <option value="czechia">Czechia</option><option value="slovakia">Slovakia</option>
      <option value="del">DEL</option><option value="nl">NL</option>
    </select>
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

<div class="table-wrap">
  <table>
    <thead><tr>
      <th onclick="sort('player')" data-c="player">Player <span class="arr">↕</span></th>
      <th onclick="sort('position')" data-c="position">Pos <span class="arr">↕</span></th>
      <th onclick="sort('league')" data-c="league">League <span class="arr">↕</span></th>
      <th onclick="sort('total_gp')" data-c="total_gp">GP <span class="arr">↕</span></th>
      <th onclick="sort('total_g')" data-c="total_g">G <span class="arr">↕</span></th>
      <th onclick="sort('total_a')" data-c="total_a">A <span class="arr">↕</span></th>
      <th onclick="sort('total_tp')" data-c="total_tp">PTS <span class="arr">↕</span></th>
      <th onclick="sort('total_ppg')" data-c="total_ppg">PPG <span class="arr">↕</span></th>
      <th onclick="sort('total_pim')" data-c="total_pim">PIM <span class="arr">↕</span></th>
      <th onclick="sort('legacy_veteran')" data-c="legacy_veteran">Vet Status <span class="arr">↕</span></th>
      <th onclick="sort('active')" data-c="active">Active <span class="arr">↕</span></th>
    </tr></thead>
    <tbody id="tb"></tbody>
  </table>
  <div id="nr" class="no-results" style="display:none"><div class="ico">🔍</div>No players match your filters.</div>
</div>

<script>
const D={json_data};
const LG={{'nhl':'NHL','ahl':'AHL','echl':'ECHL','khl':'KHL','shl':'SHL','liiga':'Liiga','czechia':'Czechia','slovakia':'Slovakia','del':'DEL','nl':'NL'}};
let sc='total_gp',sa=false,filtered=[],shown=200;
function isF(p){{if(!p)return false;const u=p.toUpperCase();return /\\b(F|C|LW|RW|W)\\b/.test(u)&&!/\\bD\\b/.test(u.replace(/D\\/F/,''));}}
function isD(p){{return p&&/\\bD\\b/.test(p.toUpperCase());}}
function vs(r){{return r.legacy_veteran?'legacy':r.new_veteran?'new':r.non_vet_ufa?'ufa':'none';}}
function applyFilters(){{
  const s=document.getElementById('search').value.trim().toLowerCase();
  const fv=document.getElementById('fv').value;
  const fl=document.getElementById('fl').value;
  const fp=document.getElementById('fp').value;
  const fa=document.getElementById('fa').value;
  filtered=D.filter(r=>{{
    if(s&&!r.player.toLowerCase().includes(s))return false;
    const v=vs(r);
    if(fv==='legacy'&&v!=='legacy')return false;
    if(fv==='new'&&v!=='new')return false;
    if(fv==='any'&&v!=='legacy'&&v!=='new')return false;
    if(fv==='ufa'&&v!=='ufa')return false;
    if(fv==='none'&&v!=='none')return false;
    if(fl&&r.league!==fl)return false;
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
  document.querySelectorAll('th').forEach(t=>{{t.classList.remove('sorted');t.querySelector('.arr').textContent='↕';}});
  const th=document.querySelector(`th[data-c="${{col}}"]`);
  if(th){{th.classList.add('sorted');th.querySelector('.arr').textContent=sa?'↑':'↓';}}
  sortArr();render();
}}
function lgB(lg){{return `<span class="lg lg-${{lg}}">${{LG[lg]||lg.toUpperCase()}}</span>`;}}
function vetB(r){{
  const v=vs(r);
  if(v==='legacy')return'<span class="vb vb-legacy">⭐ Veteran</span>';
  if(v==='new')return'<span class="vb vb-new">🆕 New Vet</span>';
  if(v==='ufa')return`<span class="vb vb-ufa">🟠 Non-Vet UFA</span>`;
  return`<span class="vb vb-none">${{r.total_gp}}/260</span>`;
}}
function gpB(gp){{
  const p=Math.min(100,Math.round(gp/260*100));
  const c=gp>=260?'fill-gold':gp>=200?'fill-grn':'fill-mut';
  return`<div class="gp-wrap"><span class="sn sn-hi">${{gp}}</span><div class="gp-bg"><div class="gp-fill ${{c}}" style="width:${{p}}%"></div></div></div>`;
}}
function render(){{
  const tb=document.getElementById('tb');
  const nr=document.getElementById('nr');
  document.getElementById('rc').textContent=filtered.length.toLocaleString();
  if(!filtered.length){{tb.innerHTML='';nr.style.display='block';return;}}
  nr.style.display='none';
  const rows=filtered.slice(0,shown).map(r=>`<tr>
    <td class="player-name"><a href="${{r.link}}" target="_blank" rel="noopener">${{r.player}}</a></td>
    <td><span class="pos-badge">${{r.position||'—'}}</span></td>
    <td>${{lgB(r.league)}}</td>
    <td>${{gpB(r.total_gp)}}</td>
    <td class="sn">${{r.total_g}}</td>
    <td class="sn">${{r.total_a}}</td>
    <td class="sn sn-hi">${{r.total_tp}}</td>
    <td class="sn ${{r.total_ppg>=0.75?'sn-ppg':''}}">${{r.total_ppg.toFixed(2)}}</td>
    <td class="sn">${{r.total_pim}}</td>
    <td>${{vetB(r)}}</td>
    <td><span class="dot ${{r.active?'dot-on':'dot-off'}}"></span>${{r.active?'Active':'<span style="color:var(--text-muted)">Inactive</span>'}}</td>
  </tr>`).join('');
  tb.innerHTML=rows;
  if(filtered.length>shown){{
    const rem=filtered.length-shown;
    const tr=document.createElement('tr');
    tr.innerHTML=`<td colspan="11" style="text-align:center;padding:16px">
      <button onclick="loadMore()" style="background:var(--surface2);border:1px solid var(--border);color:var(--text);font-family:Barlow,sans-serif;font-size:13px;padding:8px 24px;border-radius:6px;cursor:pointer">
        Load ${{Math.min(rem,200)}} more (${{rem}} remaining)
      </button></td>`;
    tb.appendChild(tr);
  }}
}}
function loadMore(){{shown+=200;render();}}
function reset(){{
  ['search','fv','fl','fp','fa'].forEach(id=>{{const e=document.getElementById(id);e.tagName==='INPUT'?e.value='':e.value='';if(e.tagName==='SELECT')e.selectedIndex=0;}});
  document.getElementById('fv').value='any';
  applyFilters();
}}
['search'].forEach(id=>document.getElementById(id).addEventListener('input',applyFilters));
['fv','fl','fp','fa'].forEach(id=>document.getElementById(id).addEventListener('change',applyFilters));
// Boot: default to all veterans, sorted by GP desc
document.getElementById('fv').value='any';
applyFilters();
</script>
</body>
</html>"""


def build_html(vet_df: pd.DataFrame, current_season: str) -> str:
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

    html = HTML_TEMPLATE.format(
        json_data  = json.dumps(records, separators=(",", ":")),
        season     = season_label,
        updated    = updated,
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

    # 2. Scrape current season
    print(f"Scraping {current_season} from EliteProspects...")
    current_stats = tdhepscrape.get_skaters(LEAGUES, current_season)
    print(f"  Scraped {len(current_stats):,} rows\n")

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
    print(f"  Active this season:   {vet_df['active'].sum():,}\n")

    # 6. Write HTML to docs/index.html (served by GitHub Pages)
    html = build_html(vet_df, current_season)
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
