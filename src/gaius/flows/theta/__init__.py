"""Theta flows. Keep this package lazy so ``python -m gaius.flows.theta.cycle``
does not import the module twice (Metaflow runpy warning).
"""

__all__ = ["ThetaCycleFlow"]


def __getattr__(name: str):
    if name == "ThetaCycleFlow":
        from gaius.flows.theta.cycle import ThetaCycleFlow

        return ThetaCycleFlow
    raise AttributeError(name)
