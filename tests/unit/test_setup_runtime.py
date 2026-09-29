"""Node/npm preflight must prevent expensive setup on unsupported runtimes."""

import pytest

from scripts import setup_project


@pytest.mark.parametrize("version,accepted", [
    ("v20.18.0", False), ("v20.19.0", True),
    ("v21.7.0", False), ("v22.11.0", False),
    ("v22.12.0", True), ("v24.0.0", True),
])
def test_node_preflight_checks_version_even_when_node_is_on_path(monkeypatch, version, accepted):
    monkeypatch.setattr(setup_project.shutil, "which", lambda name: "C:/Tools/nodejs/" + name)
    monkeypatch.setattr(setup_project.subprocess, "check_output", lambda *args, **kwargs: version)
    if accepted:
        setup_project._ensure_node_path()
    else:
        with pytest.raises(RuntimeError, match="Node.js 20.19"):
            setup_project._ensure_node_path()
