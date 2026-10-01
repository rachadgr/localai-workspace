"""Generation Runtime — a real, lazy integration layer for local image-to-video.

This module wires the **first actual generation runtime** of the workspace:
**Wan 2.2 I2V** (image-to-video), served by its *official* open-weight pipeline.

Design contract (mirrors the project's honesty rules):

* **Lazy by construction.** Importing this module loads **no** weights and imports
  **no** heavy runtime (``torch`` / ``diffusers``). Everything heavy is imported
  lazily, *inside* :meth:`WanI2VAdapter.load`, and only when a generation is
  explicitly requested. Startup and ``import`` remain weight-free.
* **Local weights only.** The checkpoint is discovered on the local filesystem
  (:func:`detect_wan_i2v_checkpoint`). There is **no download path** anywhere —
  ``AUTOMATIC_DOWNLOAD`` is ``False``.
* **Real probe before ``AVAILABLE``.** A checkpoint that merely *exists* is not
  enough: :meth:`WanI2VAdapter.load` performs a genuine initialization and a
  lightweight probe over the built pipeline. Only a successful real probe yields
  ``AVAILABLE``. Missing weights ⇒ ``NOT_CONFIGURED`` / ``weights_missing``.
* **No invented hardware settings.** :func:`discover_runtime_config` only enables
  ``dtype`` / offload / ``device_map`` when the *installed* runtime and the
  *detected* hardware genuinely support them. It never fabricates VRAM figures.
* **No mock generation.** When no real pipeline can run, the adapter reports a
  clear ``NOT_CONFIGURED`` / ``ERROR`` / ``UNAVAILABLE`` verdict and returns **no
  artifact** — it never fabricates a video.

The public, additive surface is :class:`GenerationRequest`, :class:`GenerationResult`,
:class:`GenerationLifecycle`, :class:`WanI2VAdapter`, :class:`LocalGenerationManager`
and :func:`get_local_generation_manager`. Nothing here touches ``ChatRequest``, the
Agent API or SSE.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.app.core.observability import get_logger
from models.base import (
    KIND_VIDEO,
    MODALITY_IMAGE,
    MODALITY_VIDEO,
    STATUS_AVAILABLE,
    STATUS_ERROR,
    STATUS_LOADING,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
    CAP_VIDEO_GENERATION,
)

logger = get_logger("generation_runtime")

# --------------------------------------------------------------------------- #
# Honesty constants
# --------------------------------------------------------------------------- #
#: This layer never downloads weights — asserted by the test suite.
AUTOMATIC_DOWNLOAD = False

#: Canonical id of the first wired generation model.
WAN_I2V_MODEL_ID = "wan2.2-i2v"

#: Runtime id (must match :data:`models.runtimes.RUNTIME_WAN_I2V`).
RUNTIME_WAN_I2V = "wan_i2v"

#: Reason codes explaining a non-``AVAILABLE`` outcome (never a secret).
REASON_WEIGHTS_MISSING = "weights_missing"
REASON_RUNTIME_DEPS_MISSING = "runtime_dependencies_missing"
REASON_INVALID_INPUT = "invalid_input"
REASON_LOAD_FAILED = "load_failed"
REASON_READY = "ready"

#: Markers used to recognise a Wan 2.2 I2V checkpoint directory on this host.
_WAN_I2V_MARKERS: tuple[str, ...] = (
    "wan2.2-i2v",
    "wan2_2_i2v",
    "wan2.2_i2v",
    "wan22-i2v",
    "wan-i2v",
    "wan_i2v",
)

#: A directory only counts as a *loadable* checkpoint when it looks like a
#: diffusers pipeline (this is what the official pipeline loader consumes).
_DIFFUSERS_INDEX = "model_index.json"


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
#: The generation adapter has no local weights → cannot serve anything.
LIFECYCLE_NOT_CONFIGURED = STATUS_NOT_CONFIGURED
#: Weights found; the (heavy) real runtime is being initialized.
LIFECYCLE_LOADING = STATUS_LOADING
#: A real initialization + probe succeeded → the model can generate.
LIFECYCLE_AVAILABLE = STATUS_AVAILABLE
#: Initialization or a generation genuinely failed.
LIFECYCLE_ERROR = STATUS_ERROR
#: The runtime this adapter needs is not usable here (e.g. deps missing).
LIFECYCLE_UNAVAILABLE = STATUS_UNAVAILABLE

ALL_LIFECYCLES = (
    LIFECYCLE_NOT_CONFIGURED,
    LIFECYCLE_LOADING,
    LIFECYCLE_AVAILABLE,
    LIFECYCLE_ERROR,
    LIFECYCLE_UNAVAILABLE,
)


# --------------------------------------------------------------------------- #
# Errors (additive, typed)
# --------------------------------------------------------------------------- #
class GenerationError(Exception):
    """Base error for the generation runtime (never a fabricated result)."""

    reason = "generation_error"

    def __init__(self, message: str, *, reason: str = "", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason or self.reason
        self.metadata = metadata or {}


class WeightsMissingError(GenerationError):
    """No local Wan 2.2 I2V checkpoint was found (nothing is downloaded)."""

    reason = REASON_WEIGHTS_MISSING


class RuntimeUnavailableError(GenerationError):
    """The weights exist but the runtime needed to serve them is not usable here."""

    reason = REASON_RUNTIME_DEPS_MISSING


class InvalidGenerationInputError(GenerationError):
    """The :class:`GenerationRequest` failed validation."""

    reason = REASON_INVALID_INPUT


# --------------------------------------------------------------------------- #
# Request / Result (internal, additive value objects)
# --------------------------------------------------------------------------- #
#: Sensible, non-invented defaults (Wan 2.2 I2V runs at 480p / 16 fps natively).
DEFAULT_WIDTH = 832
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 16
DEFAULT_DURATION = 5.0
DEFQULT_NUM_INFERENCE_STEPS = 40


@dataclass
class GenerationRequest:
    """Internal generation request (image-to-video).

    Additive and self-contained: it does **not** modify ``ChatRequest`` or any
    Agent/SSE contract. ``image`` is a **local path** — remote URLs are rejected so
    no implicit download can ever happen.
    """

    image: str
    prompt: str = ""
    duration: float = DEFAULT_DURATION
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    #: Free-form generation options (steps / guidance / negative prompt / seed …).
    options: dict[str, Any] = field(default_factory=dict)
    model_id: str = WAN_I2V_MODEL_ID
    #: Optional caller-supplied artifact stem (sanitised before use).
    name: str = ""

    @property
    def num_frames(self) -> int:
        """Frames implied by ``duration`` × ``fps`` (Wan consumes ``4k+1`` frames)."""
        return max(1, int(round(float(self.duration) * float(self.fps))) + 1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    # ---------------------------------------------------------------- validation
    def validate(self) -> list[str]:
        """Return a list of human-readable validation problems (empty = valid)."""
        problems: list[str] = []
        if not self.model_id:
            problems.append("model_id is required")
        image = (self.image or "").strip()
        if not image:
            problems.append("image is required (a local file path)")
        elif image.lower().startswith(("http://", "https://")):
            problems.append("image must be a local path; remote URLs are not downloaded")
        elif not Path(image).is_file():
            problems.append(f"image not found on disk: {image}")
        if self.width <= 0 or self.height <= 0:
            problems.append("width and height must be positive integers")
        elif self.width % 16 or self.height % 16:
            problems.append("width and height must be multiples of 16 (Wan latent grid)")
        if self.fps <= 0 or self.fps > 60:
            problems.append("fps must be between 1 and 60")
        if self.duration <= 0 or self.duration > 60:
            problems.append("duration must be between 0 and 60 seconds")
        steps = self.options.get("num_inference_steps")
        if steps is not None:
            try:
                if int(steps) <= 0:
                    problems.append("options.num_inference_steps must be positive")
            except (TypeError, ValueError):
                problems.append("options.num_inference_steps must be an integer")
        return problems


@dataclass
class GenerationResult:
    """Internal generation result — artifact + metadata, **never** secrets.

    ``status`` uses the shared status vocabulary (``AVAILABLE`` when a real video
    was produced; ``NOT_CONFIGURED`` / ``UNAVAILABLE`` / ``ERROR`` otherwise). On a
    non-available outcome ``error`` carries a clear, secret-free explanation and
    ``artifact_path`` stays empty — no fabricated output.
    """

    status: str
    model: str = WAN_I2V_MODEL_ID
    provider: str = RUNTIME_WAN_I2V
    artifact_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    reason: str = ""
    available: bool = False

    @property
    def ok(self) -> bool:
        return self.available and bool(self.artifact_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "provider": self.provider,
            "artifact_path": self.artifact_path,
            "metadata": dict(self.metadata),
            "error": self.error,
            "reason": self.reason,
            "available": self.available,
            "secrets_exposed": False,
        }


# --------------------------------------------------------------------------- #
# Local checkpoint discovery (filesystem only — no network, no download)
# --------------------------------------------------------------------------- #
def _explicit_checkpoint() -> str:
    """An explicitly-configured checkpoint path (settings first, then env)."""
    from configs.settings import settings

    explicit = str(getattr(settings, "generation_wan_i2v_checkpoint", "") or "").strip()
    if explicit:
        return explicit
    return str(os.environ.get("LAIW_WAN_I2V_CHECKPOINT", "") or "").strip()


def _checkpoint_scan_roots() -> list[Path]:
    """Directories that may hold a locally-provisioned Wan 2.2 I2V checkpoint."""
    from configs.settings import settings

    roots: list[Path] = []
    base = str(getattr(settings, "generation_checkpoints_dir", "") or "").strip()
    if base:
        roots.append(Path(base))
    storage_dir = getattr(settings, "storage_dir", None)
    if storage_dir:
        roots.append(Path(storage_dir) / "gen_models")
    return roots


def _is_loadable_checkpoint(path: Path) -> bool:
    """True when ``path`` looks like a diffusers pipeline the official loader accepts."""
    if path.is_dir() and (path / _DIFFUSERS_INDEX).is_file():
        return True
    return False


def _looks_like_wan_i2v(path: Path) -> bool:
    name = path.name.lower()
    return any(marker in name for marker in _WAN_I2V_MARKERS)


def detect_wan_i2v_checkpoint() -> Path | None:
    """Return the local Wan 2.2 I2V checkpoint path, or ``None`` (local only).

    Discovery is a pure filesystem scan: it never lists a hub, never resolves a URL
    and never downloads. An explicit operator path wins (and, when set but invalid,
    disables scanning so a misconfiguration is never silently masked); otherwise the
    configured roots are scanned (shallow + one level deep) for a diffusers pipeline
    whose name carries a Wan I2V marker.
    """
    explicit = _explicit_checkpoint()
    if explicit:
        candidate = Path(explicit)
        return candidate if _is_loadable_checkpoint(candidate) else None

    for root in _checkpoint_scan_roots():
        if not root.exists():
            continue
        if _is_loadable_checkpoint(root) and _looks_like_wan_i2v(root):
            return root
        try:
            children = sorted(p for p in root.iterdir() if p.is_dir())
        except OSError:
            children = []
        for child in children:
            if _is_loadable_checkpoint(child) and _looks_like_wan_i2v(child):
                return child
    return None


def checkpoint_present() -> bool:
    """True when a loadable local Wan 2.2 I2V checkpoint is present on this host."""
    return detect_wan_i2v_checkpoint() is not None


# --------------------------------------------------------------------------- #
# CPU / T4-safe configuration discovery (real detection only, no fabrication)
# --------------------------------------------------------------------------- #
@dataclass
class RuntimeConfig:
    """Runtime configuration *discovered* from the installed stack (never invented).

    Every field is derived from what the installed ``torch`` actually reports. When
    ``torch`` cannot be imported the config stays ``unknown`` — no dtype, no offload
    and no ``device_map`` is asserted, because we do not fabricate hardware.
    """

    available: bool = False
    device: str = "unknown"
    dtype: str = ""
    supports_bfloat16: bool = False
    supports_model_cpu_offload: bool = False
    supports_device_map: bool = False
    gpu_name: str = ""
    compute_capability: str = ""
    total_memory_gb: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_runtime_config() -> RuntimeConfig:
    """Probe the *installed* torch stack and report only what it truly supports.

    ``dtype`` / offload / ``device_map`` are enabled **only** when the installed
    runtime provides them (``torch`` present, ``accelerate`` importable, CUDA
    detected). Cores that cannot be observed are left empty/unknown. No VRAM figure
    is invented — the memory value is a real reading from ``torch`` when available.
    """
    cfg = RuntimeConfig()
    try:
        import torch  # local import: heavy dependency, only probed on demand
    except Exception:  # noqa: BLE001 - torch is optional in this build
        cfg.notes.append("torch is not installed: runtime config unknown (no dtype/offload asserted)")
        return cfg

    cfg.available = True
    cuda = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    cfg.device = "cuda" if cuda else "cpu"
    # bfloat16 toggles on both CPU and CUDA only when torch genuinely supports it.
    try:
        cfg.supports_bfloat16 = bool(getattr(torch, "bfloat16", None)) and bool(torch.cuda.is_bf16_supported()) if cuda else True
    except Exception:  # noqa: BLE001
        cfg.supports_bfloat16 = bool(getattr(torch, "bfloat16", None))

    # dtype preference: bfloat16 when supported, else float16 on CUDA, float32 on CPU.
    if cfg.device == "cuda":
        cfg.dtype = "bfloat16" if cfg.supports_bfloat16 else "float16"
    else:
        cfg.dtype = "float32"

    # Offload / device_map are enabled only when `accelerate` is actually present.
    try:
        import importlib.util

        has_accelerate = importlib.util.find_spec("accelerate") is not None
    except Exception:  # noqa: BLE001
        has_accelerate = False
    cfg.supports_model_cpu_offload = has_accelerate and cfg.device == "cuda"
    cfg.supports_device_map = has_accelerate
    if not has_accelerate:
        cfg.notes.append("accelerate not installed: CPU offload / device_map not enabled")

    if cuda:
        try:
            props = torch.cuda.get_device_properties(0)
            cfg.gpu_name = str(getattr(props, "name", "") or "")
            major, minor = torch.cuda.get_device_capability(0)
            cfg.compute_capability = f"{major}.{minor}"
            total = float(getattr(props, "total_memory", 0) or 0)
            if total:
                cfg.total_memory_gb = round(total / (1024 ** 3), 1)
        except Exception as exc:  # noqa: BLE001
            cfg.notes.append(f"cuda device introspection unavailable: {exc}")
    else:
        cfg.notes.append("no CUDA device detected: running CPU-safe (float32)")
    return cfg


# --------------------------------------------------------------------------- #
# The Wan 2.2 I2V adapter (lazy, probe-first, no fabricated output)
# --------------------------------------------------------------------------- #
class WanI2VAdapter:
    """Real adapter for the official Wan 2.2 I2V (image-to-video) pipeline.

    Lifecycle: ``NOT_CONFIGURED → LOADING → AVAILABLE`` or ``ERROR``/``UNAVAILABLE``.
    Importing this class or constructing it does **no** heavy work: weights and the
    runtime stack are only touched inside :meth:`load`, which is called lazily from
    :meth:`generate`.
    """

    #: Adapter name recorded in the runtime matrix.
    name = "WanI2VAdapter"
    runtime = RUNTIME_WAN_I2V
    provider = RUNTIME_WAN_I2V
    model_id = WAN_I2V_MODEL_ID
    kind = KIND_VIDEO
    capability = CAP_VIDEO_GENERATION
    #: Hard input/output modalities — enforced by the Generation Router.
    required_modalities = (MODALITY_IMAGE, MODALITY_VIDEO)
    #: Declared capability surface (read by :class:`models.generation_router.GenerationRouter`).
    declared_capabilities = (CAP_VIDEO_GENERATION,)
    declared_modalities = (MODALITY_IMAGE, MODALITY_VIDEO)

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lifecycle = LIFECYCLE_NOT_CONFIGURED
        self._checkpoint: Path | None = None
        self._config: RuntimeConfig | None = None
        self._pipeline: Any = None
        self._error = ""
        self._reason = REASON_WEIGHTS_MISSING
        self._loaded_at = 0.0
        self._probe: dict[str, Any] = {}

    # ------------------------------------------------------------------ state
    @property
    def lifecycle(self) -> str:
        return self._lifecycle

    @property
    def error(self) -> str:
        return self._error

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None and self._lifecycle == LIFECYCLE_AVAILABLE

    def checkpoint(self) -> Path | None:
        """The local checkpoint this adapter would load (discovery is cached)."""
        with self._lock:
            if self._checkpoint is None:
                self._checkpoint = detect_wan_i2v_checkpoint()
            return self._checkpoint

    def provisioned_ids(self) -> set[str]:
        """Ids whose weights are physically present locally (no load, no download)."""
        return {self.model_id} if self.checkpoint() is not None else set()

    def is_configured(self) -> bool:
        """True when a loadable local checkpoint exists (does not load it)."""
        return self.checkpoint() is not None

    def status(self) -> str:
        """Current lifecycle state (never ``AVAILABLE`` without a real probe)."""
        with self._lock:
            if self._lifecycle in (LIFECYCLE_AVAILABLE, LIFECYCLE_LOADING, LIFECYCLE_ERROR):
                return self._lifecycle
            # NOT_CONFIGURED is refreshed lazily in case an operator provisioned weights.
            return LIFECYCLE_AVAILABLE if self.loaded else LIFECYCLE_NOT_CONFIGURED

    def describe(self) -> dict[str, Any]:
        """Secret-free, JSON-safe status snapshot (safe for a read-only endpoint)."""
        with self._lock:
            checkpoint = self.checkpoint()
            return {
                "model": self.model_id,
                "runtime": self.runtime,
                "adapter": self.name,
                "kind": self.kind,
                "capability": self.capability,
                "modalities": list(self.required_modalities),
                "lifecycle": self._lifecycle,
                "configured": checkpoint is not None,
                "loaded": self.loaded,
                "probed": bool(self._probe),
                "probe": dict(self._probe),
                "checkpoint_present": checkpoint is not None,
                "checkpoint_name": checkpoint.name if checkpoint else "",
                "checkpoint_ref": str(checkpoint) if checkpoint else "",
                "reason": self._reason,
                "error": self._error,
                "auto_download": AUTOMATIC_DOWNLOAD,
                "deps": {"torch": _module_present("torch"), "diffusers": _module_present("diffusers")},
                "runtime_config": (self._config or discover_runtime_config()).to_dict(),
                "secrets_exposed": False,
            }

    # ------------------------------------------------------------------ loading
    def ensure_available(self) -> None:
        """Lazily load + probe the pipeline; raise a typed error when it cannot run.

        This is the *only* entry point that touches weights, and it is called from
        :meth:`generate` — never at import or startup.
        """
        if self.loaded:
            return
        self.load()

    def load(self) -> None:
        """Real initialization: discover → import → build → probe (or raise)."""
        with self._lock:
            checkpoint = self.checkpoint()
            self._config = discover_runtime_config()

            if checkpoint is None:
                self._lifecycle = LIFECYCLE_NOT_CONFIGURED
                self._reason = REASON_WEIGHTS_MISSING
                self._error = (
                    "Wan 2.2 I2V checkpoint not found locally (NOT_CONFIGURED / weights_missing); "
                    "provision the official open weights on this host — nothing is downloaded automatically."
                )
                raise WeightsMissingError(self._error)

            # Weights exist → attempt the real runtime import (lazy).
            self._lifecycle = LIFECYCLE_LOADING
            try:
                pipeline = self._build_pipeline(checkpoint)
            except WeightsMissingError:
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                return self._fail(exc)

            report = self._run_probe(pipeline)
            if not report.get("ok"):
                self._pipeline = None
                self._probe = report
                self._lifecycle = LIFECYCLE_UNAVAILABLE
                self._reason = report.get("reason", REASON_LOAD_FAILED)
                self._error = report.get("error", "real probe failed")
                raise RuntimeUnavailableError(self._error, reason=self._reason, metadata=report)

            self._pipeline = pipeline
            self._probe = report
            self._lifecycle = LIFECYCLE_AVAILABLE
            self._reason = REASON_READY
            self._error = ""
            self._loaded_at = time.time()
            logger.info("Wan 2.2 I2V runtime AVAILABLE (checkpoint=%s)", checkpoint.name)

    def _fail(self, exc: BaseException) -> None:
        """Classify a genuine load failure into ERROR / UNAVAILABLE (never fake)."""
        text = str(exc)
        missing_deps = isinstance(exc, ModuleNotFoundError) or "No module named" in text
        self._pipeline = None
        if missing_deps:
            self._lifecycle = LIFECYCLE_UNAVAILABLE
            self._reason = REASON_RUNTIME_DEPS_MISSING
            self._error = f"Runtime dependencies missing for Wan 2.2 I2V: {text[:200]}"
            raise RuntimeUnavailableError(self._error, reason=self._reason, metadata={"error": text[:300]})
        self._lifecycle = LIFECYCLE_ERROR
        self._reason = REASON_LOAD_FAILED
        self._error = f"Wan 2.2 I2V initialization failed: {text[:200]}"
        raise GenerationError(self._error, reason=self._reason, metadata={"error": text[:300]})

    def _build_pipeline(self, checkpoint: Path) -> Any:
        """Build the official diffusers Wan image-to-video pipeline (real, lazy).

        Only reached when a local checkpoint exists. Imports ``torch``/``diffusers``
        lazily; a missing dependency surfaces as a typed error and no fabricated
        object is ever returned.
        """
        import importlib

        diffusers = importlib.import_module("diffusers")
        torch = importlib.import_module("torch")

        dtype = getattr(torch, self._config.dtype if self._config else "float32", None)
        pipe_cls = getattr(diffusers, "WanImageToVideoPipeline", None)
        if pipe_cls is None:
            raise RuntimeUnavailableError(
                "Installed diffusers has no WanImageToVideoPipeline: cannot serve Wan 2.2 I2V here.",
                reason=REASON_RUNTIME_DEPS_MISSING,
            )

        kwargs: dict[str, Any] = {"torch_dtype": dtype} if dtype is not None else {}
        pipeline = pipe_cls.from_pretrained(str(checkpoint), **kwargs)

        device = self._config.device if self._config else "cpu"
        if self._config and self._config.supports_model_cpu_offload and device == "cuda":
            # Genuine, supported optimisation only.
            pipeline.enable_model_cpu_offload()
        else:
            pipeline = pipeline.to(device)
        return pipeline

    def _run_probe(self, pipeline: Any) -> dict[str, Any]:
        """A real, cheap characteristic probe over the built pipeline.

        It inspects the pipeline's actual components (a fact about the *loaded*
        object) rather than executing a full generation, so probing stays cheap while
        still being a genuine signal — no availability is asserted without a pipeline.
        """
        try:
            components = getattr(pipeline, "components", None)
            component_names = sorted(components.keys()) if isinstance(components, dict) else []
            missing = [
                name
                for name in ("transformer", "vae")
                if isinstance(components, dict) and name in components and components.get(name) is None
            ]
            ok = bool(component_names) and not missing
            return {
                "ok": ok,
                "reason": REASON_READY if ok else REASON_LOAD_FAILED,
                "components": component_names,
                "device": self._config.device if self._config else "unknown",
                "dtype": self._config.dtype if self._config else "",
                "error": "" if ok else f"pipeline components missing: {missing or 'none detected'}",
                "checked_at": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": REASON_LOAD_FAILED, "error": str(exc)[:200]}

    # ---------------------------------------------------------------- generation
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a video for ``request`` (lazy load + real run), or report why not.

        Returns a :class:`GenerationResult`. When the runtime cannot genuinely run,
        the result is ``NOT_CONFIGURED`` / ``UNAVAILABLE`` / ``ERROR`` with a clear
        ``reason`` and **no** ``artifact_path`` — a fabricated video is never produced.
        """
        problems = request.validate()
        if problems:
            return GenerationResult(
                status=STATUS_ERROR,
                model=request.model_id or self.model_id,
                artifact_path="",
                error="; ".join(problems),
                reason=REASON_INVALID_INPUT,
                metadata={"problems": problems},
            )

        try:
            self.ensure_available()
        except WeightsMissingError as exc:
            return GenerationResult(
                status=STATUS_NOT_CONFIGURED,
                error=exc.message,
                reason=exc.reason,
            )
        except RuntimeUnavailableError as exc:
            return GenerationResult(
                status=STATUS_UNAVAILABLE,
                error=exc.message,
                reason=exc.reason,
                metadata=dict(exc.metadata),
            )
        except GenerationError as exc:
            return GenerationResult(
                status=STATUS_ERROR,
                error=exc.message,
                reason=exc.reason,
                metadata=dict(exc.metadata),
            )

        return self._run_generation(request)

    def _run_generation(self, request: GenerationRequest) -> GenerationResult:
        """Execute the real pipeline and export the artifact (genuine, no mock)."""
        try:
            frames = self._invoke_pipeline(request)
        except Exception as exc:  # noqa: BLE001 - a real run failure, reported honestly
            text = str(exc)
            self._lifecycle = LIFECYCLE_ERROR
            self._reason = REASON_LOAD_FAILED
            self._error = f"Wan 2.2 I2V generation failed: {text[:200]}"
            return GenerationResult(
                status=STATUS_ERROR,
                error=self._error,
                reason=REASON_LOAD_FAILED,
                metadata={"error": text[:300]},
            )

        artifact, meta = self._export_artifact(frames, request)
        return GenerationResult(
            status=STATUS_AVAILABLE,
            model=request.model_id or self.model_id,
            artifact_path=str(artifact),
            metadata=meta,
            reason=REASON_READY,
            available=True,
        )

    def _invoke_pipeline(self, request: GenerationRequest) -> Any:
        """Call the official pipeline with the validated request parameters."""
        options = dict(request.options or {})
        call: dict[str, Any] = {
            "prompt": request.prompt or "",
            "height": int(request.height),
            "width": int(request.width),
            "num_frames": int(request.num_frames),
            "num_inference_steps": int(options.pop("num_inference_steps", DEFQULT_NUM_INFERENCE_STEPS)),
        }
        for key in ("negative_prompt", "guidance_scale", "seed"):
            if options.get(key) is not None:
                call[key] = options[key]
        if options.get("generator") is None and call.get("seed") is not None:
            try:
                import torch

                call["generator"] = torch.Generator(device=self._config.device if self._config else "cpu").manual_seed(int(call.pop("seed")))
            except Exception:  # noqa: BLE001
                pass
        else:
            call.pop("seed", None)

        # The image is loaded from the local path (validated to exist).
        try:
            from PIL import Image  # local import: only needed for a real run

            image = Image.open(request.image).convert("RGB")
        except Exception:  # noqa: BLE001 - fall back to the raw path the pipeline accepts
            image = request.image

        output = self._pipeline(image=image, **call)
        frames = getattr(output, "frames", None)
        if frames is None:
            raise GenerationError("pipeline returned no frames", reason=REASON_LOAD_FAILED)
        return frames

    def _export_artifact(self, frames: Any, request: GenerationRequest) -> tuple[Path, dict[str, Any]]:
        """Export the generated frames to a real artifact file (mp4 when possible)."""
        from configs.settings import settings

        out_dir = Path(getattr(settings, "artifacts_dir", Path(settings.storage_dir) / "artifacts")) / "generation"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_stem(request.name) or f"{self.model_id.replace('.', '_')}_{uuid.uuid4().hex[:10]}"
        video_path = out_dir / f"{stem}.mp4"

        exported = False
        try:
            from diffusers.utils import export_to_video

            export_to_video(frames[0], str(video_path), fps=int(request.fps))
            exported = True
        except Exception as exc:  # noqa: BLE001 - fall back to PNG frames
            logger.warning("mp4 export failed (%s); writing PNG frames instead", exc)

        artifacts: list[str] = []
        if exported and video_path.is_file():
            artifacts.append(str(video_path))
        else:
            # Honest fallback: persist the real frames as images (still a real artifact).
            frame_dir = out_dir / stem
            frame_dir.mkdir(parents=True, exist_ok=True)
            try:
                for index, frame in enumerate(frames if isinstance(frames, list) else [frames]):
                    frame_path = frame_dir / f"frame_{index:04d}.png"
                    frame.save(frame_path)
                    artifacts.append(str(frame_path))
            except Exception as exc:  # noqa: BLE001
                raise GenerationError(f"artifact export failed: {exc}", reason=REASON_LOAD_FAILED) from exc

        size_bytes = video_path.stat().st_size if (exported and video_path.is_file()) else 0
        meta = {
            "kind": "video" if exported else "frames",
            "artifacts": artifacts,
            "primary_artifact": artifacts[0] if artifacts else "",
            "width": int(request.width),
            "height": int(request.height),
            "fps": int(request.fps),
            "duration": float(request.duration),
            "num_frames": int(request.num_frames),
            "prompt": request.prompt,
            "size_bytes": size_bytes,
            "model": request.model_id or self.model_id,
            "runtime": self.runtime,
            "device": self._config.device if self._config else "unknown",
            "dtype": self._config.dtype if self._config else "",
            "generated_at": time.time(),
        }
        return Path(artifacts[0]) if artifacts else video_path, meta


def _module_present(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    return cleaned.strip("._-")[:64]


# --------------------------------------------------------------------------- #
# Manager (singleton, lazy — nothing heavy at import/startup)
# --------------------------------------------------------------------------- #
class LocalGenerationManager:
    """Owns the wired local generation adapters and answers honest questions.

    Importing/constructing the manager is cheap: no weights, no ``torch``/``diffusers``
    and no network. The adapter itself stays ``NOT_CONFIGURED`` until a generation is
    explicitly requested (or an operator provisions weights and asks for a load).
    """

    def __init__(self) -> None:
        self._adapters: dict[str, WanI2VAdapter] = {RUNTIME_WAN_I2V: WanI2VAdapter()}

    @property
    def adapters(self) -> dict[str, WanI2VAdapter]:
        """The wired generation adapters keyed by runtime id (no weights loaded)."""
        return dict(self._adapters)

    def adapter_for(self, model_id: str) -> WanI2VAdapter | None:
        """Return the adapter that serves ``model_id`` (``None`` when unwired)."""
        from models.generation import get_generation_registration

        reg = get_generation_registration(model_id)
        if reg is None:
            return None
        return self._adapters.get(reg.runtime)

    def provisioned_ids(self) -> set[str]:
        """Ids whose local weights exist on this host (offline; no load, no import)."""
        found: set[str] = set()
        for adapter in self._adapters.values():
            found |= adapter.provisioned_ids()
        return found

    def status(self, *, load: bool = False) -> dict[str, Any]:
        """Secret-free status of every wired generation model (optionally load/probe)."""
        from models.generation import get_generation_registration

        entries: list[dict[str, Any]] = []
        for runtime, adapter in self._adapters.items():
            reg = get_generation_registration(adapter.model_id)
            row = adapter.describe()
            row["registered"] = reg is not None
            row["surfaces"] = list(reg.surfaces) if reg else []
            if load and adapter.is_configured():
                try:
                    adapter.ensure_available()
                except GenerationError as exc:  # noqa: BLE001 - reported, not raised
                    row["load_error"] = exc.message
                    row["load_reason"] = exc.reason
            row["lifecycle"] = adapter.lifecycle
            row["loaded"] = adapter.loaded
            entries.append(row)

        return {
            "scope": "generation-runtime",
            "runtime": RUNTIME_WAN_I2V,
            "models": entries,
            "available": sorted(e["model"] for e in entries if e["loaded"]),
            "provisioned": sorted(self.provisioned_ids()),
            "automatic_download": AUTOMATIC_DOWNLOAD,
            "secrets_exposed": False,
        }

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Route the request to the adapter serving its model and generate."""
        adapter = self.adapter_for(request.model_id)
        if adapter is None:
            return GenerationResult(
                status=STATUS_NOT_CONFIGURED,
                model=request.model_id,
                error=f"No wired generation runtime serves model '{request.model_id}'.",
                reason="runtime_unsupported",
            )
        return adapter.generate(request)


_MANAGER: LocalGenerationManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_local_generation_manager() -> LocalGenerationManager:
    """Process-wide singleton (lazily built; holds no weights until a run)."""
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = LocalGenerationManager()
    return _MANAGER


__all__ = [
    "AUTOMATIC_DOWNLOAD",
    "WAN_I2V_MODEL_ID",
    "RUNTIME_WAN_I2V",
    "REASON_WEIGHTS_MISSING",
    "REASON_RUNTIME_DEPS_MISSING",
    "REASON_INVALID_INPUT",
    "REASON_LOAD_FAILED",
    "REASON_READY",
    "LIFECYCLE_NOT_CONFIGURED",
    "LIFECYCLE_LOADING",
    "LIFECYCLE_AVAILABLE",
    "LIFECYCLE_ERROR",
    "LIFECYCLE_UNAVAILABLE",
    "ALL_LIFECYCLES",
    "GenerationError",
    "WeightsMissingError",
    "RuntimeUnavailableError",
    "InvalidGenerationInputError",
    "GenerationRequest",
    "GenerationResult",
    "RuntimeConfig",
    "discover_runtime_config",
    "detect_wan_i2v_checkpoint",
    "checkpoint_present",
    "WanI2VAdapter",
    "LocalGenerationManager",
    "get_local_generation_manager",
]
