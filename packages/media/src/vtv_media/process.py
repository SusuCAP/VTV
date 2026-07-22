import subprocess
from collections.abc import Sequence
from pathlib import Path


class MediaProcessError(RuntimeError):
    pass


def run_media_process(
    arguments: Sequence[str | Path],
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    command = [str(argument) for argument in arguments]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise MediaProcessError(f"media executable not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessError(
            f"media command timed out after {timeout_seconds}s: {command[0]}"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip()[-4000:]
        raise MediaProcessError(f"media command failed ({result.returncode}): {detail}")
    return result
