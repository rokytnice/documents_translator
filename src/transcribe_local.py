"""Lokale Transkription mit faster-whisper (kein Upload, kein Cloud-Dienst)."""
import json, sys, time
from faster_whisper import WhisperModel

wav, out_json, model_name = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "large-v3")
t0 = time.time()
model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=18)
print(f"Modell {model_name} geladen ({time.time()-t0:.0f}s)", flush=True)

segments, info = model.transcribe(
    wav, language="de", beam_size=5, vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
    condition_on_previous_text=True,
)
print(f"Sprache={info.language} Dauer={info.duration:.0f}s", flush=True)

data = []
for seg in segments:
    data.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
    if len(data) % 25 == 0:
        pct = seg.end / info.duration * 100
        print(f"  {seg.end/60:5.1f} min ({pct:4.1f}%) — {len(data)} Segmente, "
              f"{(time.time()-t0)/60:.1f} min gelaufen", flush=True)
json.dump(data, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"FERTIG: {len(data)} Segmente -> {out_json} in {(time.time()-t0)/60:.1f} min", flush=True)
