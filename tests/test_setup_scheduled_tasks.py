"""
Регрессионные тесты для scripts/setup_scheduled_tasks.py — до этого файл не был покрыт
тестами вовсе, из-за чего невалидный Task Scheduler XML (отсутствовала обёртка
<Principals> вокруг <Principal>) попал в прод и был обнаружен только на реальной
машине пользователя ("XML-файл имеет неверное содержание... Отсутствует узел",
(7,5):Principal — 7-я строка, 5-й столбец, ровно на элементе <Principal>).

schtasks.exe в этой песочнице недоступен, поэтому мы не можем вызвать реальный
`schtasks /Create /XML`, но можем и должны валидировать сам XML через стандартный
xml.etree, чтобы структурные ошибки (отсутствующие обязательные обёртки-элементы)
ловились локальным pytest, а не только на реальном Windows-инсталле у пользователя.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import setup_scheduled_tasks as sst

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _render(restart: bool = True) -> str:
    return sst._TASK_XML.format(
        description="test task",
        triggers=sst._TRIGGER_LOGON,
        user=r"DOMAIN\user",
        restart=sst._RESTART_ON_FAILURE if restart else "",
        command=r"C:\python.exe",
        arguments='"C:\\jarvis\\hud\\server.py" --port 8765',
        workdir=r"C:\hermes",
    )


def test_task_xml_is_well_formed():
    xml = _render()
    # ET.fromstring chokes on the <?xml ... encoding="UTF-16"?> declaration when the
    # input is already a decoded str (not bytes) — encode to match what schtasks actually
    # reads from disk (setup_scheduled_tasks.py writes the file as utf-16).
    ET.fromstring(xml.encode("utf-16"))


def test_task_xml_has_principals_wrapper():
    """Task Scheduler's schema requires <Principals><Principal>...</Principal></Principals>;
    a bare <Principal> directly under <Task> is rejected by schtasks.exe with
    "XML-файл имеет неверное содержание... Отсутствует узел" pointing at the Principal line.
    This is the exact bug reported from a real Windows install — regression-guard it here.
    """
    root = ET.fromstring(_render().encode("utf-16"))
    principals = root.find("t:Principals", NS)
    assert principals is not None, "missing <Principals> wrapper element"
    principal = principals.find("t:Principal", NS)
    assert principal is not None
    assert principal.get("id") == "Author"
    user_id = principal.find("t:UserId", NS)
    assert user_id is not None and user_id.text == r"DOMAIN\user"


def test_task_xml_required_top_level_elements_present():
    root = ET.fromstring(_render().encode("utf-16"))
    for tag in ("RegistrationInfo", "Triggers", "Principals", "Settings", "Actions"):
        assert root.find(f"t:{tag}", NS) is not None, f"missing <{tag}>"


def test_task_xml_valid_without_restart_block_too():
    # JARVIS-Updater is registered with restart=False; make sure the template still
    # produces valid, schema-complete XML with the {restart} placeholder empty.
    root = ET.fromstring(_render(restart=False).encode("utf-16"))
    assert root.find("t:Principals/t:Principal", NS) is not None
    assert root.find("t:Settings/t:RestartOnFailure", NS) is None


def test_run_helper_defaults_to_utf8_encoding_for_subprocess():
    # Regression guard for the UnicodeDecodeError seen on a cp1251-locale Windows machine:
    # _run() must always decode child-process output as UTF-8 with errors replaced, never
    # fall back to the platform's default locale encoding.
    import inspect

    src = inspect.getsource(sst._run)
    assert 'kw.setdefault("encoding", "utf-8")' in src
    assert 'kw.setdefault("errors", "replace")' in src
