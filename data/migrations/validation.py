"""Read known saved fields, repairing local saves and checking player input.

Recovery keeps valid entries and unknown extension fields. Unreadable optional
values use empty defaults; malformed individual entries are dropped. Multiplayer
commands still use strict readers before the host applies permission checks.
"""

import math


def expect(value, kind, path):
    if not isinstance(value, kind):
        label = {dict: "an object", list: "a list", str: "text"}[kind]
        received = "null" if value is None else type(value).__name__
        raise ValueError(f"{path}: expected {label}; received {received}.")
    return value


def repaired(path):
    print(f"[WARN] Repaired malformed saved field: {path}.")


def container(record, field, kind, path, *, repair=False):
    value = record.get(field, kind())
    if repair and not isinstance(value, kind):
        value = record[field] = kind()
        repaired(f"{path}.{field}")
    return expect(value, kind, f"{path}.{field}")


def records(record, field, path, *, repair=False):
    values = container(record, field, list, path, repair=repair)
    if repair and any(not isinstance(value, dict) for value in values):
        values[:] = [value for value in values if isinstance(value, dict)]
        repaired(f"{path}.{field}")
    for index, value in enumerate(values):
        entry_path = f"{path}.{field}[{index}]"
        yield expect(value, dict, entry_path), entry_path


def text_fields(record, fields, path, *, repair=False):
    for field in fields:
        if field not in record:
            continue
        if repair and not isinstance(record[field], str):
            del record[field]
            repaired(f"{path}.{field}")
        else:
            expect(record[field], str, f"{path}.{field}")


def number(value, path):
    # Integers are finite without converting arbitrarily large JSON integers to float.
    if type(value) is not int and not (type(value) is float and math.isfinite(value)):
        raise ValueError(f"{path}: expected a finite number.")
    return value


def numeric_fields(record, fields, path, *, repair=False):
    for field in fields:
        if field not in record:
            continue
        field_path = f"{path}.{field}"
        if not repair:
            number(record[field], field_path)
            continue
        value = record[field]
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = None
        try:
            value = number(value, field_path)
        except ValueError:
            del record[field]
            repaired(field_path)
        else:
            if type(value) is not type(record[field]) or value != record[field]:
                record[field] = value
                repaired(field_path)


def research_country(country, path, *, repair=True):
    """Recover research containers for saves; reject malformed player submissions.

    Equipment levels and research_years retain their existing recovery policies.
    current_research allows null to mean no active technology.
    """
    container(country, "research", dict, path, repair=repair)
    progress = container(country, "research_progress", dict, path, repair=repair)
    numeric_fields(progress, list(progress), path + ".research_progress", repair=repair)
    if country.get("current_research") is not None:
        text_fields(country, ("current_research",), path, repair=repair)
    projects = list(records(country, "research_queue", path, repair=repair))
    for project, project_path in projects:
        text_fields(project, ("tech_name",), project_path, repair=repair)
        had_points = "points_remaining" in project
        numeric_fields(project, ("points_remaining", "days_remaining"), project_path, repair=repair)
        if repair and had_points and "points_remaining" not in project and "days_remaining" not in project:
            remaining = progress.get(project.get("tech_name"))
            if remaining is not None:
                project["points_remaining"] = remaining
            else:
                country["research_queue"].remove(project)
                repaired(project_path)
                continue
        if repair and not project.get("tech_name"):
            country["research_queue"].remove(project)
            repaired(project_path)
