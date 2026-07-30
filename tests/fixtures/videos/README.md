# Fixture videos for visual pipeline demos

Downloaded locally (binaries gitignored). Refresh with:

```bash
./scripts/download_fixture_videos.sh
```

| File | Source | Purpose |
|------|--------|---------|
| `car-detection.mp4` | Intel IoT sample-videos | Single/few cars, line-crossing smoke |
| `person-bicycle-car-detection.mp4` | Intel IoT sample-videos | Mixed traffic |
| `parking-plates.mp4` | open-edge-platform ParkingVideo | Multi-car parking + readable plates |
| `traffic-plates.mp4` | anmspro Traffic IP Camera | Dense traffic / more vehicles |
| `highway-tripod.mp4` | maxzhy highway-video | Busy multi-lane highway, fixed/tripod cam |
| `highway-split.mp4` | M4D-AI Highway-Incident-Detection | Highway split/merge fixed camera |
| `generic-sample.mp4` | optional legacy short clip | Keep if present; not required |

Run demos:

```bash
./scripts/run_demo.sh
# outputs under .runtime/demo-results-paddle/ for paddle backend
```

Per-video artifacts: `*.annotated.mp4`, `*.progress.gif`, `*.compressed.mp4`, `*.result.json`.

Notes:

- Vehicle attributes from `vehicle_attribute_model` are VeRi **color/body-style** (sedan/suv/…), not light/medium/heavy size taxonomy.
- Plate OCR uses downloaded latin/chinese baseline + local lookalike map; `production_russian_ocr: false`.
