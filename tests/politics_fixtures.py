"""Temporary national policy definitions for rule and integration tests."""

from contextlib import contextmanager
from unittest.mock import patch

from map_logic import politics


@contextmanager
def policy_fixtures(*definitions):
    """Use the same fixture definitions for policy iteration and ID lookup."""
    policies = tuple({"name": definition["id"], **definition} for definition in definitions)
    by_id = {policy["id"]: policy for policy in policies}
    with patch.object(politics, "POLICIES", policies), patch.object(politics, "POLICIES_BY_ID", by_id):
        yield
