"""runwhere-ai 一体化 Web 控制台。

Built on top of gpuctl (imported as a path dependency). Exposes a single
FastAPI app at `src.main:app` that mounts both gpuctl's existing
/api/v1/* JSON routes and the new HTML / HTMX UI routes in the same process.
"""

__version__ = "0.1.0"
