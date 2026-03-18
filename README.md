# 🏒 Pro Hockey Veteran Tracker

Automatically tracks ECHL veteran status (260-career-GP threshold) across 10 pro leagues.
Refreshes every Monday morning and is hosted for free on GitHub Pages.

**Live site:** `https://cbattinieri.github.io/vet-tracker/`

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


---



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
