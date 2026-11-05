"""Malformed known fields shared by save, history, and tournament regression cases."""


def malformed_records():
    """Yield (field path, country fields, province fields) without real tuning data."""
    for field in ("research", "research_progress", "research_queue", "custom_production_units",
                  "pending_diplomacy", "volunteer_missions", "inbox", "scripted_events"):
        for value in (None, 7):
            yield field, {field: value}, {}
    yield "current_research", {"current_research": []}, {}
    yield "research_queue[0]", {"research_queue": [None]}, {}
    yield "research_queue[0].tech_name", {"research_queue": [{"tech_name": []}]}, {}
    for value in (None, True, float("inf"), "7"):
        yield "research_progress.fixture", {"research_progress": {"fixture": value}}, {}
        yield "research_queue[0].points_remaining", {"research_queue": [{"points_remaining": value}]}, {}
    yield "custom_production_units[0]", {"custom_production_units": [[]]}, {}
    yield "scripted_events[0].conditions", {"scripted_events": [{"conditions": None}]}, {}
    yield "volunteer_missions.fixture", {"volunteer_missions": {"fixture": []}}, {}
    yield "volunteer_missions.fixture.held_units[0].unit", {
        "volunteer_missions": {"fixture": {"held_units": [{"unit": None}]}}}, {}
    for field in ("units", "building_queue", "unit_queue", "deployment_queue", "buildings"):
        for value in (None, 7):
            yield field, {}, {field: value}
    yield "units[0]", {}, {"units": [None]}
    yield "units[0].unit_id", {}, {"units": [{"unit_id": []}]}
    yield "units[0].type", {}, {"units": [{"type": []}]}
    yield "units[0].health", {}, {"units": [{"health": "bad"}]}
    yield "units[0].order", {}, {"units": [{"order": []}]}
    yield "units[0].air_cargo[0]", {}, {"units": [{"air_cargo": [None]}]}
    yield "building_queue[0]", {}, {"building_queue": [None]}
    for value in ([], {}, None):
        yield "building_queue[0].item_name", {}, {"building_queue": [{"item_name": value}]}
    yield "building_queue[0].refund", {}, {"building_queue": [{"refund": []}]}
    yield "building_queue[0].refund.cost_materials", {}, {"building_queue": [{"refund": {"cost_materials": "bad"}}]}
    yield "unit_queue[0].unit_type", {}, {"unit_queue": [{"unit_type": []}]}
    yield "unit_queue[0].turns_remaining", {}, {"unit_queue": [{"turns_remaining": float("nan")}]}
