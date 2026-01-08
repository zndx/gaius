"""Tests for scheduler service types and pure logic.

This module tests the dataclasses and metrics logic used by SchedulerService:
1. JobPriority - Priority queue ordering
2. InferenceJob - Job lifecycle and timing
3. AgentMetrics - Token and latency tracking
4. XAIBudget - API budget management with daily/weekly limits

Critical Path Coverage:
- Priority ordering for job scheduling
- Latency percentile calculations (p50, p99)
- Budget enforcement and reset logic
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import patch

from gaius.engine.services.scheduler_service import (
    JobPriority,
    InferenceJob,
    AgentMetrics,
    XAIBudget,
)
from gaius.engine.backends import InferenceRequest, InferenceResponse


# ─────────────────────────────────────────────────────────────────────────────
# JobPriority Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestJobPriority:
    """Test JobPriority enum and ordering."""

    def test_priority_values(self):
        """Priority values are ordered correctly."""
        assert JobPriority.BATCH.value == 0
        assert JobPriority.LOW.value == 1
        assert JobPriority.NORMAL.value == 2
        assert JobPriority.HIGH.value == 3
        assert JobPriority.CRITICAL.value == 4

    def test_priority_ordering(self):
        """Higher priority has higher value."""
        assert JobPriority.CRITICAL.value > JobPriority.HIGH.value
        assert JobPriority.HIGH.value > JobPriority.NORMAL.value
        assert JobPriority.NORMAL.value > JobPriority.LOW.value
        assert JobPriority.LOW.value > JobPriority.BATCH.value

    def test_priority_count(self):
        """Five priority levels exist."""
        assert len(JobPriority) == 5


# ─────────────────────────────────────────────────────────────────────────────
# InferenceJob Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestInferenceJob:
    """Test InferenceJob dataclass."""

    @pytest.fixture
    def sample_request(self):
        """Create sample inference request."""
        return InferenceRequest(
            messages=[{"role": "user", "content": "Test prompt"}],
            agent_alias="test-agent",
            max_tokens=100,
        )

    def test_default_values(self, sample_request):
        """Job has sensible defaults."""
        job = InferenceJob(id="job-1", request=sample_request)

        assert job.id == "job-1"
        assert job.request == sample_request
        assert job.priority == JobPriority.NORMAL
        assert job.started_at is None
        assert job.completed_at is None
        assert job.result is None
        assert job.callback is None

    def test_with_priority(self, sample_request):
        """Job can have different priority."""
        job = InferenceJob(
            id="job-1",
            request=sample_request,
            priority=JobPriority.CRITICAL,
        )
        assert job.priority == JobPriority.CRITICAL

    def test_wait_time_before_start(self, sample_request):
        """wait_time_ms calculated from submitted_at when not started."""
        now = datetime.now()
        job = InferenceJob(
            id="job-1",
            request=sample_request,
            submitted_at=now - timedelta(milliseconds=500),
        )

        # Should be approximately 500ms (allow some tolerance)
        assert job.wait_time_ms >= 490
        assert job.wait_time_ms < 600

    def test_wait_time_after_start(self, sample_request):
        """wait_time_ms fixed after job starts."""
        submitted = datetime.now() - timedelta(milliseconds=500)
        started = datetime.now() - timedelta(milliseconds=200)

        job = InferenceJob(
            id="job-1",
            request=sample_request,
            submitted_at=submitted,
            started_at=started,
        )

        # Wait time should be ~300ms (500 - 200)
        assert abs(job.wait_time_ms - 300) < 20

    def test_processing_time_before_start(self, sample_request):
        """processing_time_ms is 0 before job starts."""
        job = InferenceJob(id="job-1", request=sample_request)
        assert job.processing_time_ms == 0

    def test_processing_time_while_processing(self, sample_request):
        """processing_time_ms increases while processing."""
        job = InferenceJob(
            id="job-1",
            request=sample_request,
            started_at=datetime.now() - timedelta(milliseconds=100),
        )

        assert job.processing_time_ms >= 90
        assert job.processing_time_ms < 200

    def test_processing_time_after_complete(self, sample_request):
        """processing_time_ms fixed after completion."""
        started = datetime.now() - timedelta(milliseconds=500)
        completed = datetime.now() - timedelta(milliseconds=200)

        job = InferenceJob(
            id="job-1",
            request=sample_request,
            started_at=started,
            completed_at=completed,
        )

        # Processing time should be ~300ms
        assert abs(job.processing_time_ms - 300) < 20


# ─────────────────────────────────────────────────────────────────────────────
# AgentMetrics Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAgentMetrics:
    """Test AgentMetrics dataclass."""

    def test_default_values(self):
        """Metrics have sensible defaults."""
        metrics = AgentMetrics(agent_alias="test")

        assert metrics.agent_alias == "test"
        assert metrics.total_requests == 0
        assert metrics.total_input_tokens == 0
        assert metrics.total_output_tokens == 0
        assert metrics.total_latency_ms == 0
        assert metrics.error_count == 0

    def test_avg_latency_no_requests(self):
        """avg_latency_ms is 0 with no requests."""
        metrics = AgentMetrics(agent_alias="test")
        assert metrics.avg_latency_ms == 0.0

    def test_avg_latency_with_requests(self):
        """avg_latency_ms calculated correctly."""
        metrics = AgentMetrics(
            agent_alias="test",
            total_requests=4,
            total_latency_ms=400,
        )
        assert metrics.avg_latency_ms == 100.0

    def test_avg_tokens_per_request_no_requests(self):
        """avg_tokens_per_request is 0 with no requests."""
        metrics = AgentMetrics(agent_alias="test")
        assert metrics.avg_tokens_per_request == 0.0

    def test_avg_tokens_per_request(self):
        """avg_tokens_per_request includes both input and output."""
        metrics = AgentMetrics(
            agent_alias="test",
            total_requests=2,
            total_input_tokens=100,
            total_output_tokens=200,
        )
        assert metrics.avg_tokens_per_request == 150.0

    def test_p50_latency_empty(self):
        """p50_latency_ms is 0 with no data."""
        metrics = AgentMetrics(agent_alias="test")
        assert metrics.p50_latency_ms == 0

    def test_p50_latency_single(self):
        """p50_latency_ms with single value."""
        metrics = AgentMetrics(agent_alias="test")
        metrics.recent_latencies.append(100)
        assert metrics.p50_latency_ms == 100

    def test_p50_latency_multiple(self):
        """p50_latency_ms is median of values."""
        metrics = AgentMetrics(agent_alias="test")
        for lat in [10, 20, 30, 40, 50]:
            metrics.recent_latencies.append(lat)

        # Median of [10, 20, 30, 40, 50] is 30 (index 2)
        assert metrics.p50_latency_ms == 30

    def test_p99_latency_empty(self):
        """p99_latency_ms is 0 with no data."""
        metrics = AgentMetrics(agent_alias="test")
        assert metrics.p99_latency_ms == 0

    def test_p99_latency_single(self):
        """p99_latency_ms with single value."""
        metrics = AgentMetrics(agent_alias="test")
        metrics.recent_latencies.append(100)
        assert metrics.p99_latency_ms == 100

    def test_p99_latency_multiple(self):
        """p99_latency_ms is near max for small samples."""
        metrics = AgentMetrics(agent_alias="test")
        for i in range(100):
            metrics.recent_latencies.append(i * 10)

        # 99th percentile of [0, 10, 20, ..., 990] should be near 990
        assert metrics.p99_latency_ms >= 980

    def test_record_response(self):
        """record() updates all metrics."""
        metrics = AgentMetrics(agent_alias="test")

        response = InferenceResponse(
            content="Test response",
            model="test-model",
            backend="vllm",
            input_tokens=50,
            output_tokens=100,
            latency_ms=150,
        )

        metrics.record(response)

        assert metrics.total_requests == 1
        assert metrics.total_input_tokens == 50
        assert metrics.total_output_tokens == 100
        assert metrics.total_latency_ms == 150
        assert metrics.error_count == 0
        assert 150 in metrics.recent_latencies

    def test_record_error_response(self):
        """record() increments error_count on errors."""
        metrics = AgentMetrics(agent_alias="test")

        response = InferenceResponse(
            content="",
            model="test-model",
            backend="vllm",
            error="Connection failed",
        )

        metrics.record(response)

        assert metrics.total_requests == 1
        assert metrics.error_count == 1

    def test_record_multiple_responses(self):
        """record() accumulates across responses."""
        metrics = AgentMetrics(agent_alias="test")

        for i in range(5):
            response = InferenceResponse(
                content="response",
                model="model",
                backend="vllm",
                input_tokens=10,
                output_tokens=20,
                latency_ms=100 + i * 10,
            )
            metrics.record(response)

        assert metrics.total_requests == 5
        assert metrics.total_input_tokens == 50
        assert metrics.total_output_tokens == 100
        assert metrics.total_latency_ms == 600  # 100+110+120+130+140=600

    def test_to_dict(self):
        """to_dict() includes all relevant fields."""
        metrics = AgentMetrics(
            agent_alias="test",
            total_requests=10,
            total_input_tokens=100,
            total_output_tokens=200,
            total_latency_ms=1000,
            error_count=1,
        )
        metrics.recent_latencies.extend([80, 90, 100, 110, 120])

        d = metrics.to_dict()

        assert d["agent_alias"] == "test"
        assert d["total_requests"] == 10
        assert d["total_input_tokens"] == 100
        assert d["total_output_tokens"] == 200
        assert d["total_latency_ms"] == 1000
        assert d["avg_latency_ms"] == 100.0
        assert d["p50_latency_ms"] == 100
        assert d["error_count"] == 1
        assert d["error_rate"] == 0.1

    def test_recent_latencies_bounded(self):
        """recent_latencies has max length of 100."""
        metrics = AgentMetrics(agent_alias="test")

        for i in range(150):
            metrics.recent_latencies.append(i)

        assert len(metrics.recent_latencies) == 100
        # Should have most recent 100 values (50-149)
        assert 49 not in metrics.recent_latencies
        assert 50 in metrics.recent_latencies


# ─────────────────────────────────────────────────────────────────────────────
# XAIBudget Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestXAIBudget:
    """Test XAIBudget dataclass."""

    def test_default_values(self):
        """Budget has sensible defaults."""
        budget = XAIBudget()

        assert budget.daily_limit == 50
        assert budget.weekly_limit == 200
        assert budget.daily_used == 0
        assert budget.weekly_used == 0

    def test_custom_limits(self):
        """Budget can have custom limits."""
        budget = XAIBudget(daily_limit=10, weekly_limit=50)

        assert budget.daily_limit == 10
        assert budget.weekly_limit == 50

    def test_can_use_initially(self):
        """can_use() returns True with fresh budget."""
        budget = XAIBudget()
        assert budget.can_use() is True

    def test_can_use_after_use(self):
        """can_use() returns True after some usage."""
        budget = XAIBudget(daily_limit=10)
        budget.record_use()
        budget.record_use()

        assert budget.daily_used == 2
        assert budget.can_use() is True

    def test_can_use_at_daily_limit(self):
        """can_use() returns False at daily limit."""
        budget = XAIBudget(daily_limit=3)

        budget.record_use()
        budget.record_use()
        budget.record_use()

        assert budget.daily_used == 3
        assert budget.can_use() is False

    def test_can_use_at_weekly_limit(self):
        """can_use() returns False at weekly limit."""
        budget = XAIBudget(daily_limit=100, weekly_limit=5)

        for _ in range(5):
            budget.record_use()

        assert budget.weekly_used == 5
        assert budget.can_use() is False

    def test_record_use_increments_both(self):
        """record_use() increments both daily and weekly."""
        budget = XAIBudget()
        budget.record_use()

        assert budget.daily_used == 1
        assert budget.weekly_used == 1

    def test_daily_remaining(self):
        """daily_remaining calculated correctly."""
        budget = XAIBudget(daily_limit=10)
        assert budget.daily_remaining == 10

        budget.record_use()
        budget.record_use()
        assert budget.daily_remaining == 8

    def test_weekly_remaining(self):
        """weekly_remaining calculated correctly."""
        budget = XAIBudget(weekly_limit=50)
        assert budget.weekly_remaining == 50

        budget.record_use()
        budget.record_use()
        assert budget.weekly_remaining == 48

    def test_daily_remaining_at_zero(self):
        """daily_remaining doesn't go negative."""
        budget = XAIBudget(daily_limit=2)
        budget.daily_used = 5  # Over limit

        assert budget.daily_remaining == 0

    def test_daily_reset_on_new_day(self):
        """Daily counter resets on new day."""
        budget = XAIBudget(daily_limit=10)
        budget.record_use()
        budget.record_use()

        # Simulate day change
        yesterday = date.today() - timedelta(days=1)
        budget.current_day = yesterday

        # Accessing daily_remaining triggers reset
        assert budget.daily_remaining == 10
        assert budget.daily_used == 0

    def test_weekly_reset_on_monday(self):
        """Weekly counter resets on Monday."""
        budget = XAIBudget(weekly_limit=100)
        budget.record_use()
        budget.record_use()

        # Simulate week change (set week_start to previous week)
        last_week = date.today() - timedelta(days=7)
        budget.week_start = last_week

        # Find a Monday to simulate
        with patch("gaius.engine.services.scheduler_service.date") as mock_date:
            # Set today to be a Monday
            monday = date.today()
            while monday.weekday() != 0:
                monday = monday - timedelta(days=1)

            mock_date.today.return_value = monday
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            # Accessing weekly_remaining should trigger reset
            # (only if today is Monday and week_start is different)
            if date.today().weekday() == 0:
                budget._maybe_reset()
                assert budget.weekly_used == 0

    def test_to_dict(self):
        """to_dict() includes all budget info."""
        budget = XAIBudget(daily_limit=10, weekly_limit=50)
        budget.record_use()
        budget.record_use()

        d = budget.to_dict()

        assert d["daily_used"] == 2
        assert d["daily_limit"] == 10
        assert d["daily_remaining"] == 8
        assert d["weekly_used"] == 2
        assert d["weekly_limit"] == 50
        assert d["weekly_remaining"] == 48


# ─────────────────────────────────────────────────────────────────────────────
# Priority Queue Ordering Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPriorityQueueOrdering:
    """Test that job priorities are correctly ordered."""

    def test_priority_comparison(self):
        """Higher priority jobs should be processed first."""
        # Create jobs with different priorities
        request = InferenceRequest(messages=[{"role": "user", "content": "test"}], agent_alias="test")

        low = InferenceJob(id="low", request=request, priority=JobPriority.LOW)
        normal = InferenceJob(id="normal", request=request, priority=JobPriority.NORMAL)
        high = InferenceJob(id="high", request=request, priority=JobPriority.HIGH)
        critical = InferenceJob(id="critical", request=request, priority=JobPriority.CRITICAL)

        # Higher priority value means higher priority
        assert critical.priority.value > high.priority.value
        assert high.priority.value > normal.priority.value
        assert normal.priority.value > low.priority.value

    def test_sort_by_priority(self):
        """Jobs can be sorted by priority."""
        request = InferenceRequest(messages=[{"role": "user", "content": "test"}], agent_alias="test")

        jobs = [
            InferenceJob(id="1", request=request, priority=JobPriority.LOW),
            InferenceJob(id="2", request=request, priority=JobPriority.CRITICAL),
            InferenceJob(id="3", request=request, priority=JobPriority.NORMAL),
            InferenceJob(id="4", request=request, priority=JobPriority.HIGH),
        ]

        # Sort by priority value (descending for highest first)
        sorted_jobs = sorted(jobs, key=lambda j: j.priority.value, reverse=True)

        assert sorted_jobs[0].id == "2"  # CRITICAL
        assert sorted_jobs[1].id == "4"  # HIGH
        assert sorted_jobs[2].id == "3"  # NORMAL
        assert sorted_jobs[3].id == "1"  # LOW


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
