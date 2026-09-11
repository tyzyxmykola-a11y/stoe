"""Trusted task observations; counts are command checks, never guessed test cases."""
from dataclasses import dataclass, field
import time


@dataclass
class TaskEvidence:
    task_id: str
    observer_before: str
    started: float = field(default_factory=time.monotonic)
    selected_roles: list = field(default_factory=list)
    disabled_roles: list = field(default_factory=list)
    model_calls: int = 0
    model_metrics: list = field(default_factory=list)
    tool_steps: int = 0
    checks: list = field(default_factory=list)
    files: list = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    binary_files: int = 0
    review: str | None = None
    commit: str | None = None
    push: str | None = None

    def snapshot(self, outcome, observer_after, failure=''):
        def tokens(key):
            values = [m.get(key) for m in self.model_metrics if isinstance(m.get(key), int)]
            return sum(values) if values else None
        return {
            'task_id': self.task_id, 'outcome': outcome,
            'duration_seconds': round(time.monotonic() - self.started, 3),
            'observer_before': self.observer_before, 'observer_after': observer_after,
            'selected_roles': [{k: r[k] for k in ('name','model_mode','resolved_model','digest')} for r in self.selected_roles],
            'disabled_roles': self.disabled_roles, 'model_calls': self.model_calls,
            'prompt_tokens': tokens('prompt_tokens'), 'output_tokens': tokens('output_tokens'),
            'token_metrics_calls': len(self.model_metrics), 'tool_steps': self.tool_steps,
            'files_changed': self.files, 'diff_additions': self.additions, 'diff_deletions': self.deletions,
            'binary_files': self.binary_files, 'checks_passed': sum(c['passed'] for c in self.checks),
            'checks_failed': sum(not c['passed'] for c in self.checks), 'checks': self.checks,
            'review_verdict': self.review, 'commit': self.commit, 'push': self.push,
            'failure_condition': failure,
        }
