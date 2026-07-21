"""Calcul partagé des expressions de planification Marvin."""

import re
from datetime import datetime, timedelta


DAY_OF_WEEK = {
    "sunday": 0, "dimanche": 0, "monday": 1, "lundi": 1,
    "tuesday": 2, "mardi": 2, "wednesday": 3, "mercredi": 3,
    "thursday": 4, "jeudi": 4, "friday": 5, "vendredi": 5,
    "saturday": 6, "samedi": 6,
}


def parse_schedule_seconds(schedule: str) -> int:
    value = schedule.lower().strip()
    match = re.match(r"every\s+(\d+)\s+(second|minute|hour|day)s?", value)
    if match:
        count, unit = int(match.group(1)), match.group(2)
        return count * {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]
    if value in ("every minute", "chaque minute"):
        return 60
    if value in ("every hour", "chaque heure"):
        return 3600
    if value in ("every day", "chaque jour"):
        return 86400
    match = re.match(r"\*/(\d+)\s+\*", value)
    if match:
        return int(match.group(1)) * 60
    if re.match(r"daily at (\d{1,2}):(\d{2})", value):
        return 86400
    return 60


def to_cron(schedule: str):
    value = schedule.lower().strip()
    if re.fullmatch(r"[\d*/,\-]+(\s+[\d*/,\-]+){4}", value):
        return value
    time_match = re.search(r"(?:at|à)\s+(\d{1,2})[:h](\d{2})", value)
    hour, minute = (
        (int(time_match.group(1)), int(time_match.group(2)))
        if time_match
        else (9, 0)
    )
    if "weekday" in value or "semaine" in value or "ouvré" in value:
        return f"{minute} {hour} * * 1-5"
    if "weekend" in value or "week-end" in value:
        return f"{minute} {hour} * * 0,6"
    monthly = re.search(r"monthly.*day\s+(\d{1,2})|mensuel.*(\d{1,2})", value)
    if monthly:
        day = monthly.group(1) or monthly.group(2)
        return f"{minute} {hour} {day} * *"
    for name, day_of_week in DAY_OF_WEEK.items():
        if name in value:
            return f"{minute} {hour} * * {day_of_week}"
    if ("daily" in value or "chaque jour" in value or "tous les jours" in value) and time_match:
        return f"{minute} {hour} * * *"
    if time_match and (
        "every day" in value
        or "daily" in value
        or not any(marker in value for marker in ("every", "chaque"))
    ):
        return f"{minute} {hour} * * *"
    return None


def next_run_datetime(schedule: str) -> str:
    now = datetime.now()
    cron = to_cron(schedule)
    if cron:
        try:
            from croniter import croniter

            return croniter(cron, now).get_next(datetime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return (now + timedelta(seconds=parse_schedule_seconds(schedule))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
