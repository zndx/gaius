"""GaiusFlow._claim_yk must read gpu_tokens off the instance.

Metaflow installs a property on the running flow class for every inherited
class attribute, so `getattr(type(self), "gpu_tokens")` hands back the
descriptor and `int()` raises:

    TypeError: int() argument must be a string, a bytes-like object or a
    real number, not 'property'

That took down every flow reaching emit_lineage_start — prospects,
clt_skos_admit and clt_skos_label alike.
"""

from __future__ import annotations

import inspect

from gaius.flows.base import GaiusFlow


def _claim_yk_source() -> str:
    return inspect.getsource(GaiusFlow._claim_yk)


def test_gpu_tokens_is_not_read_off_the_class():
    src = _claim_yk_source()
    assert 'getattr(type(self), "gpu_tokens"' not in src
    assert 'getattr(self, "gpu_tokens", 0)' in src


def test_property_descriptor_would_have_raised():
    """Pin the failure mode so the class-level read cannot come back."""

    class Base:
        gpu_tokens: int = 0

    class Running(Base):
        # What Metaflow injects on the class it actually runs.
        gpu_tokens = property(lambda self: 0)

    running = Running()
    try:
        int(getattr(type(running), "gpu_tokens", 0) or 0)
    except TypeError as e:
        assert "property" in str(e)
    else:  # pragma: no cover
        raise AssertionError("class-level read should raise TypeError")

    # The instance read is what _claim_yk now does.
    assert int(getattr(running, "gpu_tokens", 0) or 0) == 0


def test_subclass_tokens_survive_the_instance_read():
    """A flow declaring tokens must still gate the YK queue check."""

    class Base:
        gpu_tokens: int = 0

    class Heavy(Base):
        gpu_tokens = property(lambda self: 4)

    assert int(getattr(Heavy(), "gpu_tokens", 0) or 0) == 4
