"""Explicit user-confirmed intake scope; never delete historical facts."""
from contextlib import contextmanager
import hashlib
from .sync_runtime import SyncBlocked


# The user confirmed this source is not used. No URL or credential is stored.
UNUSED_SOURCE_HASHES = {
    'form_ctech': '5444e18f6db88cb3896f3cd06e2dcc4c91fd82d3de379a398efa1312c6ca822b',
}


def active_roles(roles):
    active = dict(roles)
    for role, sha in UNUSED_SOURCE_HASHES.items():
        if role in active:
            if hashlib.sha256(active[role].encode()).hexdigest() != sha:
                raise SyncBlocked('UNUSED_SOURCE_IDENTITY_CHANGED')
            del active[role]
    return active


@contextmanager
def exclude_legacy_forms(collector, roles):
    """Adapt fixed legacy form list without modifying its verified program.

    Empty sheets here mean explicit exclusion, never a successful source read
    or verified zero. Other loads retain their original missing-source errors.
    """
    active_roles(roles)  # Bind the approval to the exact reviewed resource.
    original = collector.load
    excluded = {'opt-form-' + role[5:] + '.json': role
                for role in UNUSED_SOURCE_HASHES}
    def scoped_load(name):
        if name in excluded:
            return {'sheets': [], 'source_scope': 'USER_CONFIRMED_UNUSED'}
        return original(name)
    collector.load = scoped_load
    try:
        yield
    finally:
        collector.load = original
