# Bike-Share Siting Toolkit

**Where should a city put its next bike-share stations?** This toolkit scores a city on a hexagon grid using open data (census population, OpenStreetMap streets, services, bus stops and cycleways, and terrain), then proposes new station sites in phases using siting rules drawn from operating a real docked system.

It grew out of a practical question from a transportation researcher studying bike-share expansion in Maricá, Brazil: *how should a city weigh gaps in station coverage against connections to public transport?* I answered with lessons from Bublr Bikes in Milwaukee, where I work, and then tested the same rules on Maricá.

**Live pages**

* Coverage or transit? Lessons from Milwaukee: `https://PrasanthYenuganti.github.io/bikeshare-siting-toolkit/milwaukee.html`
* Maricá bike-share expansion plan: `https://PrasanthYenuganti.github.io/bikeshare-siting-toolkit/marica.html`

\---

## Key findings

**Milwaukee (Bublr Bikes, 173 stations)**

* Coverage and transit work at two scales. Station density decides which neighbourhoods get stations and how close together they are; transit decides which corner the station stands on.
* 86% of stations are within 200 m of a bus stop (60% within 100 m).
* About 27% of residents in the four served municipalities live within 500 m of a station. Coverage by income is U-shaped: the lowest- and highest-income fifths are best served.
* Unlike Maricá, Milwaukee's lower-income neighbourhoods have *more* bus stops, not fewer (Spearman ρ = 0.26 between income disadvantage and bus stops).

**Maricá (Vermelhinhas, fare-free system)**

||Today|With the 52-station plan|
|-|-|-|
|Residents within 300 m of a station|17.0%|31.9%|
|Residents within 500 m of a station|33.8%|63.4%|

|District|Residents (Census 2022)|New stations|Within 500 m today|Within 500 m with plan|
|-|-|-|-|-|
|Maricá (Sede)|79,176|14|55.6%|74.3%|
|Itaipuaçu|59,470|18|23.1%|56.9%|
|Inoã|35,709|12|16.9%|60.1%|
|Ponta Negra|22,922|8|13.0%|47.5%|

Phase 1 (12 stations) brings about 29,000 more residents within 500 m. Three alternative strategies for 20 stations are compared in `outputs/marica/summary.json`: densify the core, transit first and coverage first.

\---

## How it works

1. **`src/fetch\_data.py`** downloads the city boundary, OpenStreetMap features (Overpass API) and existing stations (GBFS feed or a CSV).
2. **`src/build\_grid.py`** builds a hexagon grid (250 m radius by default) and measures each criterion per hexagon: population (census totals spread by buildings and streets), services and shops within 600 m, bus stops within 400 m, distance to main roads, cycleways and existing stations, and terrain slope (Open-Meteo elevation).
3. **`src/score\_sites.py`** ranks every criterion 0–1, combines them with weights, applies a terrain factor and then picks sites greedily under siting rules:

   * minimum spacing between new stations (450 m) and from existing ones (350 m)
   * no isolated stations: each new site must be within a set distance of the network
   * optional fair shares of new stations by district
4. **`src/ahp.py`** turns pairwise judgments (Analytic Hierarchy Process, Saaty 1–9 scale) into weights and reports the consistency ratio.

|Criterion|Measured as|Weight|
|-|-|-|
|Population density|Residents within 600 m|22.2%|
|Access to services|Schools, health, banks, markets within 600 m|22.2%|
|Bus integration|Bus stops within 400 m, plus a main road within 150 m|22.2%|
|Jobs and commerce|Shops within 600 m|11.1%|
|Coverage gap|Distance to the nearest existing station (stands in for income)|11.1%|
|Cycling infrastructure|Distance to a cycleway|11.1%|

\---

## Run it yourself

Requires Python 3.9 or newer.

```bash
pip install -r requirements.txt
python tests/test\_pipeline.py          # offline check, no internet needed
python src/ahp.py config/marica.json   # weights and consistency ratio
python src/fetch\_data.py config/marica.json
python src/build\_grid.py config/marica.json
python src/score\_sites.py config/marica.json
```

Results are written to `outputs/<city>/proposed\_sites.csv` (open in Excel or QGIS) and `outputs/<city>/summary.json`. Rerunning with newer OpenStreetMap data can shift the numbers slightly.

**Add a city:** copy `config/marica.json`, change `name`, `bbox` (south, west, north, east), `boundary\_url` (any GeoJSON), the population totals, and either set `gbfs\_station\_information` to the system's GBFS feed or put a `stations.csv` (columns `lat`, `lon`) in `data/<city>/`.

\---

## Limitations

* Population inside each district is spread by mapped buildings and residential streets, so poorly mapped areas are under-counted.
* OpenStreetMap lists far fewer bus stops in Maricá than the operator's network; the transit criterion is conservative. An operator GTFS feed would improve it.
* Small-area income was not available, so distance to existing stations stands in for the income criterion.
* Maricá's existing station positions were digitised from a study map (about ±110 m).
* Proposed sites are 250 m hexagons for field review, not final addresses.

\---

## How this was made

I designed the analysis, checked the results against operating data and wrote the conclusions. I used Claude (Anthropic) as an assistant for code, open-data retrieval and first drafts.

## Data sources and licences

* OpenStreetMap contributors, via the Overpass API (ODbL 1.0)
* IBGE Census 2022, table 9923, and municipal boundaries
* US Census Bureau: TIGERweb and American Community Survey 5-year estimates
* Open-Meteo elevation API (Copernicus DEM)
* Bublr Bikes public GBFS station feed
* NACTO, *Densifying docked bike share in Milwaukee* (2026)

Code is released under the MIT licence (`LICENSE`). Data derived from OpenStreetMap is under the ODbL (`NOTICE.md`).

## Citation

See `CITATION.cff`, or cite as: Yenuganti, P. (2026). *Bike-Share Siting Toolkit* \[Software]. GitHub.

## Acknowledgements

Thanks to my colleagues at Bublr Bikes, and to the researcher whose question started this work.

