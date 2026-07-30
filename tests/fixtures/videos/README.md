# Fixture videos for visual pipeline demos

Sources (downloaded locally, not committed as binaries if ignored):

- `car-detection.mp4` — Intel IoT sample, ~30s, cars on road
- `person-bicycle-car-detection.mp4` — Intel IoT sample, mixed traffic
- `generic-sample.mp4` — short generic sample clip

Run:

```bash
./scripts/run_demo.sh
# or
./scripts/run_demo.sh .runtime/demo-results
```

Outputs per video in the chosen directory:

- `*.annotated.mp4` — boxes, track ids, counting line, HUD
- `*.progress.gif` — intermediate low-FPS GIF of the same work
- `*.compressed.mp4` — compressed derivative
- `*.result.json` — immutable result manifest
