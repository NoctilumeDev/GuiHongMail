"""Compatibility rules for retained collector summary schemas."""


def is_completed(summary):
    states = {summary[name] for name in ('execution_status', 'execution') if name in summary}
    return states == {'COMPLETED'}
