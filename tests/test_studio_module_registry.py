"""Individual registry acceptance for the 15 declared Studio modules.

Passing this file proves discoverability and catalog consistency only. It does
not prove that a module has a complete UI workflow or physical-device E2E.
"""
import pytest

from app.production_catalog import production_catalog
from app.studio_scope import STUDIO_MODULES, scope_summary


MODULES = tuple(STUDIO_MODULES)


@pytest.mark.parametrize("module_name", MODULES, ids=MODULES)
def test_each_studio_module_is_exposed_consistently(module_name):
    catalog = production_catalog()
    scope = scope_summary()

    assert catalog["studio_modules"].count(module_name) == 1
    assert scope["studio_modules"].count(module_name) == 1
    assert scope["studio_module_count"] == 15
    assert catalog["version"] >= 2
    assert catalog["pipeline"]
    assert catalog["agent_registry"]["checker_total"] > 0


def test_studio_module_registry_has_exactly_fifteen_unique_names():
    assert len(MODULES) == 15
    assert len(set(MODULES)) == 15
    assert all(isinstance(name, str) and name.strip() for name in MODULES)
