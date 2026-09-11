"""Скилл-бандлы /jarvis (skill-bundles/jarvis.{macos,windows,linux}.yaml):
каждая ОС ссылается только на существующие скиллы этой же ОС (не путает mac-control/win-control/linux-control
и Apple-специфичные навыки из другого бандла).
"""

from __future__ import annotations

import yaml

from conftest import ROOT

BUNDLES = ROOT / "skill-bundles"

# skills/<name>/SKILL.md регистрируется по имени каталога (jarvis-core автосканирует свою папку skills/);
# также существуют кроссплатформенные навыки из корневого skills/ (frontmatter name: jarvis-*) и jarvis-brain/skills/.
_CROSS_PLATFORM = {
    "morning-briefing", "brain-usage", "brain-nightly-review", "web-tasks",
    "jarvis-briefing", "jarvis-voice-etiquette", "jarvis-research-brief", "jarvis-home-automation",
}
_PLATFORM_ONLY = {
    "macos": {"mac-control", "apple-notes", "apple-reminders", "imessage"},
    "windows": {"win-control"},
    "linux": {"linux-control"},
}
# Встроенные в сам Hermes Agent навыки (не SKILL.md этого репозитория) — см. docs/SOURCES.md.
_HERMES_BUILTIN_SKILLS = {"apple-notes", "apple-reminders", "imessage", "findmy"}


def _load(os_name: str) -> dict:
    return yaml.safe_load((BUNDLES / f"jarvis.{os_name}.yaml").read_text(encoding="utf-8"))


def test_all_three_bundles_exist_and_parse():
    for os_name in ("macos", "windows", "linux"):
        b = _load(os_name)
        assert b["name"] == "jarvis"
        assert isinstance(b.get("skills"), list) and b["skills"]
        assert b.get("instruction", "").strip()


def test_bundles_reference_only_own_platform_control_skill():
    """Windows-бандл не должен тянуть mac-control/linux-control, и т.д."""
    others = {"macos": {"win-control", "linux-control"}, "windows": {"mac-control", "linux-control"},
              "linux": {"mac-control", "win-control"}}
    for os_name in ("macos", "windows", "linux"):
        skills = set(_load(os_name)["skills"])
        forbidden = skills & others[os_name]
        assert not forbidden, f"{os_name}: бандл ссылается на чужие control-скиллы: {forbidden}"
        assert skills & _PLATFORM_ONLY[os_name], f"{os_name}: бандл не содержит своего control-скилла"


def test_windows_and_linux_bundles_do_not_reference_apple_only_skills():
    apple_only = {"apple-notes", "apple-reminders", "imessage", "mac-control"}
    for os_name in ("windows", "linux"):
        skills = set(_load(os_name)["skills"])
        assert not (skills & apple_only), f"{os_name}: бандл ссылается на Apple-специфичные навыки: {skills & apple_only}"


def test_bundles_only_reference_known_skill_names():
    known = set()
    for base in (ROOT / "skills", ROOT / "plugins" / "jarvis-core" / "skills", ROOT / "plugins" / "jarvis-brain" / "skills"):
        if base.exists():
            for child in base.iterdir():
                if (child / "SKILL.md").exists():
                    fm = (child / "SKILL.md").read_text(encoding="utf-8")
                    for line in fm.splitlines():
                        if line.startswith("name:"):
                            known.add(line.split(":", 1)[1].strip())
                            break
    known |= _HERMES_BUILTIN_SKILLS
    for os_name in ("macos", "windows", "linux"):
        skills = set(_load(os_name)["skills"])
        unknown = skills - known
        assert not unknown, f"{os_name}: бандл ссылается на несуществующие скиллы: {unknown} (известны: {sorted(known)})"
