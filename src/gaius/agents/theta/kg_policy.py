"""Knowledge Gradient policy for consolidation decisions.

Implements the Knowledge Gradient (KG) from Optimal Learning (Powell & Ryzhov, 2012)
to provide economic justification for subsumption verification decisions.

The KG measures the expected improvement in the best alternative's value
after making a measurement (verifying a subsumption):

    KG(x) = E[max_{x'} μ^{n+1}_{x'} | x^n = x] - max_{x'} μ^n_{x'}

where:
    μ^n_x = Current belief about value of alternative x
    μ^{n+1}_x = Updated belief after observing outcome of measuring x

For consolidation, the KG policy selects subsumption candidates that maximize
expected improvement in downstream retrieval quality.

Research Phase Note:
    During initial development, verification costs may exceed the KG threshold.
    This is warranted while:
    1. Building measurement infrastructure (SHAP, holdout testing)
    2. Calibrating the belief state model against empirical retrieval quality
    3. Characterizing the cost function (GPU cycles, latency, token consumption)
    4. Validating that the KG formulation correctly predicts retrieval improvement

References:
    - Powell, W.B. & Ryzhov, I.O. (2012). Optimal Learning. Wiley.
    - Frazier, P., Powell, W., Dayanik, S. (2009). The Knowledge-Gradient Policy
      for Correlated Normal Beliefs. INFORMS Journal on Computing.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
from scipy.stats import norm

import logging

from .subsumption import SubsumptionCandidate

logger = logging.getLogger(__name__)


@dataclass
class BeliefState:
    """Bayesian belief state about retrieval quality improvements.

    ACADEMIC IMPLEMENTATION (Powell & Ryzhov 2012, Chapter 4):
    Maintains prior distributions over the value of each subsumption candidate
    for retrieval quality improvement. Updated via Bayesian inference after
    each measurement (SHAP evaluation).

    Key feature: DYNAMIC NOISE ESTIMATION
    Rather than using a fixed measurement_noise, we estimate it empirically
    from the residuals between predictions and observations. This implements
    the "unknown variance" extension from Bayesian statistics:
        σ²_ε ~ InverseGamma(α, β) with α, β updated from residuals

    Following the Optimal Learning framework, we model beliefs as independent
    normal distributions with known precision (variance).

    Attributes:
        means: Mean belief about improvement value for each candidate key
        variances: Variance in belief (uncertainty) for each candidate key
        measurement_noise: Current estimated observation noise variance
        prior_mean: Default prior mean for new candidates
        prior_variance: Default prior variance for new candidates
        noise_alpha: Inverse-Gamma shape parameter for noise estimation
        noise_beta: Inverse-Gamma scale parameter for noise estimation
    """

    means: dict = field(default_factory=dict)
    variances: dict = field(default_factory=dict)
    measurement_noise: float = 0.1
    prior_mean: float = 0.0
    prior_variance: float = 1.0
    n_measurements: int = 0

    # Dynamic noise estimation parameters (Inverse-Gamma prior)
    # α=2, β=0.2 gives prior mean of 0.1 with moderate uncertainty
    noise_alpha: float = 2.0
    noise_beta: float = 0.2
    _residuals: list = field(default_factory=list)
    _residuals_limit: int = 50

    def get_belief(self, candidate_key: str) -> tuple[float, float]:
        """Get current belief (mean, variance) for a candidate.

        Args:
            candidate_key: Unique identifier for the candidate

        Returns:
            Tuple of (mean, variance) for the candidate's value belief
        """
        mean = self.means.get(candidate_key, self.prior_mean)
        var = self.variances.get(candidate_key, self.prior_variance)
        return mean, var

    def current_best(self) -> float:
        """Get the current best expected value across all candidates.

        Returns:
            Maximum mean value, or prior_mean if no beliefs exist
        """
        if not self.means:
            return self.prior_mean
        return max(self.means.values())

    def estimate_noise_variance(self) -> float:
        """Estimate measurement noise variance from residuals.

        ACADEMIC IMPLEMENTATION:
        Uses the posterior mean of the Inverse-Gamma distribution:
            E[σ²] = β / (α - 1) for α > 1

        With Inverse-Gamma conjugate updates:
            α_post = α_prior + n/2
            β_post = β_prior + Σ(residuals²)/2

        Returns:
            Estimated noise variance
        """
        if not self._residuals:
            # Use prior mean: β/(α-1)
            if self.noise_alpha > 1:
                return self.noise_beta / (self.noise_alpha - 1)
            return self.measurement_noise

        # Compute sum of squared residuals
        ssr = sum(r**2 for r in self._residuals)
        n = len(self._residuals)

        # Posterior parameters
        alpha_post = self.noise_alpha + n / 2
        beta_post = self.noise_beta + ssr / 2

        # Posterior mean
        if alpha_post > 1:
            estimated = beta_post / (alpha_post - 1)
        else:
            estimated = self.measurement_noise

        logger.debug(
            f"Estimated noise variance: {estimated:.4f} "
            f"(α={alpha_post:.1f}, β={beta_post:.2f}, n={n})"
        )

        return estimated

    def update(
        self,
        candidate_key: str,
        observed_value: float,
        observation_variance: float | None = None,
    ) -> tuple[float, float]:
        """Bayesian update of belief after observing measurement.

        ACADEMIC IMPLEMENTATION (Normal-Normal conjugate with dynamic noise):
        1. Computes residual between prediction and observation
        2. Updates noise estimate from residuals
        3. Performs normal-normal conjugate belief update

        The posterior update follows:
            posterior_precision = prior_precision + measurement_precision
            posterior_mean = (prior_precision * prior_mean + measurement_precision * observation)
                           / posterior_precision

        Args:
            candidate_key: Identifier for the measured candidate
            observed_value: Measured improvement value (from SHAP)
            observation_variance: Variance of the observation (default: estimated)

        Returns:
            Tuple of (new_mean, new_variance) after update
        """
        prior_mean, prior_var = self.get_belief(candidate_key)

        # Compute residual for noise estimation
        residual = observed_value - prior_mean
        self._residuals.append(residual)

        # Trim residual history
        if len(self._residuals) > self._residuals_limit:
            self._residuals = self._residuals[-self._residuals_limit:]

        # Update noise estimate from accumulated residuals
        self.measurement_noise = self.estimate_noise_variance()

        # Use provided variance or estimated noise
        obs_var = observation_variance or self.measurement_noise

        # Ensure obs_var is positive and reasonable
        obs_var = max(obs_var, 1e-6)

        # Bayesian update (normal-normal conjugate)
        prior_precision = 1.0 / prior_var
        obs_precision = 1.0 / obs_var

        posterior_precision = prior_precision + obs_precision
        posterior_mean = (prior_precision * prior_mean + obs_precision * observed_value) / posterior_precision
        posterior_var = 1.0 / posterior_precision

        # Store updated belief
        self.means[candidate_key] = posterior_mean
        self.variances[candidate_key] = posterior_var
        self.n_measurements += 1

        logger.debug(
            f"Updated belief for {candidate_key}: "
            f"μ={prior_mean:.3f}→{posterior_mean:.3f}, "
            f"σ²={prior_var:.3f}→{posterior_var:.3f}, "
            f"noise={self.measurement_noise:.4f}"
        )

        return posterior_mean, posterior_var

    def get_noise_stats(self) -> dict:
        """Get statistics about noise estimation.

        Returns:
            Dict with noise estimation details
        """
        n = len(self._residuals)
        if n > 0:
            ssr = sum(r**2 for r in self._residuals)
            alpha_post = self.noise_alpha + n / 2
            beta_post = self.noise_beta + ssr / 2

            # 95% credible interval for noise variance
            # Using inverse-gamma quantiles
            from scipy.stats import invgamma
            noise_dist = invgamma(a=alpha_post, scale=beta_post)
            ci_lower = float(noise_dist.ppf(0.025))
            ci_upper = float(noise_dist.ppf(0.975))
        else:
            ci_lower = 0.0
            ci_upper = 1.0

        return {
            "current_estimate": self.measurement_noise,
            "n_residuals": n,
            "residual_mean": float(np.mean(self._residuals)) if self._residuals else 0.0,
            "residual_std": float(np.std(self._residuals)) if len(self._residuals) > 1 else 0.0,
            "ci_95_lower": ci_lower,
            "ci_95_upper": ci_upper,
        }

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "means": self.means.copy(),
            "variances": self.variances.copy(),
            "measurement_noise": self.measurement_noise,
            "n_measurements": self.n_measurements,
            "current_best": self.current_best(),
            "noise_estimation": self.get_noise_stats(),
        }


def compute_kg_factor(z: float) -> float:
    """Compute the KG factor f(z) = z*Φ(z) + φ(z).

    This is the core computation from Frazier et al. (2009) Proposition 1.

    Args:
        z: Normalized improvement value

    Returns:
        KG factor value
    """
    return z * norm.cdf(z) + norm.pdf(z)


class KnowledgeGradientPolicy:
    """Knowledge Gradient policy for subsumption verification decisions.

    Implements the KG policy from Powell & Ryzhov (2012) to select which
    subsumption candidates to verify based on expected value of information.

    The policy computes:
        KG(x) = σ(x) * f(z(x))

    where:
        σ(x) = standard deviation of belief update
        z(x) = normalized improvement potential
        f(z) = z*Φ(z) + φ(z) (see compute_kg_factor)

    Args:
        measurement_cost: Cost of verifying one subsumption (GPU cycles, etc.)
        research_mode: If True, bypass cost threshold (for theory development)
        discount_factor: Time discount for future value (default 1.0)
    """

    def __init__(
        self,
        measurement_cost: float = 1.0,
        research_mode: bool = True,
        discount_factor: float = 1.0,
    ):
        self.measurement_cost = measurement_cost
        self.research_mode = research_mode
        self.discount_factor = discount_factor
        self.belief_state = BeliefState()
        self._history: list[dict] = []

    def candidate_key(self, candidate: SubsumptionCandidate) -> str:
        """Generate unique key for a subsumption candidate.

        Args:
            candidate: SubsumptionCandidate to key

        Returns:
            Unique string key
        """
        return f"{candidate.subclass}⊑{candidate.superclass}"

    def compute_kg(
        self,
        candidate: SubsumptionCandidate,
        belief_state: BeliefState | None = None,
    ) -> float:
        """Compute Knowledge Gradient for a subsumption candidate.

        The KG measures expected improvement in the best alternative's value
        after measuring this candidate.

        From Frazier et al. (2009):
            KG(x) = σ_tilde(x) * f(-|z(x)|)

        where:
            σ_tilde = sqrt(σ²_x * σ²_ε / (σ²_x + σ²_ε))
            z = (μ_x - μ*) / σ_tilde
            μ* = current best mean

        Args:
            candidate: SubsumptionCandidate to evaluate
            belief_state: Belief state (default: self.belief_state)

        Returns:
            KG value (higher = more valuable to verify)
        """
        belief = belief_state or self.belief_state
        key = self.candidate_key(candidate)

        # Get current belief
        mu_x, sigma2_x = belief.get_belief(key)
        mu_star = belief.current_best()

        # Measurement noise
        sigma2_eps = belief.measurement_noise

        # Compute σ_tilde (posterior variance reduction)
        sigma_tilde = np.sqrt(sigma2_x * sigma2_eps / (sigma2_x + sigma2_eps))

        if sigma_tilde < 1e-10:
            return 0.0  # No uncertainty to resolve

        # Compute z (normalized improvement potential)
        z = (mu_x - mu_star) / sigma_tilde

        # KG = σ_tilde * f(-|z|)
        # Using absolute value and negation per Frazier et al. (2009)
        kg_value = sigma_tilde * compute_kg_factor(-abs(z))

        # Apply discount factor
        kg_value *= self.discount_factor

        # Apply subsumption confidence as weight
        # Higher confidence subsumptions have lower uncertainty about outcome
        kg_value *= (1.0 - 0.5 * candidate.confidence)  # Confidence reduces KG

        return float(kg_value)

    def cost_adjusted_kg(
        self,
        candidate: SubsumptionCandidate,
        belief_state: BeliefState | None = None,
    ) -> float:
        """Compute cost-adjusted Knowledge Gradient.

        Returns KG / cost, representing value per unit measurement cost.

        Args:
            candidate: SubsumptionCandidate to evaluate
            belief_state: Belief state (default: self.belief_state)

        Returns:
            Cost-adjusted KG value
        """
        kg = self.compute_kg(candidate, belief_state)
        return kg / self.measurement_cost if self.measurement_cost > 0 else kg

    def should_verify(
        self,
        candidate: SubsumptionCandidate,
        belief_state: BeliefState | None = None,
    ) -> tuple[bool, float, str]:
        """Decide whether to verify a subsumption candidate.

        Returns True if:
        - research_mode is True (bypass cost threshold), OR
        - cost-adjusted KG exceeds 1.0 (value exceeds cost)

        Args:
            candidate: SubsumptionCandidate to evaluate
            belief_state: Belief state (default: self.belief_state)

        Returns:
            Tuple of (should_verify, kg_value, reason)
        """
        kg = self.compute_kg(candidate, belief_state)
        kg_adjusted = self.cost_adjusted_kg(candidate, belief_state)

        if self.research_mode:
            return True, kg, "research_mode"
        elif kg_adjusted >= 1.0:
            return True, kg, "kg_exceeds_cost"
        else:
            return False, kg, "kg_below_cost"

    def select_candidates(
        self,
        candidates: list[SubsumptionCandidate],
        budget: float | None = None,
        max_candidates: int | None = None,
    ) -> list[SubsumptionCandidate]:
        """Select candidates for verification using KG policy.

        Selects candidates in order of decreasing KG value until budget
        is exhausted or max_candidates reached.

        Args:
            candidates: List of candidates to consider
            budget: Total measurement budget (None = unlimited)
            max_candidates: Maximum candidates to select (None = unlimited)

        Returns:
            List of selected candidates, sorted by KG value
        """
        if not candidates:
            return []

        # Compute KG for each candidate
        scored = []
        for c in candidates:
            kg = self.compute_kg(c)
            should, _, reason = self.should_verify(c)
            scored.append({
                "candidate": c,
                "kg": kg,
                "should_verify": should,
                "reason": reason,
            })

        # Sort by KG descending
        scored.sort(key=lambda x: x["kg"], reverse=True)

        # Select within budget
        selected = []
        remaining_budget = budget if budget is not None else float("inf")

        for item in scored:
            if max_candidates is not None and len(selected) >= max_candidates:
                break

            if not item["should_verify"] and not self.research_mode:
                continue

            if remaining_budget >= self.measurement_cost:
                selected.append(item["candidate"])
                remaining_budget -= self.measurement_cost

        # Record selection for history
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "candidates_considered": len(candidates),
            "candidates_selected": len(selected),
            "research_mode": self.research_mode,
            "top_kg": scored[0]["kg"] if scored else 0.0,
        })

        logger.info(
            f"KG policy selected {len(selected)}/{len(candidates)} candidates "
            f"(research_mode={self.research_mode})"
        )

        return selected

    def update_from_measurement(
        self,
        candidate: SubsumptionCandidate,
        observed_improvement: float,
        observation_variance: float | None = None,
    ) -> tuple[float, float]:
        """Update belief state after measuring a candidate.

        Args:
            candidate: The verified candidate
            observed_improvement: Measured retrieval improvement (from SHAP)
            observation_variance: Variance of observation

        Returns:
            Tuple of (new_mean, new_variance) for the candidate
        """
        key = self.candidate_key(candidate)
        return self.belief_state.update(key, observed_improvement, observation_variance)

    def get_stats(self) -> dict:
        """Get policy statistics."""
        return {
            "measurement_cost": self.measurement_cost,
            "research_mode": self.research_mode,
            "discount_factor": self.discount_factor,
            "belief_state": self.belief_state.to_dict(),
            "history_length": len(self._history),
            "recent_selections": self._history[-5:] if self._history else [],
        }


@dataclass
class ConsolidationDecision:
    """Result of a KG-based consolidation decision.

    Attributes:
        candidate: The subsumption candidate
        kg_value: Computed Knowledge Gradient value
        cost_adjusted_kg: KG / measurement_cost
        should_verify: Whether to proceed with verification
        reason: Explanation for the decision
        timestamp: When decision was made
    """

    candidate: SubsumptionCandidate
    kg_value: float
    cost_adjusted_kg: float
    should_verify: bool
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "candidate": self.candidate.to_dict(),
            "kg_value": self.kg_value,
            "cost_adjusted_kg": self.cost_adjusted_kg,
            "should_verify": self.should_verify,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }
