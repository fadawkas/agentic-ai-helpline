from enum import StrEnum


class CallState(StrEnum):
    CONNECTING = "CONNECTING"
    ACTIVE = "ACTIVE"
    ENDING = "ENDING"
    ENDED = "ENDED"


_ALLOWED_TRANSITIONS = {
    CallState.CONNECTING: {CallState.ACTIVE, CallState.ENDING},
    CallState.ACTIVE: {CallState.ENDING},
    CallState.ENDING: {CallState.ENDED},
    CallState.ENDED: set(),
}


def transition_call_state(current: CallState, target: CallState) -> CallState:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid call transition: {current} -> {target}")
    return target
