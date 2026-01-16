"""Evidence storage bridge for KB domain.

This module bridges the KB domain to the HX evidence capture infrastructure.
Evidence is stored in Iceberg via hx://rase.evidence for consistency with
the rest of the HX data lake.

The HX evidence module handles:
- Iceberg table creation and schema management
- MinIO storage backend
- Retry logic for failed writes
- KB thin manifests

This module provides domain-specific helpers:
- Converting VerificationResult to EvidenceRecord
- Extracting constraint summaries
- Computing document hashes
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from gaius.hx.evidence import (
    EvidenceCapture,
    EvidenceRecord,
    EvidenceWriteResult,
    get_evidence_capture,
)
from gaius.rase.core.vm import VerificationResult
from gaius.rase.traceability import DigitalThread


def create_evidence_record(
    objective_name: str,
    domain: str,
    result: VerificationResult,
    thread: DigitalThread,
    document_path: str | None = None,
    document_content: str | None = None,
    duration_ms: int | None = None,
) -> EvidenceRecord:
    """Create an EvidenceRecord from verification result.

    This is the bridge between RASE verification and HX evidence storage.

    Args:
        objective_name: Name of the verified objective
        domain: Verification domain (kb, nifi, etc.)
        result: Verification result from oracle
        thread: Digital thread for lineage
        document_path: Path to verified document
        document_content: Document content for hashing
        duration_ms: Verification duration

    Returns:
        EvidenceRecord ready for capture
    """
    # Extract constraint results
    constraint_results = []
    for cr in result.constraint_results:
        constraint_results.append({
            "name": cr.constraint_name,
            "satisfied": cr.satisfied,
            "message": cr.message,
        })

    # Compute document hash if content provided
    document_hash = None
    if document_content:
        document_hash = hashlib.sha256(document_content.encode("utf-8")).hexdigest()

    # Build thread data
    thread_data = {
        "thread_id": str(thread.thread_id),
        "requirement_id": str(thread.requirement_id),
        "verification_case_id": str(thread.verification_case_id) if thread.verification_case_id else None,
        "verification_result_id": str(thread.verification_result_id) if thread.verification_result_id else None,
        "reward_outcome": thread.reward_outcome,
    }

    return EvidenceRecord(
        objective_name=objective_name,
        domain=domain,
        verdict=result.verdict.value,
        accuracy=result.accuracy,
        reward=result.to_reward(),
        gates_total=len(result.constraint_results),
        gates_passed=sum(1 for cr in result.constraint_results if cr.satisfied),
        constraint_results=constraint_results,
        thread_id=str(thread.thread_id),
        document_path=document_path,
        document_hash=document_hash,
        thread_data=thread_data,
        duration_ms=duration_ms,
        is_training_eligible=True,  # KB domain is always training-eligible
    )


async def capture_verification_evidence(
    objective_name: str,
    result: VerificationResult,
    thread: DigitalThread,
    document_path: str | None = None,
    document_content: str | None = None,
    duration_ms: int | None = None,
) -> EvidenceWriteResult:
    """Capture verification evidence to HX.

    This is the main entry point for storing KB verification evidence.
    Uses the singleton EvidenceCapture for consistent configuration.

    Args:
        objective_name: Name of the verified objective
        result: Verification result from oracle
        thread: Digital thread for lineage
        document_path: Path to verified document
        document_content: Document content for hashing
        duration_ms: Verification duration

    Returns:
        EvidenceWriteResult with status
    """
    record = create_evidence_record(
        objective_name=objective_name,
        domain="kb",
        result=result,
        thread=thread,
        document_path=document_path,
        document_content=document_content,
        duration_ms=duration_ms,
    )

    capture = get_evidence_capture()
    return await capture.capture(record)


__all__ = [
    "create_evidence_record",
    "capture_verification_evidence",
    # Re-export from HX
    "EvidenceCapture",
    "EvidenceRecord",
    "EvidenceWriteResult",
    "get_evidence_capture",
]
