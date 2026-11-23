"""Account material units; calculations and saved recipes remain in grams/ml."""
GRAMS_PER_OUNCE = 28.349523125
ML_PER_US_FL_OUNCE = 29.5735295625


def units_for_country(country):
    # US customary fluid ounces are deliberately distinct from UK fluid ounces.
    return "US" if str(country).strip().upper() in {"US", "PR", "GU", "VI", "AS", "MP"} else "METRIC"


def current_units():
    try:
        from .environment import get_addon_preferences
        return getattr(get_addon_preferences(), "material_units", "METRIC")
    except ImportError:
        return "METRIC"


def unit_factor(kind, units=None):
    if (units or current_units()) != "US":
        return 1.0
    return {"mass": GRAMS_PER_OUNCE, "volume": ML_PER_US_FL_OUNCE,
            "density": GRAMS_PER_OUNCE / ML_PER_US_FL_OUNCE}[kind]


def unit_label(kind, units=None):
    us = (units or current_units()) == "US"
    return {"mass": "oz" if us else "g", "volume": "US fl oz" if us else "ml",
            "density": "oz/US fl oz" if us else "g/ml"}[kind]


def format_amount(value, kind, units=None):
    amount = value / unit_factor(kind, units)
    return f"{amount:.2f} {unit_label(kind, units)}" if (units or current_units()) == "US" else f"{amount:.0f} {unit_label(kind, units)}"


def display_getter(property_name, kind):
    def get(scene):
        return getattr(scene, property_name) / unit_factor(kind)
    return get


def display_setter(property_name, kind):
    def set(scene, value):
        setattr(scene, property_name, value * unit_factor(kind))
    return set
