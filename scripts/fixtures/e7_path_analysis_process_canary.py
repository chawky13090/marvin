"""Canari prospectif supplementaire distinguant observation et mutation psutil."""

import psutil


def observe_process(pid: int) -> tuple[bool, float | None]:
    if not psutil.pid_exists(pid):
        return False, None
    return True, psutil.Process(pid).create_time()


def mutate_process(pid: int) -> None:
    psutil.Process(pid).terminate()
