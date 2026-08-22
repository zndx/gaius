# optillm sentinel + provided vLLM

`gaius-optillm` is a compute Application (gunicorn, 0 extra GPU).
It binds any healthy generate vLLM already provided (prefer
thinking). Only if none is healthy does it demand thinking via
`ensure_endpoint` (zndx.engine.v1 admit + start). Foreign `:8000`
masters are reaped so the sentinel owns the process 1:1.
