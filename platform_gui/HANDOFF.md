# Platform changes: handoff for Gigi

Branch `platform-gui`, cut from `fleet-composition-v3.1-gigi` at `b81370a`
(your "Add local GUI and FSA post-processing tools" commit). The Pipeline tab
you built is unchanged in behaviour. This branch adds four tabs on top of it
and moves the page out of `app.py`.

## Read this first: `app.py` no longer holds the HTML

`INDEX_HTML` is now `platform_gui/static/index.html`. If you have local edits
to the HTML or JS inside `app.py`, they will conflict. Re-apply them in
`static/index.html` instead. Extra scripts and styles are in
`static/whatif.js` and `static/whatif.css`.

## What changed

| Area | Change |
| --- | --- |
| Pipeline tab | Progress bar with real step names and elapsed seconds. Output Files panel is now a stacked, clickable list. CO2 results use the emission events for the selected year and scenario, falling back to the configured file. Assign lists FSAs that had no composition row (they silently used another FSA's shares before). New config key `fsa_projected_pop_dir`. |
| Explore tab | Map of any indicator per scenario on a shared colour scale, change vs 2020, Table 5 style summary, adoption vs baseline-emissions scatter, concentration curve, FSA card, CSV download. |
| What-if tab | EV adoption factor slider, per-FSA override, boost top emitting FSAs, choice of what the extra EVs replace. Results update live (about 20 ms). |
| Policy tab | Equal-effort experiment: N extra EVs, four allocation rules, replaced-vehicle filter, within-FSA bounds, gain vs uniform effort. |
| Priorities tab | Re-draws vehicle assignments and reports how often each FSA is in the top-k. Candidate levers per FSA are my own heuristic rules, not from the paper. |
| Backend | `platform_gui/whatif.py` (engine), `platform_gui/indicators.py` (paper indicators), new `/api/whatif/*` endpoints, `/api/progress`, `/static/*`. |
| Tests | `tests/test_platform.py`, 12 tests. |

## How the what-if engine works

It builds an agent table once (home FSA, simulated km per day, EV kWh/km) and
cached in `<results_dir>/whatif_agent_table.npz`. Any fleet composition is then
a lookup and a sum, because travel demand is fixed and emission factors are
averages. Vehicle draws copy `core.assign_vehicle_types` (same seed, same
population order), and a test checks they pick the same types.

Per-category CO2 g/km are regressed from every scenario that has emission
events, and each FSA gets a scale factor. The result matches those runs within
1 to 4% on total CO2 with the mock data. The Explore tab shows the error.

## What you need to do

1. **Install and run**
   ```bash
   python3 -m pip install numpy pandas pyarrow pillow
   python3 -m unittest discover -s tests
   python3 scripts/run_platform_gui.py
   ```
   Python 3.9 was used. `numpy` is now required for the four new tabs.
2. **Get data.** Not in git. Either the real files listed in the repository
   README and `default_config.json`, or the mock folder `demo_data/` from
   Jonatas. Copy it into the repo root and it stays local (it is excluded in
   `.git/info/exclude`). **`demo_data/paper_results/` holds unpublished
   results: share it privately, never commit it.** Mock inputs make FSA totals
   follow the paper, but every per-agent value is invented, and the page shows
   a banner while `mock_data` is true in `platform_gui/config.json`.
3. **Check the first load.** Open the Explore tab. It builds the agent table
   (a few seconds on mock data, longer on real events) and the map polygons.
   Read the "About these numbers" box for the calibration error.
4. **With real data**, the item that matters most is the emission runs: the
   what-if is only as good as the g/km per category. Ask Qi for the five
   emission runs (one per vehicle category) or the agent table described in
   `revision-plan.md` section 7, then check the calibration error again.

## Known gaps

- Numbers from the Policy and Priorities tabs on mock data are not results.
  The paper's `[X]%` needs the real agent table.
- Not built: run manifest (scenario and vehicle file still picked separately in
  Pipeline), Gompertz vs recalibrated BAU switch, LISA clusters, census join
  for the equity check, cost per tonne, SVG export.
- Density uses shapefile land area, about 5% below the paper's geometry area.
- Run Emission Module still needs Maven and the `matsim-emissions` checkout.
- The 15 sample agents with no home FSA still get an assigned vehicle (G0A's
  shares). The paper excludes them. Assign now warns about it.

## Files to look at

- `platform_gui/whatif.py`: engine, allocation, stability.
- `platform_gui/indicators.py`: kappa, density, load, concentration, Pearson.
- `platform_gui/static/whatif.js`: the four views.
- `platform_gui/core.py`, `app.py`: progress reporting, endpoints, assign warning.
