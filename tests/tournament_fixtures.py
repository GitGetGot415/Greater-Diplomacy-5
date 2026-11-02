"""Fast password derivation for tournament rule tests only."""

import base64
import hashlib
from unittest.mock import patch

from data.multiplayer.tournament import files


def _fixture_key(password, salt):
    """Keep password and salt checks without repeated password hardening."""
    return base64.urlsafe_b64encode(hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 1))


def fast_tournament_crypto():
    """Patch behavior tests locally. Dedicated encryption tests retain production derivation."""
    return patch.object(files, "generate_fernet_key_from_password", new=_fixture_key)
