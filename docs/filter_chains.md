# Filter Chains

This tool loads filter chains from a YAML file passed via `--config`.

- `--config` must point to an existing `.yaml` file.
- New sessions auto-create four ablation presets in `<session>/config/filters/`:
  - `hot_only.yaml`
  - `ba_only.yaml`
  - `hot_then_ba.yaml`
  - `ba_then_hot.yaml`
- The baseline branch is `unfiltered/` and does not require a YAML file.

Example:

```bash
./sert filter <session>/scenes/<scene> --config <session>/config/filters/hot_then_ba.yaml
```

Filtering resolves the capture group root to its `unfiltered/` branch and creates a sibling branch named `filtered_<config_stem>/`.

## YAML shape

`chain` is required and order is applied as written.

For the `background_activity` filter, a larger `time_window_us` is more permissive (keeps more events).

Settings:
- `chain`: only the ordered filter steps
- `hot_pixel`, `roi`, `polarity`: settings outside `chain`

```yaml
chain:
  - type: hot_pixel
  - type: background_activity
    time_window_us: 3000

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
```

## Available `chain` filter types

- `background_activity` (requires `time_window_us`)
- `fast_decay` (requires `time_window_us`)
- `k_noise` (requires `time_window_us`)
- `hot_pixel`
- `roi`
- `polarity`

## Optional top-level options (not nested in `chain`)

- `hot_pixel`:
  - `auto_detect` (bool)
  - `n_std_dev` (float)
  - `n_hot_pixels` (int)
    - `-1`: auto detect mode (uses `n_std_dev`)
    - `N >= 0`: top-N mode (marks the `N` most active pixels as hot pixels)
- `roi`: `[x, y, width, height]` (required if `roi` is in chain)
- `polarity`: `on | off | both` (required if `polarity` is in chain)

Notes:

- `hot_pixel` mask detection runs as a pre-pass, but the hot-pixel mask filter is inserted at the `hot_pixel` position in the chain.
- Filtering currently only derives from the `unfiltered/` branch.
- Output is written to a sibling branch: `<capture>/filtered_<config_stem>/`.
- Each branch keeps its own `raw/`, `intermediate/`, `frames/`, and scene `reconstruction/` outputs.
