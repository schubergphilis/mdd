"""Command implementations for mdd CLI.

Each module exposes a ``register(subparsers, parents)`` function called
from :mod:`mdd.cli` to wire its subparser(s) into the global argparse tree.

:func:`register_skill_root` is re-exported here, next to the commands it
affects, so a composing distribution reaches the skills-bundle seam the
same way it reaches :func:`mdd.mirror.register_backend` — from the package,
not from the module that happens to implement it.
"""

from mdd.commands.skills import register_skill_root, skill_roots

__all__ = ["register_skill_root", "skill_roots"]
