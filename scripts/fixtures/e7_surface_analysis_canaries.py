"""Canaris statiques : ce module n'est jamais importé par l'analyseur."""


def sqlite_only(note_id: str) -> None:
    import database as db

    db.delete_note(note_id)


def pure_function(value: int) -> int:
    return value + 1


def dynamic_dispatch(name: str, payload: dict) -> object:
    return globals()[name](payload)
