"""Harnais E7 autonome; ce paquet ne doit jamais importer le runtime Marvin."""

from .pilot_fixtures import PILOT_FIXTURES, build_pilot_plans

__all__ = ["PILOT_FIXTURES", "build_pilot_plans"]
