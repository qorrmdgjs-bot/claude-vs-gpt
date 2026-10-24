"""Pure decision rules. Evidence supplied here is simulated, not trusted real evidence."""
from dataclasses import dataclass, field, asdict
from hashlib import sha256
import json
import math
from typing import List


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class Contract:
    goal: str
    criteria: tuple
    checks: tuple
    max_seconds: int = 14400
    review_seconds: int = 3600
    max_stalled: int = 3
    publish: str = "never"

    def __post_init__(self):
        if not self.goal.strip() or not self.criteria or not self.checks:
            raise ValueError("Goal, criteria and required checks must be nonempty")
        for values in (self.criteria, self.checks):
            if any(not isinstance(x, str) or not x.strip() for x in values):
                raise ValueError("Identifiers must be nonempty strings")
            if len(set(values)) != len(values):
                raise ValueError("Identifiers must be unique")
        if (self.max_seconds, self.review_seconds, self.max_stalled, self.publish) != (14400, 3600, 3, "never"):
            raise ValueError("This prototype uses the agreed fixed limits and never publishes")

    @property
    def fingerprint(self):
        return digest(asdict(self))


@dataclass
class Evidence:
    snapshot: str
    review_snapshot: str
    audit_snapshot: str
    passed_checks: List[str] = field(default_factory=list)
    met_criteria: List[str] = field(default_factory=list)
    resolved_findings: List[str] = field(default_factory=list)
    review: str = "changes_requested"
    audit: str = "continue"
    blocking_findings: List[str] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)


@dataclass
class Run:
    run_id: str
    contract_hash: str
    started: float
    deadline: float
    last_now: float
    state: str = "IMPLEMENTING"
    reason: str = "started"
    cycle: int = 0
    stalled: int = 0
    seen_progress: List[str] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)
    events: list = field(default_factory=list)

    @classmethod
    def start(cls, run_id, contract, now):
        if not math.isfinite(now):
            raise ValueError("Invalid clock")
        return cls(run_id, contract.fingerprint, now, now + contract.max_seconds, now)

    def stop(self, reason):
        self.state, self.reason, self.instructions = "STOPPED", reason, []

    def guard(self, contract, now):
        if contract.fingerprint != self.contract_hash:
            self.stop("contract_changed")
        elif not math.isfinite(now) or now < self.last_now:
            self.stop("clock_invalid")
        elif now >= self.deadline:
            self.stop("time_limit")
        self.last_now = max(self.last_now, now) if math.isfinite(now) else self.last_now
        return self.state != "STOPPED"

    def decide(self, contract, evidence, now):
        if self.state in ("STOPPED", "COMPLETED"):
            raise ValueError("Terminal run requires explicit resume")
        if not self.guard(contract, now):
            return
        self.cycle += 1
        e = evidence
        self.events.append({"cycle": self.cycle, "snapshot": e.snapshot, "at": now})
        if not e.snapshot or not (e.snapshot == e.review_snapshot == e.audit_snapshot):
            self.stop("stale_evidence")
            return
        if (e.review not in ("pass", "changes_requested", "inconclusive")
                or e.audit not in ("continue", "complete", "stop")):
            self.stop("invalid_result")
            return
        if not set(e.passed_checks) <= set(contract.checks) or not set(e.met_criteria) <= set(contract.criteria):
            self.stop("unknown_evidence")
            return
        if e.review == "inconclusive" or e.audit == "stop":
            self.stop("review_or_audit_stop")
            return
        complete = (set(e.passed_checks) == set(contract.checks)
                    and set(e.met_criteria) == set(contract.criteria)
                    and not e.blocking_findings and e.review == "pass" and e.audit == "complete")
        if complete:
            self.state, self.reason, self.instructions = "COMPLETED", "all_evidence_passed", []
            return
        # Stable finding IDs are supplied by the fake fixture. Semantic matching is not implemented.
        progress = set(["criterion:" + x for x in e.met_criteria]
                       + ["check:" + x for x in e.passed_checks]
                       + ["finding:" + x for x in e.resolved_findings])
        fresh = progress - set(self.seen_progress)
        self.seen_progress = sorted(set(self.seen_progress) | progress)
        self.stalled = 0 if fresh else self.stalled + 1
        if self.stalled >= contract.max_stalled:
            self.stop("no_progress")
        elif not 1 <= len(e.instructions) <= 2 or any(not x.strip() for x in e.instructions):
            self.stop("invalid_instructions")
        else:
            self.state, self.reason = "IMPLEMENTING", "next_instructions"
            self.instructions = list(e.instructions)

    def resume(self, contract, now, approved=False, cause_resolved=False):
        if self.state != "STOPPED" or not approved or not cause_resolved:
            raise ValueError("Resume requires a stopped run, approval and resolved cause")
        reason = self.reason
        self.state = "PREPARING"
        if not self.guard(contract, now):
            return
        if reason in ("time_limit", "contract_changed", "clock_invalid"):
            self.stop(reason)
            return
        # Explicit resume rechecks evidence; it never reuses a prior approval.
        self.state, self.reason = "CHECKING", "resume_requires_revalidation"


def review_due(started, now, instruction_done=False):
    return instruction_done or now - started >= 3600
