"""Dutch sentences for the template writer (and the fallback once a model writes).

All user-facing wording lives here, so another language is another file like this one.
"""

from __future__ import annotations

from datetime import datetime

MONTHS = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
          "september", "oktober", "november", "december"]
WEEKDAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]

GREETING = {
    "morning": "Goeiemorgen {name}.",
    "midday": "Goeiemiddag {name}.",
    "afternoon": "Goeienamiddag {name}.",
    "evening": "Goeienavond {name}.",
}

T = {
    "agenda.missing": "Je agenda is nog niet gekoppeld. Plak je iCal-adres bij de instellingen.",
    "agenda.stale": "Je agenda kon niet ververst worden. Dit is de versie van {when}.",
    "agenda.partial": "Je agenda {names} kon niet gelezen worden. Wat erin staat, ontbreekt hier.",
    "agenda.empty_today": "Vandaag staat er niets in je agenda. De dag is van jou.",
    "agenda.first_far": "Je eerste afspraak is pas over {duration}. Tot dan is je agenda vrij.",
    "agenda.next_far": "Je volgende afspraak is pas over {duration}. Tot dan is je agenda vrij.",
    "agenda.first_near": "Je eerste afspraak begint over {duration}: {title}.",
    "agenda.next_near": "Je volgende afspraak begint over {duration}: {title}.",
    "agenda.now": "Je zit nu in {title}, tot {end}.",
    "agenda.count_today": "Vandaag {count} afspraken, de laatste eindigt om {end}.",
    "agenda.all_day": "Ook vandaag: {titles}.",
    "agenda.done": "Je afspraken van vandaag zitten erop.",
    "agenda.rest_empty": "Je agenda is leeg voor de rest van de dag.",
    "agenda.remaining_one": "Nog één afspraak vandaag: {title}, tot {end}.",
    "agenda.remaining_many": "Nog {count} afspraken vandaag, de laatste eindigt om {end}.",
    "agenda.free_block": "Je langste vrije blok loopt van {start} tot {end}.",
    "agenda.tomorrow_empty": "Morgen staat er niets in je agenda.",
    "agenda.tomorrow_first": "Morgen begint met {title} om {start}.",
    "agenda.tomorrow_busy": "Het wordt een volle dag: {count} afspraken.",
}


def join_names(names: list[str]) -> str:
    """['Werk'] -> '“Werk”', ['Werk', 'Sport'] -> '“Werk” en “Sport”'."""
    quoted = [f"“{name}”" for name in names]
    if len(quoted) <= 1:
        return "".join(quoted)
    return ", ".join(quoted[:-1]) + " en " + quoted[-1]


def clock(moment: datetime) -> str:
    """13:30 -> '13u30', 9:00 -> '9u'."""
    return f"{moment.hour}u{moment.minute:02d}" if moment.minute else f"{moment.hour}u"


def duration(minutes: int) -> str:
    """50 -> '50 minuten', 60 -> '1 uur', 350 -> '5u50'."""
    if minutes < 60:
        return "1 minuut" if minutes == 1 else f"{minutes} minuten"
    hours, rest = divmod(minutes, 60)
    return f"{hours}u{rest:02d}" if rest else f"{hours} uur"


def long_date(moment: datetime) -> str:
    """'maandag 16 november'."""
    return f"{WEEKDAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}"


def short_when(moment: datetime, now: datetime) -> str:
    """'6u30' for today, '15 november, 21u' for another day."""
    if moment.date() == now.date():
        return clock(moment)
    return f"{moment.day} {MONTHS[moment.month - 1]}, {clock(moment)}"
