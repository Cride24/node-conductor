"""Internal action failures with explicit dispatch certainty."""


class ActionExecutionError(Exception):
    """A sanitized infrastructure failure; raw adapter errors never escape."""

    def __init__(self, result_code: str, *, dispatched: bool, uncertain: bool) -> None:
        super().__init__(result_code)
        self.result_code = result_code
        self.dispatched = dispatched
        self.uncertain = uncertain


class ActionNotDispatchedError(ActionExecutionError):
    def __init__(self, result_code: str = "dispatch_not_started") -> None:
        super().__init__(result_code, dispatched=False, uncertain=False)


class ActionConfirmedFailure(ActionExecutionError):
    def __init__(self, result_code: str = "infrastructure_action_failed") -> None:
        super().__init__(result_code, dispatched=True, uncertain=False)


class ActionIndeterminateError(ActionExecutionError):
    def __init__(self, result_code: str = "infrastructure_result_unknown") -> None:
        super().__init__(result_code, dispatched=True, uncertain=True)
