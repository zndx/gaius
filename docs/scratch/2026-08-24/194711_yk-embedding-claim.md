# Embedding is a 1-GPU YK claim, not scraps after thinking

GPU tokens are Applications YK admits or preempts. Tinybox has six
tokens. Heavy (thinking, 4), embedding (ColBERT/Aperture, 1), extract
and light (1 each) compete. Nothing is leftover.

Aperture loading ColBERT on `cuda:0` while thinking's HEAVY process
already occupied that card was a host CUDA steal. YK never saw an
embedding Application, so it could not place or preempt. That OOM is
`#YK.00000008.GPUCOLLIDE`, not starve.

Admit `gaius-embedding` on `root.internal.inference.embedding`. Map
host CUDA onto a device no other admitted WRK occupies. If every card
is held, Yield/preempt the occupant — do not scavenge.
