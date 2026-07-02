# IOT Mapping

Interactive map that visualises IoT sensor radio paths (sensor → repeater → gateway) for a water monitoring network. Devices are plotted on a Leaflet map with colour-coded markers, searchable labels, and real-time offline status from ThingsBoard.

The map is regenerated every 15 minutes via GitHub Actions and deployed to GitHub Pages.

## Project Structure

```
src/iot_mapping/       Python package
  cli.py               Entry point and argument parsing
  config.py            Shared constants (URLs, timezone, defaults)
  data_loader.py       Load devices, labels, and path log files
  data_processing.py   Build network edges and merge coordinates
  encryption.py        XOR obfuscation for client-side data protection
  map_builder.py       Folium map generation with injected frontend
  scraper.py           Selenium scraper for ThingsBoard offline status
templates/             Frontend files injected into the generated HTML
  styles.css           Map UI styles
  map_shell.html       Login modal, search box, offline panel, legend
  map_app.js           Client-side auth, decryption, search, rendering
```

## Local Development

**Prerequisites:** Python 3.11+, Google Chrome (for offline node scraping)

```bash
python -m venv venv
venv\Scripts\activate        # or source venv/bin/activate on linux
pip install -r requirements.txt
```

**Generate the map:**

```bash
PYTHONPATH=src python -m iot_mapping \
  --paths paths.csv \
  --devices devices.csv \
  --labels labels.csv \
  --out output/routes_map.html \
  --password "your-password"
```

On Windows (PowerShell):

```powershell
$env:PYTHONPATH = "src"
python -m iot_mapping `
  --paths paths.csv `
  --devices devices.csv `
  --labels labels.csv `
  --out output/routes_map.html `
  --password "your-password"
```

Add `--skip-offline` to skip the ThingsBoard scraper (useful for local testing without Chrome).

## CI/CD

A GitHub Actions workflow (`.github/workflows/build-map.yml`) runs every 15 minutes:

1. Downloads CSV data from a private repo using `DATA_REPO_PAT`
2. Scrapes ThingsBoard for offline node status
3. Generates `routes_map.html` with encrypted data
4. Deploys to the `gh-pages` branch via GitHub Pages

**Required secrets:** `DATA_REPO_PAT`, `MAP_PASSWORD`

**Setup:** In repo Settings → Pages, set source to "Deploy from a branch" → `gh-pages` / `/ (root)`.

## Input Data Formats

**paths.csv** — hop sequences (CSV or TSV):
```
count, date, time_with_GMT, node, hop1, hop2, hop3, hop4, hop5, hop6
```

**devices.csv** — device coordinates (CSV or XLSX):
```
ID, Latitude, Longitude, Type
```

**labels.csv** — friendly names (optional):
```
ID, DeviceName, Location
```
