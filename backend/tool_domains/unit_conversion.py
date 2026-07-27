"""Conversions d'unités déterministes fondées sur des facteurs explicites."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from math import isfinite
from typing import Any


_MAX_ABS_VALUE = Decimal("1e100")
_TEMPERATURE_UNITS = frozenset(
    {"c", "celsius", "°c", "f", "fahrenheit", "°f", "k", "kelvin"}
)


def _aliases(
    target: dict[str, tuple[Decimal, str]],
    names: str,
    factor: str,
    dimension: str,
) -> None:
    value = Decimal(factor)
    for name in names.split("|"):
        target[name] = (value, dimension)


_UNITS: dict[str, tuple[Decimal, str]] = {}
_aliases(_UNITS, "m|metre|meter|metres|meters", "1", "m")
_aliases(_UNITS, "km|kilometre|kilometer", "1000", "m")
_aliases(_UNITS, "cm|centimetre|centimeter", "0.01", "m")
_aliases(_UNITS, "mm|millimetre|millimeter", "0.001", "m")
_aliases(_UNITS, "mile|miles|mi", "1609.344", "m")
_aliases(_UNITS, "yard|yards|yd", "0.9144", "m")
_aliases(_UNITS, "foot|feet|ft", "0.3048", "m")
_aliases(_UNITS, "inch|inches|in", "0.0254", "m")
_aliases(_UNITS, "nm|nanometre", "1e-9", "m")
_aliases(_UNITS, "au", "149597870700", "m")
_aliases(_UNITS, "ly", "9460730472580800", "m")

_aliases(_UNITS, "kg|kilogram|kilogramme", "1", "kg")
_aliases(_UNITS, "g|gram|gramme", "0.001", "kg")
_aliases(_UNITS, "mg|milligram", "1e-6", "kg")
_aliases(_UNITS, "tonne|t", "1000", "kg")
_aliases(_UNITS, "lb|pound|pounds|lbs", "0.45359237", "kg")
_aliases(_UNITS, "oz|ounce|ounces", "0.028349523125", "kg")
_aliases(_UNITS, "stone", "6.35029318", "kg")

_aliases(_UNITS, "l|litre|liter|litres|liters", "1", "L")
_aliases(_UNITS, "ml|millilitre|milliliter", "0.001", "L")
_aliases(_UNITS, "cl|centilitre", "0.01", "L")
_aliases(_UNITS, "dl|decilitre", "0.1", "L")
_aliases(_UNITS, "m3|m³", "1000", "L")
_aliases(_UNITS, "gallon|gallons|gal", "3.785411784", "L")
_aliases(_UNITS, "pint|pints|pt", "0.473176473", "L")
_aliases(_UNITS, "fl oz", "0.0295735295625", "L")

_aliases(_UNITS, "m/s|ms", "1", "m/s")
_aliases(_UNITS, "km/h|kmh|kph", "0.2777777777777777777777777778", "m/s")
_aliases(_UNITS, "mph", "0.44704", "m/s")
_aliases(_UNITS, "knot|knots|kt", "0.5144444444444444444444444444", "m/s")

_aliases(_UNITS, "m2|m²", "1", "m²")
_aliases(_UNITS, "km2|km²", "1e6", "m²")
_aliases(_UNITS, "cm2|cm²", "1e-4", "m²")
_aliases(_UNITS, "ha|hectare", "1e4", "m²")
_aliases(_UNITS, "acre|acres", "4046.8564224", "m²")
_aliases(_UNITS, "ft2|sqft", "0.09290304", "m²")

_aliases(_UNITS, "j|joule|joules", "1", "J")
_aliases(_UNITS, "kj|kilojoule", "1000", "J")
_aliases(_UNITS, "cal|calorie", "4.184", "J")
_aliases(_UNITS, "kcal|kilocalorie", "4184", "J")
_aliases(_UNITS, "kwh", "3.6e6", "J")
_aliases(_UNITS, "wh", "3600", "J")
_aliases(_UNITS, "ev", "1.602176634e-19", "J")

# Compatibilité historique : "b" désigne ici un octet, comme avant l'extraction.
_aliases(_UNITS, "b|byte|bytes", "1", "o")
_aliases(_UNITS, "ko|kb|kilobyte", "1000", "o")
_aliases(_UNITS, "mo|mb|megabyte", "1e6", "o")
_aliases(_UNITS, "go|gb|gigabyte", "1e9", "o")
_aliases(_UNITS, "to|tb|terabyte", "1e12", "o")
_aliases(_UNITS, "kib", "1024", "o")
_aliases(_UNITS, "mib", "1048576", "o")
_aliases(_UNITS, "gib", "1073741824", "o")


def _decimal_value(value: object) -> tuple[Decimal | None, str | None]:
    if value is None or isinstance(value, bool):
        return None, "Paramètre 'value' requis et numérique."
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, f"Valeur numérique invalide : {value!r}."
    if not parsed.is_finite():
        return None, "La valeur doit être finie."
    if abs(parsed) > _MAX_ABS_VALUE:
        return None, "La valeur dépasse la limite de 1e100."
    return parsed, None


def _to_celsius(value: Decimal, unit: str) -> Decimal:
    if unit in {"c", "celsius", "°c"}:
        result = value
    elif unit in {"f", "fahrenheit", "°f"}:
        result = (value - Decimal(32)) * Decimal(5) / Decimal(9)
    elif unit in {"k", "kelvin"}:
        result = value - Decimal("273.15")
    else:
        raise ValueError(f"Unité de température inconnue : {unit}.")
    if result < Decimal("-273.15"):
        raise ValueError("Température inférieure au zéro absolu.")
    return result


def _from_celsius(value: Decimal, unit: str) -> Decimal:
    if unit in {"c", "celsius", "°c"}:
        return value
    if unit in {"f", "fahrenheit", "°f"}:
        return value * Decimal(9) / Decimal(5) + Decimal(32)
    if unit in {"k", "kelvin"}:
        return value + Decimal("273.15")
    raise ValueError(f"Unité de température inconnue : {unit}.")


def _public_number(value: Decimal, digits: int) -> float:
    raw = float(value)
    number = raw if value and abs(value) < Decimal(f"1e-{digits}") else round(raw, digits)
    if not isfinite(number):
        raise OverflowError
    return number


async def unit_convert(args: dict[str, Any]) -> dict[str, Any]:
    """Convertit une valeur entre deux unités compatibles."""
    value, error = _decimal_value(args.get("value"))
    if error or value is None:
        return {"error": error or "Valeur invalide."}
    from_unit = str(args.get("from_unit") or "").strip().lower()
    to_unit = str(args.get("to_unit") or "").strip().lower()
    if not from_unit:
        return {"error": "Paramètre 'from_unit' requis."}
    if not to_unit:
        return {"error": "Paramètre 'to_unit' requis."}
    if len(from_unit) > 64 or len(to_unit) > 64:
        return {"error": "Nom d'unité limité à 64 caractères."}

    with localcontext() as context:
        context.prec = 40
        if from_unit in _TEMPERATURE_UNITS or to_unit in _TEMPERATURE_UNITS:
            if from_unit not in _TEMPERATURE_UNITS or to_unit not in _TEMPERATURE_UNITS:
                return {
                    "error": f"Unités incompatibles : '{from_unit}' et '{to_unit}'."
                }
            try:
                result = _from_celsius(_to_celsius(value, from_unit), to_unit)
                public_result = _public_number(result, 6)
            except (ValueError, OverflowError) as exc:
                return {"error": str(exc) or "Résultat hors limites."}
            return {
                "success": True,
                "value": float(value),
                "from_unit": from_unit,
                "to_unit": to_unit,
                "result": public_result,
                "formatted": f"{float(value):g} {from_unit} = {float(result):.6g} {to_unit}",
            }

        if from_unit not in _UNITS:
            return {
                "error": (
                    f"Unité source inconnue : '{from_unit}'. "
                    "Exemples : m, km, kg, lb, L, °C, km/h."
                )
            }
        if to_unit not in _UNITS:
            return {"error": f"Unité destination inconnue : '{to_unit}'."}
        from_factor, from_dimension = _UNITS[from_unit]
        to_factor, to_dimension = _UNITS[to_unit]
        if from_dimension != to_dimension:
            return {
                "error": (
                    f"Unités incompatibles : '{from_unit}' ({from_dimension}) "
                    f"≠ '{to_unit}' ({to_dimension})."
                )
            }
        result = value * from_factor / to_factor
        try:
            public_result = _public_number(result, 9)
        except OverflowError:
            return {"error": "Le résultat dépasse les limites numériques prises en charge."}
        return {
            "success": True,
            "value": float(value),
            "from_unit": from_unit,
            "to_unit": to_unit,
            "result": public_result,
            "formatted": f"{float(value):g} {from_unit} = {float(result):.6g} {to_unit}",
        }
