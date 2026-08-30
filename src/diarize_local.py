"""Sprechertrennung für ein bereits transkribiertes Gespräch — komplett lokal.

Für jedes Whisper-Segment wird ein Stimm-Embedding (ECAPA, speechbrain)
berechnet und geclustert. Die Sprecherzahl wird über den Silhouetten-Wert
geschätzt. Ergebnis: segments_diarized.json mit Sprecher-Label je Segment.
"""

import json
import sys
import warnings

import numpy as np
import torch
import torchaudio
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from speechbrain.inference.speaker import EncoderClassifier

warnings.filterwarnings("ignore")

SR = 16000
MIN_LEN = 0.8      # kürzere Segmente liefern keine brauchbare Stimmprobe
MAX_LEN = 8.0      # längere Segmente werden auf die Mitte gekürzt


def embeddings(wav_path, segments, model):
    audio, sr = torchaudio.load(wav_path)
    if sr != SR:
        audio = torchaudio.functional.resample(audio, sr, SR)
    audio = audio.mean(0)
    vecs, usable = [], []
    for i, seg in enumerate(segments):
        start, end = seg["start"], seg["end"]
        if end - start < MIN_LEN:
            continue
        if end - start > MAX_LEN:
            mid = (start + end) / 2
            start, end = mid - MAX_LEN / 2, mid + MAX_LEN / 2
        chunk = audio[int(start * SR):int(end * SR)]
        if chunk.numel() < int(MIN_LEN * SR):
            continue
        with torch.no_grad():
            emb = model.encode_batch(chunk.unsqueeze(0)).squeeze().cpu().numpy()
        vecs.append(emb)
        usable.append(i)
        if len(vecs) % 100 == 0:
            print(f"  {len(vecs)} Stimmproben", flush=True)
    return np.array(vecs), usable


def best_k(vecs, kmin=2, kmax=5):
    """Sprecherzahl über den besten Silhouetten-Wert schätzen."""
    norm = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    best, scores = (kmin, -1), {}
    for k in range(kmin, min(kmax, len(norm) - 1) + 1):
        labels = AgglomerativeClustering(
            n_clusters=k, metric="cosine", linkage="average"
        ).fit_predict(norm)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(norm, labels, metric="cosine")
        scores[k] = round(float(score), 3)
        if score > best[1]:
            best = (k, score)
    print(f"Silhouetten-Werte: {scores} -> {best[0]} Sprecher", flush=True)
    return best[0], norm


def smooth(labels, window=2):
    """Einzelne Ausreißer zwischen gleichen Nachbarn glätten."""
    out = list(labels)
    for i in range(1, len(out) - 1):
        if out[i - 1] == out[i + 1] and out[i] != out[i - 1]:
            out[i] = out[i - 1]
    return out


def main(wav, seg_json, out_json):
    segments = json.load(open(seg_json, encoding="utf-8"))
    print(f"{len(segments)} Segmente geladen", flush=True)
    model = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="/tmp/spkrec-ecapa", run_opts={"device": "cpu"},
    )
    vecs, usable = embeddings(wav, segments, model)
    print(f"{len(vecs)} verwertbare Stimmproben", flush=True)

    k, norm = best_k(vecs)
    labels = smooth(AgglomerativeClustering(
        n_clusters=k, metric="cosine", linkage="average"
    ).fit_predict(norm))

    names = {i: f"SPRECHER {chr(65 + i)}" for i in range(k)}
    by_index = {idx: names[lab] for idx, lab in zip(usable, labels)}

    last = names[0]
    for i, seg in enumerate(segments):
        seg["speaker"] = by_index.get(i, last)   # zu kurze Segmente: Sprecher halten
        last = seg["speaker"]

    json.dump(segments, open(out_json, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    counts = {}
    for seg in segments:
        counts[seg["speaker"]] = counts.get(seg["speaker"], 0) + seg["end"] - seg["start"]
    for name, secs in sorted(counts.items()):
        print(f"{name}: {secs/60:.1f} min Redeanteil")
    print(f"FERTIG -> {out_json}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
