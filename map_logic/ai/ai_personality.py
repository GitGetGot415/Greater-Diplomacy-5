"""Per-nation temperament, so two countries in the same position play differently.

Every AI nation used to reason identically: the same strength thresholds, the
same willingness to declare war, the same answer to every proposal. Two
neighbours with the same borders and the same army made the same choices, every
game, forever.

Traits are procedural and deterministic -- the same scenario always produces the
same personalities -- so a game is reproducible and a player can learn that a
particular neighbour is not to be trusted. A scenario can override any of them
per nation, and the editor can pin them outright.

None of this needs the LLM. It is read by ai_opinion's war desire, by the
proposal verdicts, and by whether a nation honours a commitment it made.

Stdlib and `data` only, so it imports under Pyodide.
"""

import hashlib

import data.constants as c
from data.number_utils import clamp_float

#: All 0.0-1.0. Kept deliberately few: each one has to earn its keep by being
#: read somewhere that visibly changes play.
TRAITS = ("aggression", "ambition", "caution", "loyalty", "trust")

#: What a trait means where it is read:
#:   aggression -- baseline appetite for war, independent of the odds
#:   ambition   -- pursuit of land it has no claim to yet
#:   caution    -- how much of an edge it wants before committing
#:   loyalty    -- weight on faction obligations and its own past promises
#:   trust      -- how far it lets relations, rather than power, decide

#: Traits present but not overridden by anything are regenerated on load; these
#: sources are respected as authored and never recomputed.
AUTHORED_SOURCES = ("scenario", "editor")

_DEFAULT = 0.5


def _trait_from(digest_bytes):
    """Maps four bytes to 0.0-1.0, weighted toward the middle.

    The average of two uniforms rather than one, so most nations come out
    moderate and the outliers are rare enough to be memorable. A flat
    distribution gives a map where a third of everyone is a fanatic.
    """
    first = int.from_bytes(digest_bytes[:2], "big") / 65535.0
    second = int.from_bytes(digest_bytes[2:4], "big") / 65535.0
    return round((first + second) / 2.0, 4)


def procedural(nation_name, scenario_seed):
    """The traits this nation gets when nobody has authored any.

    hashlib, never hash(): Python salts hash() on str per process unless
    PYTHONHASHSEED is set, so a hash()-based seeder would hand the same save
    different personalities on every launch. That is the single easiest way to
    get this feature quietly wrong.
    """
    digest = hashlib.sha256(f"{scenario_seed}|{nation_name}".encode("utf-8")).digest()
    return {trait: _trait_from(digest[i * 4:(i + 1) * 4]) for i, trait in enumerate(TRAITS)}


def scenario_seed(scenario_settings):
    """The seed personalities are derived from, created and stored on first use.

    Stored rather than derived fresh each time so that editing a scenario later
    -- renaming a country, moving a border -- does not silently reroll everyone's
    temperament in a save already in progress.
    """
    if scenario_settings is None:
        return c.DEFAULT_AI_PERSONALITY_SEED
    seed = scenario_settings.get("ai_personality_seed")
    if not seed:
        seed = c.DEFAULT_AI_PERSONALITY_SEED
        scenario_settings["ai_personality_seed"] = seed
    return seed


def get(nation_data, nation_name, scenario_settings=None):
    """This nation's traits, seeded and stored on first ask.

    Resolution order, highest first:
      1. traits already stored with an authored source -- a scenario or the
         editor said so, and nothing regenerates those
      2. scenario_settings["ai_personality_overrides"][nation], merged over the
         procedural values so a scenario can set just `aggression` and leave the
         rest alone
      3. procedural

    Persisting on first access means an old save with no personalities gets them
    once, deterministically, and identically on every later load.
    """
    block = nation_data.setdefault(nation_name, {})
    existing = block.get("personality")
    if isinstance(existing, dict) and existing.get("_source") in AUTHORED_SOURCES:
        return existing

    seed = scenario_seed(scenario_settings)
    traits = procedural(nation_name, seed)
    source = "procedural"

    overrides = (scenario_settings or {}).get("ai_personality_overrides", {})
    nation_overrides = overrides.get(nation_name)
    if isinstance(nation_overrides, dict):
        for trait, value in nation_overrides.items():
            if trait in TRAITS:
                traits[trait] = clamp_float(value, 0.0, 1.0, _DEFAULT)
        source = "scenario"

    traits["_seed"] = seed
    traits["_source"] = source
    block["personality"] = traits
    return traits


def trait(nation_data, nation_name, name, scenario_settings=None):
    """One trait, defaulting to the midpoint for anything unrecognised."""
    return clamp_float(get(nation_data, nation_name, scenario_settings).get(name, _DEFAULT),
                       0.0, 1.0, _DEFAULT)


def set_authored(nation_data, nation_name, traits, source="editor"):
    """Pins traits so nothing regenerates them. Used by the scenario editor."""
    block = nation_data.setdefault(nation_name, {})
    stored = {t: clamp_float(traits.get(t, _DEFAULT), 0.0, 1.0, _DEFAULT) for t in TRAITS}
    stored["_source"] = source if source in AUTHORED_SOURCES else "editor"
    stored["_seed"] = block.get("personality", {}).get("_seed", "")
    block["personality"] = stored
    return stored


def describe(nation_data, nation_name, scenario_settings=None):
    """A short human phrase for the traits that stand out, for prompts and UI."""
    traits = get(nation_data, nation_name, scenario_settings)
    words = []
    for name, low, high in (("aggression", "peaceable", "belligerent"),
                            ("ambition", "content", "expansionist"),
                            ("caution", "reckless", "cautious"),
                            ("loyalty", "faithless", "loyal"),
                            ("trust", "suspicious", "trusting")):
        value = clamp_float(traits.get(name, _DEFAULT), 0.0, 1.0, _DEFAULT)
        if value >= c.AI_TRAIT_NOTABLE_HIGH:
            words.append(high)
        elif value <= c.AI_TRAIT_NOTABLE_LOW:
            words.append(low)
    return ", ".join(words) if words else "unremarkable"
