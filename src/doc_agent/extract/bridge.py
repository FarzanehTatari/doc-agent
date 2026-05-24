"""Python ↔ MATLAB bridge.

Shells out to MATLAB in `-batch` (headless) mode, runs an extractor script that
writes JSON to a temp file, then validates that JSON against the canonical schema.

Auto-detects `matlab` on PATH and inside `/Applications/MATLAB_R*.app/bin/`
(macOS install layout). Override with `MATLAB_EXECUTABLE` in `.env`.
"""

from __future__ import annotations

import glob
import json
import shutil
import subprocess
from pathlib import Path

from pydantic import ValidationError

from doc_agent.config import settings
from doc_agent.extract.schema import CanonicalModel
from doc_agent.utils.logger import get_logger

log = get_logger(__name__)


class MatlabBridge:
    """Wraps `matlab -batch ...` calls and validates the JSON they produce."""

    def __init__(
        self,
        *,
        matlab_executable: str | None = None,
        scripts_dir: Path | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self.matlab = matlab_executable or settings.matlab_executable or self._auto_detect_matlab()
        if not self.matlab:
            raise RuntimeError(
                "MATLAB executable not found. Either:\n"
                "  • Put `matlab` on your PATH, or\n"
                "  • Set MATLAB_EXECUTABLE in .env to the full path "
                "(e.g. /Applications/MATLAB_R2025b.app/bin/matlab)"
            )
        self.scripts_dir = Path(scripts_dir or settings.matlab_scripts_dir)
        if not self.scripts_dir.exists():
            raise FileNotFoundError(
                f"MATLAB scripts dir not found: {self.scripts_dir}"
            )
        self.timeout_s = int(timeout_s or settings.matlab_timeout_s)

    # ---- public API -----------------------------------------------------
    def extract_slx(self, slx_path: Path | str, out_json: Path | str) -> CanonicalModel:
        """Run `extract_slx(slxPath, outJson)` and return the validated CanonicalModel."""
        slx_path = Path(slx_path).resolve()
        out_json = Path(out_json).resolve()
        if not slx_path.exists():
            raise FileNotFoundError(slx_path)
        out_json.parent.mkdir(parents=True, exist_ok=True)

        cmd_str = (
            f"addpath('{self.scripts_dir.as_posix()}'); "
            f"extract_slx('{slx_path.as_posix()}', '{out_json.as_posix()}'); "
            f"exit;"
        )
        self._run_matlab(cmd_str, what=f"extract_slx({slx_path.name})")

        return self.load_canonical(out_json)

    def build_test_model(self, out_dir: Path | str) -> tuple[Path, Path]:
        """Run `build_test_model(outDir)` and return the (slx, sldd) paths produced."""
        out_dir = Path(out_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd_str = (
            f"addpath('{self.scripts_dir.as_posix()}'); "
            f"build_test_model('{out_dir.as_posix()}'); "
            f"exit;"
        )
        self._run_matlab(cmd_str, what="build_test_model")
        slx = out_dir / "VSEModel.slx"
        sldd = out_dir / "VSEModel.sldd"
        if not slx.exists() or not sldd.exists():
            raise RuntimeError(
                f"build_test_model did not produce expected files in {out_dir}"
            )
        return slx, sldd

    @staticmethod
    def load_canonical(path: Path | str) -> CanonicalModel:
        """Read a JSON file produced by extract_slx and validate against the schema."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            return CanonicalModel.model_validate(raw)
        except ValidationError as e:
            # Wrap so the CLI shows a useful message instead of a wall of Pydantic
            raise RuntimeError(
                f"Canonical JSON at {path} failed schema validation:\n{e}"
            ) from e

    # ---- internals -------------------------------------------------------
    def _run_matlab(self, cmd: str, *, what: str) -> str:
        """Execute `matlab -batch cmd`. Returns combined stdout; raises on failure."""
        log.info("MATLAB %s → %s", what, self.matlab)
        try:
            proc = subprocess.run(
                [self.matlab, "-batch", cmd],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"MATLAB {what} timed out after {self.timeout_s}s. "
                f"Increase MATLAB_TIMEOUT_S or check the script for an infinite loop."
            ) from e
        except FileNotFoundError as e:
            raise RuntimeError(
                f"MATLAB executable not found: {self.matlab}"
            ) from e

        if proc.returncode != 0:
            raise RuntimeError(
                f"MATLAB {what} exited with code {proc.returncode}.\n"
                f"--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
            )
        return proc.stdout

    @staticmethod
    def _auto_detect_matlab() -> str | None:
        """Look for matlab on PATH, then inside common macOS install locations."""
        p = shutil.which("matlab")
        if p:
            return p
        # macOS — `/Applications/MATLAB_R2025b.app/bin/matlab` etc.
        for path in sorted(glob.glob("/Applications/MATLAB_R*.app/bin/matlab"), reverse=True):
            if Path(path).exists():
                return path
        # Generic /Applications/MATLAB.app
        candidate = "/Applications/MATLAB.app/bin/matlab"
        if Path(candidate).exists():
            return candidate
        return None
