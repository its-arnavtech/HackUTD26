"""Recovery policy based on bank evidence, never on model-invented references.

These are suggestions for the customer's checklist. No banking write or other
protective action is performed here. Full transaction details stay app-side.
"""

from app.contracts import Action, AgentInput, AgentMode, AgentResult


def finish_recovery(result: AgentResult, agent_input: AgentInput, refs: list[str]) -> AgentResult:
    if agent_input.mode != AgentMode.recovery:
        return result.model_copy(update={"was_this_you": []})
    verified = list(dict.fromkeys(refs)) if agent_input.customer_context.linked_bank else []
    actions = (
        [Action.freeze_card, Action.call_number_on_card, Action.change_password]
        if verified
        else [Action.change_password, Action.open_official_app, Action.call_number_on_card]
    )
    return result.model_copy(update={"was_this_you": verified, "actions": actions, "replan": True})
