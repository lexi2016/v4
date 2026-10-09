"""Public admission entry after manager_plan.load_owner pins the original owner."""

def rejection_reason(daily, date, context, current):
    from v4.manager_research.mapping_plan_admission import rejection_reason as check
    return check(daily, date, context, current)
