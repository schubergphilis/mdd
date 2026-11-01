"""Hypothesis profiles for the prose property tests.

``ci`` is the default. It is derandomized, so ``mise run ci`` explores the same
examples on every machine and a red build always reproduces. ``fuzz`` is the
long, randomized search ``mise run prose-fuzz`` runs on demand; select it, or
any other registered profile, with ``MDD_HYPOTHESIS_PROFILE``.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

# The oracle's asserts live outside a test module. Rewrite them anyway, so a
# failing property shows the values that differed.
pytest.register_assert_rewrite("tests.prose.oracle")

PROFILE_ENV = "MDD_HYPOTHESIS_PROFILE"

settings.register_profile(
    "ci",
    max_examples=200,
    derandomize=True,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "fuzz",
    max_examples=20_000,
    derandomize=False,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get(PROFILE_ENV, "ci"))
