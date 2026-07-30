#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${FIXTURE_VIDEOS_DIR:-$repo_root/tests/fixtures/videos}"
mkdir -p "$dest"

download() {
  local url="$1"
  local out="$2"
  if [[ -f "$out" && -s "$out" ]]; then
    printf 'OK exists: %s (%s bytes)\n' "$out" "$(wc -c <"$out")"
    return 0
  fi
  printf 'Downloading %s\n' "$url"
  curl -fL --retry 3 --retry-delay 2 -o "$out.partial" "$url"
  mv "$out.partial" "$out"
  printf 'Saved %s (%s bytes)\n' "$out" "$(wc -c <"$out")"
}

# Regression / multi-scene (Intel IoT)
download \
  "https://github.com/intel-iot-devkit/sample-videos/raw/master/car-detection.mp4" \
  "$dest/car-detection.mp4"
download \
  "https://github.com/intel-iot-devkit/sample-videos/raw/master/person-bicycle-car-detection.mp4" \
  "$dest/person-bicycle-car-detection.mp4"

# Parking lot: multiple vehicles + readable plates
download \
  "https://github.com/open-edge-platform/edge-ai-resources/raw/main/videos/ParkingVideo.mp4" \
  "$dest/parking-plates.mp4"

# Dense traffic / more vehicles (spaces in upstream name)
download \
  "https://github.com/anmspro/Traffic-Signal-Violation-Detection-System/raw/master/Resources/Traffic%20IP%20Camera%20video.mp4" \
  "$dest/traffic-plates.mp4"

# Busy multi-lane highway from fixed / tripod-style surveillance camera
download \
  "https://github.com/maxzhy/yolov5-deepsort-traffic-incident-detection/raw/main/highway-video.mp4" \
  "$dest/highway-tripod.mp4"

# Highway split/merge fixed camera (lighter alternate)
download \
  "https://github.com/M4D-AI/Highway-Incident-Detection/raw/main/data/parking.mp4" \
  "$dest/highway-split.mp4"

printf '\nFixtures in %s:\n' "$dest"
find "$dest" -maxdepth 1 -type f \( -name '*.mp4' -o -name '*.avi' \) -printf '%f\t%s\n' | sort
