"""Bootstrap EditorVoice when launched by the Windows desktop wrapper."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _open_log():
    data_root = Path(
        os.getenv(
            "VIENEU_APP_DATA_DIR",
            str(Path(os.getenv("LOCALAPPDATA", Path.home())) / "EditorVoice"),
        )
    )
    log_dir = data_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return (log_dir / "latest.log").open("w", encoding="utf-8", buffering=1)


def main() -> None:
    log_file = _open_log()
    sys.stdout = log_file
    sys.stderr = log_file
    try:
        print("Starting EditorVoice desktop server...")
        from apps.quick_studio import main as run_server

        run_server()
    except BaseException:
        traceback.print_exc()
        raise
    finally:
        log_file.flush()


if __name__ == "__main__":
    main()
