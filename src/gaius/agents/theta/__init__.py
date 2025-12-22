"""ThetaAgent - Neuromorphic Situational Awareness for Gaius.

This module implements a biologically-inspired attention management system
grounded in Graziano's Attention Schema Theory (AST) and hippocampal theta
wave dynamics.

The ThetaAgent provides `/sitrep` as the single pane of glass for daily
situational awareness, synthesizing:
- Objectives and agent thoughts
- Personal agenda (filtered from all project agendas)
- Current events via search/research actions
- Evolving Gaius capabilities

References:
- Graziano, M.S.A. (2013). Consciousness and the Social Brain
- Zhang et al. (2015). Traveling Theta Waves in the Human Hippocampus
- Monaco et al. (2020). Cognitive Swarming with Attractor Dynamics
"""

from .horizons import Horizon, HorizonView
from .schema import AttentionTarget, AttentionSchema
from .sitrep import SituationReport, SitrepSection
from .agent import ThetaAgent

__all__ = [
    "ThetaAgent",
    "Horizon",
    "HorizonView",
    "AttentionTarget",
    "AttentionSchema",
    "SituationReport",
    "SitrepSection",
]
