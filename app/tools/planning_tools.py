"""
Planning tools.

- ``extract_meeting_actions`` (LLM, read/compute) — structured extraction from meeting notes.
- ``generate_work_plan`` (deterministic) — rule-based day plan; model decisions kept out of scheduling.
- ``detect_overdue_tasks`` (deterministic, bonus) — find overdue work + a recommendation.
- ``draft_follow_up_email`` (LLM, bonus, write/simulated) — draft an email; approval-gated.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.database.models import Priority, Status, TaskFilter
from app.tools.registry import ToolContext, ToolError, register_tool
from app.tools.task_tools import TaskSummary

# Heuristics (documented so they're defensible in code review — there is no effort field on tasks).
PRIORITY_WEIGHT = {Priority.CRITICAL: 4, Priority.HIGH: 3, Priority.MEDIUM: 2, Priority.LOW: 1}
PRIORITY_HOURS = {Priority.CRITICAL: 3.0, Priority.HIGH: 2.5, Priority.MEDIUM: 1.5, Priority.LOW: 1.0}
ACTIVE_STATUSES = {Status.PENDING, Status.IN_PROGRESS, Status.BLOCKED}


# =================================================== extract_meeting_actions
class ActionItem(BaseModel):
    description: str = Field(..., description="The concrete action to take.")
    owner: str | None = Field(None, description="Person responsible, if named.")
    deadline: str | None = Field(None, description="Deadline if stated (free text is fine).")


class ExtractMeetingActionsInput(BaseModel):
    meeting_notes: str = Field(..., min_length=1, description="Raw meeting notes or transcript.")


class ExtractMeetingActionsOutput(BaseModel):
    summary: str
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


_EXTRACT_SYSTEM = (
    "You extract structured information from meeting notes. Read the notes and produce: a short "
    "summary; the decisions that were made; the concrete action items (with owner and deadline only "
    "if explicitly stated — never invent them); and any unresolved/open questions. Do not fabricate "
    "details that are not present in the notes."
)


@register_tool(
    name="extract_meeting_actions",
    description=(
        "Analyze meeting notes or a transcript and return a STRUCTURED breakdown: summary, "
        "decisions, action items (with owners/deadlines when stated), and unresolved questions. Use "
        "when the user pastes notes and wants them organized or wants action items identified. "
        "READ/COMPUTE only — it does NOT create tasks. To turn the action items into tasks, call "
        "create_task afterwards (which requires approval)."
    ),
    input_model=ExtractMeetingActionsInput,
    output_model=ExtractMeetingActionsOutput,
    is_write=False,
    requires_approval=False,
)
def extract_meeting_actions(
    inp: ExtractMeetingActionsInput, ctx: ToolContext
) -> ExtractMeetingActionsOutput:
    if ctx.llm is None:
        raise ToolError("Meeting extraction needs the language model, which is unavailable.")
    return ctx.llm.structured(_EXTRACT_SYSTEM, inp.meeting_notes, ExtractMeetingActionsOutput)


# ======================================================= generate_work_plan
class ScheduledItem(BaseModel):
    task_id: str
    title: str
    priority: Priority
    status: Status
    due_date: date | None = None
    est_hours: float
    reason: str


class GenerateWorkPlanInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    available_hours: float = Field(8.0, gt=0, le=24, description="Hours available to work today.")
    # Named plan_date internally (avoids shadowing the `date` type); accepts "date" as the arg name.
    plan_date: date | None = Field(None, alias="date", description="Plan date (defaults to today).")
    user_priorities: list[str] = Field(
        default_factory=list, description="Optional focus hints (keywords/tags to prioritize)."
    )


class GenerateWorkPlanOutput(BaseModel):
    plan_date: date
    ordered_schedule: list[ScheduledItem]
    focus_areas: list[str]
    deferred_tasks: list[TaskSummary]
    risk_warnings: list[str]
    total_scheduled_hours: float


@register_tool(
    name="generate_work_plan",
    description=(
        "Build an ordered day plan from the user's active tasks, fitting them into the available "
        "hours. Ranks by priority and deadline urgency (overdue first), estimates effort, and lists "
        "what to defer plus risk warnings. Use for 'plan my day', 'what should I work on with 6 "
        "hours'. READ/COMPUTE only; no approval needed. Scheduling is deterministic — not left to the model."
    ),
    input_model=GenerateWorkPlanInput,
    output_model=GenerateWorkPlanOutput,
    is_write=False,
    requires_approval=False,
)
def generate_work_plan(inp: GenerateWorkPlanInput, ctx: ToolContext) -> GenerateWorkPlanOutput:
    as_of = inp.plan_date or date.today()
    hints = [h.lower() for h in inp.user_priorities]
    tasks = [t for t in ctx.repo.list_tasks(TaskFilter(limit=500)) if t.status in ACTIVE_STATUSES]

    def urgency(t) -> tuple[float, str]:
        if t.due_date is None:
            return 0.0, "no due date"
        days = (t.due_date - as_of).days
        if days < 0:
            return 15.0 + abs(days), f"overdue by {abs(days)} day(s)"
        if days == 0:
            return 12.0, "due today"
        return max(0.0, 10.0 - days), f"due in {days} day(s)"

    scored = []
    for t in tasks:
        u_score, u_reason = urgency(t)
        focus = 5.0 if any(h in t.title.lower() or h in [x.lower() for x in t.tags] for h in hints) else 0.0
        blocked_penalty = 5.0 if t.status == Status.BLOCKED else 0.0
        score = PRIORITY_WEIGHT[t.priority] * 10 + u_score + focus - blocked_penalty
        scored.append((score, u_reason, t))

    # Highest score first; break ties by earliest due date (None last).
    scored.sort(key=lambda x: (-x[0], x[2].due_date or date.max))

    schedule: list[ScheduledItem] = []
    deferred: list[TaskSummary] = []
    warnings: list[str] = []
    used = 0.0

    for score, u_reason, t in scored:
        if t.status == Status.BLOCKED:
            warnings.append(f"'{t.title}' is Blocked and cannot be worked on until unblocked.")
            continue
        est = PRIORITY_HOURS[t.priority]
        if used + est <= inp.available_hours:
            reason = f"{t.priority.value} priority; {u_reason}"
            schedule.append(
                ScheduledItem(
                    task_id=str(t.id), title=t.title, priority=t.priority, status=t.status,
                    due_date=t.due_date, est_hours=est, reason=reason,
                )
            )
            used += est
            if t.due_date and t.due_date < as_of:
                warnings.append(f"'{t.title}' is overdue (was due {t.due_date}).")
        else:
            deferred.append(TaskSummary.from_task(t))
            if t.priority == Priority.CRITICAL:
                warnings.append(f"Critical task '{t.title}' did not fit in {inp.available_hours}h.")

    if used > inp.available_hours:  # defensive; greedy fill prevents this
        warnings.append("Scheduled hours exceed available hours.")

    focus_areas = [tag for tag, _ in Counter(tag for s in schedule for tag in
                   next((t.tags for t in tasks if str(t.id) == s.task_id), [])).most_common(3)]

    return GenerateWorkPlanOutput(
        plan_date=as_of,
        ordered_schedule=schedule,
        focus_areas=focus_areas,
        deferred_tasks=deferred,
        risk_warnings=list(dict.fromkeys(warnings)),  # de-dupe, keep order
        total_scheduled_hours=round(used, 2),
    )


# ==================================================== detect_overdue_tasks
class DetectOverdueInput(BaseModel):
    as_of: date | None = Field(None, description="Reference date (defaults to today).")


class OverdueTaskItem(BaseModel):
    task_id: str
    title: str
    priority: Priority
    status: Status
    due_date: date
    days_overdue: int


class DetectOverdueOutput(BaseModel):
    overdue_tasks: list[OverdueTaskItem]
    count: int
    recommendation: str


@register_tool(
    name="detect_overdue_tasks",
    description=(
        "Find all active tasks whose due date has passed, sorted by how overdue and how important "
        "they are, and recommend what to tackle first. Use for 'what's overdue', 'am I behind on "
        "anything'. READ-ONLY; no approval needed."
    ),
    input_model=DetectOverdueInput,
    output_model=DetectOverdueOutput,
    is_write=False,
    requires_approval=False,
)
def detect_overdue_tasks(inp: DetectOverdueInput, ctx: ToolContext) -> DetectOverdueOutput:
    as_of = inp.as_of or date.today()
    tasks = ctx.repo.list_tasks(TaskFilter(limit=500))
    overdue = [
        t for t in tasks
        if t.due_date and t.due_date < as_of and t.status in ACTIVE_STATUSES
    ]
    overdue.sort(key=lambda t: ((as_of - t.due_date).days, PRIORITY_WEIGHT[t.priority]), reverse=True)
    items = [
        OverdueTaskItem(
            task_id=str(t.id), title=t.title, priority=t.priority, status=t.status,
            due_date=t.due_date, days_overdue=(as_of - t.due_date).days,
        )
        for t in overdue
    ]
    if items:
        top = items[0]
        rec = (
            f"Start with '{top.title}' — {top.priority.value} priority and "
            f"{top.days_overdue} day(s) overdue."
        )
    else:
        rec = "Nothing is overdue. You're on track."
    return DetectOverdueOutput(overdue_tasks=items, count=len(items), recommendation=rec)


# =================================================== draft_follow_up_email
class _EmailDraft(BaseModel):
    """Internal schema the LLM fills."""

    subject: str
    body: str


class DraftFollowUpEmailInput(BaseModel):
    context: str = Field(..., min_length=1, description="Meeting notes/summary to base the email on.")
    recipient: str | None = Field(None, description="Recipient name or email, if known.")
    tone: str = Field("professional", description="Desired tone, e.g. professional, friendly.")


class DraftFollowUpEmailOutput(BaseModel):
    to: str | None
    subject: str
    body: str
    note: str


@register_tool(
    name="draft_follow_up_email",
    description=(
        "Draft a follow-up email based on meeting notes or a summary, in the requested tone. Returns "
        "a subject and body for review. Use for 'draft a follow-up email from these notes'. This is "
        "a WRITE/irreversible-style action (a message to be sent) and requires approval; sending is "
        "SIMULATED — the email is never actually delivered."
    ),
    input_model=DraftFollowUpEmailInput,
    output_model=DraftFollowUpEmailOutput,
    is_write=True,
    requires_approval=True,
)
def draft_follow_up_email(
    inp: DraftFollowUpEmailInput, ctx: ToolContext
) -> DraftFollowUpEmailOutput:
    if ctx.llm is None:
        raise ToolError("Drafting an email needs the language model, which is unavailable.")
    system = (
        f"You write concise, {inp.tone} follow-up emails. Given meeting context, produce a clear "
        "subject line and a short email body with next steps. Do not invent facts beyond the context."
    )
    user = inp.context if not inp.recipient else f"Recipient: {inp.recipient}\n\n{inp.context}"
    draft = ctx.llm.structured(system, user, _EmailDraft)
    return DraftFollowUpEmailOutput(
        to=inp.recipient,
        subject=draft.subject,
        body=draft.body,
        note="Simulated draft — not actually sent. Review before sending.",
    )
