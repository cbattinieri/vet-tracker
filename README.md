# 🏒 Pro Hockey Veteran Tracker

Automatically tracks ECHL veteran status (260-career-GP threshold) across 10 pro leagues.
Refreshes every Monday morning and is hosted for free on GitHub Pages.

**Live site:** `https://<your-org>.github.io/vet-tracker/`

---

## How it works

```
Every Monday @ 9 AM ET
        │
        ▼
GitHub Actions runner (free cloud computer)
        │
        ├─ Reads historical career CSVs from data/
        ├─ Scrapes current-season stats from EliteProspects
        ├─ Calculates veteran status for every player
        └─ Writes docs/index.html  ──►  GitHub Pages serves it publicly
```

No server to maintain. No costs. Fully automatic.

---

## One-time setup (≈ 15 minutes)

### Step 1 — Create the GitHub repository

1. Go to [github.com](https://github.com) and sign in (create a free account if needed).
2. Click **+** → **New repository**.
3. Name it `vet-tracker`, set it to **Private** (or Public — your choice), click **Create**.

### Step 2 — Upload the files

Upload everything from this folder into the new repository:

```
vet-tracker/
├── .github/
│   └── workflows/
│       └── weekly_update.yml   ← the automation schedule
├── data/
│   ├── nhl_career_1516_2425.csv
│   ├── ahl_career_1516_2425.csv
│   ├── echl_career_1516_2425.csv
│   ├── khl_career_1516_2425.csv
│   ├── shl_career_1516_2425.csv
│   ├── liiga_career_1516_2425.csv
│   ├── czechia_career_1516_2425.csv
│   ├── slovakia_career_1516_2425.csv
│   ├── del_career_1516_2425.csv
│   └── nl_career_1516_2425.csv
├── docs/
│   └── index.html              ← the web app (auto-generated)
├── build_tracker.py
├── requirements.txt
├── .gitignore
└── README.md
```

The easiest upload method:
- On your repo page click **uploading an existing file**
- Drag and drop all files, preserving the folder structure
- Click **Commit changes**

### Step 3 — Enable GitHub Pages

1. In your repo, go to **Settings** → **Pages** (left sidebar).
2. Under **Source**, select **Deploy from a branch**.
3. Set branch to `main` and folder to `/docs`.
4. Click **Save**.

After a minute you'll see: *"Your site is live at https://\<your-org\>.github.io/vet-tracker/"*

### Step 4 — Run it once manually to generate the first page

1. Go to the **Actions** tab in your repo.
2. Click **Weekly Veteran Tracker Update** in the left panel.
3. Click **Run workflow** → **Run workflow**.
4. Watch it run (takes 2–5 minutes). When it shows a green ✅ the site is updated.

After this, it runs automatically every Monday at 9 AM ET — no action needed.

---

## Updating the historical CSVs each summer

At the end of each season, add the new season's data to the CSVs in `data/` and upload
the updated files to the repo. The script will automatically detect the new current season.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Action fails with a red ✗ | Click the failed run → expand the failing step to read the error |
| Site not updating | Check Actions tab — the job may have been skipped if nothing changed |
| Player missing | They may not be in EliteProspects or played in a league not tracked |

For any issues, contact the person who set this up or open a GitHub Issue on this repo.
