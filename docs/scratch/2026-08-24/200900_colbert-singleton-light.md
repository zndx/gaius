# ColBERT load-per-window was the Aperture anti-pattern

Every MaxSim window constructed a new `ColBERTZeroEmbedder`. Placement
then saw GPU 4 filling and hopped to GPU 5. Two light copies filled the
box; synthesis failed `#YK.00000008.GPUCOLLIDE`. Thinking's cards went
idle. That is not starve, and skipping MaxSim would hide it.

Fix: one process-wide embedder on the pinned light GPU. Aperture still
runs (off the asyncio loop). `CltSkosAdmitFlow` remains the Metaflow
with `gpu_tokens=1`.
