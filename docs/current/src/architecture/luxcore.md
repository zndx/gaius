# LuxCore Renderer

LuxCore is the unbiased path tracer used for generating card visualizations. It provides GPU-accelerated rendering with physically accurate spectral glass materials that Blender Cycles could not achieve.

## Installation

**PyPI (CPU-only, production fallback):**

```bash
uv pip install pyluxcore --no-deps
```

The `--no-deps` flag is required to avoid pulling in numpy 2.x, which conflicts with vLLM.

**From source (GPU path):**

The from-source build lives at `thirdparty/src/LuxCore` (git submodule). Build with:

```bash
./build-thirdparty.sh --component luxcore
```

Output: `thirdparty/installed/LuxCore/pyluxcore/pyluxcore.cpython-312-x86_64-linux-gnu.so`

Runtime libraries (OIDN + TBB) are installed to `thirdparty/installed/LuxCore/lib/` with RPATH set to `$ORIGIN/../lib`. CUDA 12.4 at `/usr/local/cuda` is auto-detected during build.

## Render Engines

**PATHOCL** -- GPU-accelerated path tracing on CUDA devices. This is the primary production engine. Hybrid mode automatically uses both GPU intersection and 64 CPU native threads together. The engine name is `PATHOCL`, not `PATHGPU` (which does not exist).

**PATHCPU** -- 64-thread CPU rendering when no CUDA devices are available. Approximately 10x slower than single-GPU PATHOCL for equivalent sample counts.

## Device Selection

CUDA devices are selected via a string of `0` and `1` characters (no spaces), where each position maps to an entry in `pyluxcore.GetOpenCLDeviceList()`:

```python
# Device order: 6 OpenCL (indices 0-5) + 6 CUDA (indices 6-11)
# Physical GPU N = cuda_indices[N]
# Select only GPU 2:
device_string = "000000001000"  # CUDA index 8 = physical GPU 2
```

The `gpu_id` parameter restricts rendering to a single evicted GPU, which is required since all other GPUs are loaded by vLLM.

## Scene Construction

Camera configuration goes in `scene.Parse()`, NOT in the config object. This is a common LuxCore pitfall:

```python
scene.Parse(pyluxcore.Properties()
    .Set(pyluxcore.Property("scene.camera.type", "perspective"))
    .Set(pyluxcore.Property("scene.camera.lookat.orig", [0, -5, 2]))
    .Set(pyluxcore.Property("scene.camera.lookat.target", [0, 0, 0.5]))
    .Set(pyluxcore.Property("scene.camera.fieldofview", 40))
)
```

## Light Types

LuxCore supports: `point`, `spot`, `distant`, `constantinfinite`. There is no `area` light type -- use emissive meshes instead. Light gain values are approximately 100x lower than Blender energy values.

## Film Pipeline

After rendering, the film pipeline must be executed with an explicit pipeline index:

```python
session.GetFilm().ExecuteImagePipeline(0)  # 0 = pipeline index, required
```

## Polling vs Blocking

Never use `WaitForDone()` -- it blocks indefinitely. Use polling with `HasDone()` and `UpdateStats()`:

```python
while not session.HasDone():
    session.UpdateStats()
    stats = session.GetStats()
    elapsed = stats.Get("stats.renderengine.time").GetFloat()
    if elapsed > timeout_seconds:
        break
    time.sleep(0.5)
```

## Initialization

`pyluxcore.Init()` must be called exactly once. The `_ensure_luxcore()` helper handles this, preferring the from-source build over the PyPI wheel:

```python
def _ensure_luxcore():
    """Initialize LuxCore once, preferring from-source build."""
    source_path = Path("thirdparty/installed/LuxCore/pyluxcore")
    if source_path.exists():
        sys.path.insert(0, str(source_path))
    import pyluxcore
    pyluxcore.Init()
```
