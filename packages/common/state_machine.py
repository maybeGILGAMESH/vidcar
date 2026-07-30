"""Strict processing state transitions used by every control-plane service."""
from packages.contracts.models import JobState


class InvalidTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.created: frozenset({JobState.uploading, JobState.cancelled}),
    JobState.uploading: frozenset({JobState.uploaded, JobState.cancelled, JobState.failed_retryable}),
    JobState.uploaded: frozenset({JobState.queued, JobState.cancelled}),
    JobState.queued: frozenset({JobState.claimed, JobState.cancelled, JobState.failed_retryable}),
    JobState.claimed: frozenset({JobState.processing, JobState.queued, JobState.failed_retryable}),
    JobState.processing: frozenset(
        {JobState.uploading_results, JobState.failed_retryable, JobState.failed_terminal}
    ),
    JobState.uploading_results: frozenset(
        {JobState.awaiting_finalize, JobState.failed_retryable, JobState.failed_terminal}
    ),
    JobState.awaiting_finalize: frozenset(
        {JobState.completed, JobState.failed_retryable, JobState.failed_terminal}
    ),
    JobState.failed_retryable: frozenset({JobState.queued, JobState.cancelled, JobState.failed_terminal}),
    JobState.completed: frozenset(),
    JobState.failed_terminal: frozenset(),
    JobState.cancelled: frozenset(),
}


def validate_transition(current: JobState | str, target: JobState | str) -> JobState:
    current_state, target_state = JobState(current), JobState(target)
    if target_state not in ALLOWED_TRANSITIONS[current_state]:
        raise InvalidTransition(f"invalid state transition: {current_state.value} -> {target_state.value}")
    return target_state
