#!/bin/bash
set -u
BASE="/home/aroc/projects/universal_text_translator/_work/milos_srt"
OUT="$BASE/images"; TMP="$BASE/_video_tmp"; mkdir -p "$OUT" "$TMP"
for KEY in "14 - The Book" "15 - The Readings" "16 - The Spoon Bend" \
           "17 - The UV Set" "18 - The Phone Unlock" "19 - The Performances" \
           "The 1089 Force"; do
  DEST=""
  for EXT in m4v mp4; do
    for TRY in 1 2 3; do
      if rclone copy "gdrive:Milos_Zauberschule/${KEY}.${EXT}" "$TMP" \
           --drive-shared-with-me --low-level-retries 10 --retries 3 2>>"$BASE/extract2.err"; then
        [ -f "$TMP/${KEY}.${EXT}" ] && DEST="$TMP/${KEY}.${EXT}" && break 2
      fi
      sleep 20
    done
  done
  [ -z "$DEST" ] && { echo "KEIN VIDEO: $KEY"; continue; }
  grep -P "^\Q$KEY\E\t" "$BASE/_frame_jobs.tsv" | while IFS=$'\t' read -r K N T; do
    ffmpeg -loglevel error -ss "$T" -i "$DEST" -frames:v 1 -vf "scale=1000:-2" \
      -q:v 4 -y "$OUT/${K}_${N}.jpg" </dev/null
  done
  echo "fertig: $KEY ($(ls "$OUT" | grep -c "^${KEY}_") Bilder)"
  rm -f "$DEST"
done
echo "NACHLESE FERTIG: $(ls "$OUT"/*.jpg | wc -l) Bilder"
