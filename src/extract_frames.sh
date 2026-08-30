#!/bin/bash
# Lädt jedes Video einzeln, schneidet die geplanten Standbilder heraus, löscht es wieder.
set -u
BASE="/home/aroc/projects/universal_text_translator/_work/milos_srt"
PLAN="$BASE/frames_plan.json"
OUT="$BASE/images"; mkdir -p "$OUT"
TMP="$BASE/_video_tmp"; mkdir -p "$TMP"

python3 - "$PLAN" <<'PY' > "$BASE/_frame_jobs.tsv"
import json,sys
plan=json.load(open(sys.argv[1],encoding='utf-8'))
for key,items in plan.items():
    for n,it in enumerate(items,1):
        print(f"{key}\t{n:02d}\t{it['t']}")
PY

cut -f1 "$BASE/_frame_jobs.tsv" | uniq | while read -r KEY; do
  DEST=""
  for EXT in mp4 m4v; do
    if rclone lsf "gdrive:Milos_Zauberschule/${KEY}.${EXT}" --drive-shared-with-me >/dev/null 2>&1; then
      DEST="$TMP/${KEY}.${EXT}"
      rclone copy "gdrive:Milos_Zauberschule/${KEY}.${EXT}" "$TMP" --drive-shared-with-me 2>/dev/null
      break
    fi
  done
  if [ -z "$DEST" ] || [ ! -f "$DEST" ]; then echo "KEIN VIDEO: $KEY"; continue; fi
  grep -P "^\Q$KEY\E\t" "$BASE/_frame_jobs.tsv" | while IFS=$'\t' read -r K N T; do
    ffmpeg -loglevel error -ss "$T" -i "$DEST" -frames:v 1 \
      -vf "scale=1000:-2" -q:v 4 -y "$OUT/${K}_${N}.jpg" </dev/null
  done
  echo "fertig: $KEY ($(ls "$OUT" | grep -c "^${KEY}_") Bilder)"
  rm -f "$DEST"
done
rmdir "$TMP" 2>/dev/null
echo "ALLE FERTIG: $(ls "$OUT"/*.jpg 2>/dev/null | wc -l) Bilder"
