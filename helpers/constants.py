"""Hardcoded server constants (``constants.yml``).

Values that drive server-side game logic but aren't (yet) found in master data --
generous preservation defaults, or figures that only ever lived in the client/server.
Kept separate from ``config.yml`` (deployment) so they're easy to audit and tweak.
"""

from pathlib import Path

import yaml

_loaded = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "constants.yml").read_text(
        encoding="utf-8"
    )
)
constants: dict = _loaded if isinstance(_loaded, dict) else {}
