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
        triggers=sst._trigger_logon(r"DOMAIN\user"),
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


def test_run_helper_uses_oem_encoding_on_windows():
    # Regression guard: schtasks.exe (a console app) writes stdout/stderr in the console's
    # OEM code page (GetOEMCP(), e.g. cp866 on a Russian-locale Windows machine), not UTF-8
    # and not the ANSI code page (GetACP()/cp1251). Decoding as UTF-8 doesn't raise (errors=
    # "replace" swallows it) but silently mangles every non-ASCII message into mojibake —
    # confirmed on a real user machine: "ОШИБКА: Отказано в доступе." became
    # "������: �⪠���� � ����㯥." when cp866 bytes were misdecoded as UTF-8. Python's
    # built-in "oem" codec (since 3.6, bpo-27959) decodes via the true console code page.
    import inspect

    src = inspect.getsource(sst._run)
    assert '"oem" if sys.platform == "win32" else "utf-8"' in src
    assert 'kw.setdefault("errors", "replace")' in src


def test_restart_on_failure_count_within_schema_range():
    """Task Scheduler XML schema (and MS-TSCH 2.5.4.2) types RestartOnFailure/Count as
    unsignedByte, valid range 1..255. A value of 999 (the original bug) is out of schema
    and schtasks.exe rejects the whole XML — but reports a generic/misleading error
    ("Access is denied.") instead of a schema-validation message, which is exactly what a
    real user hit: JARVIS-HUD/Gateway/App (restart=True) failed to register while
    JARVIS-Updater (restart=False, no RestartOnFailure block) succeeded.
    """
    root = ET.fromstring(_render(restart=True).encode("utf-16"))
    count_el = root.find("t:Settings/t:RestartOnFailure/t:Count", NS)
    assert count_el is not None
    count = int(count_el.text)
    assert 1 <= count <= 255, f"RestartOnFailure/Count={count} is outside the unsignedByte schema range 1..255"


def test_restart_on_failure_interval_present_and_valid_duration():
    root = ET.fromstring(_render(restart=True).encode("utf-16"))
    interval_el = root.find("t:Settings/t:RestartOnFailure/t:Interval", NS)
    assert interval_el is not None and interval_el.text == "PT1M"


def test_logon_trigger_has_explicit_user_id():
    """Regression guard for a real-world install: <LogonTrigger> WITHOUT <UserId> is
    interpreted by Task Scheduler as "fire on ANY user's logon" (see the official
    LogonTrigger.UserId docs: "If you want a task to be triggered when any member of a
    group logs on... do not assign a value to UserId"). Registering an unscoped logon
    trigger from a non-elevated process requires privileges a normal user doesn't have,
    and schtasks.exe rejects the whole task with the exact same generic "ОШИБКА: Отказано
    в доступе" ("Access is denied") message as a real permission problem — which is what
    masked this bug behind the (separately fixed) RestartOnFailure/Count=999 issue.
    A user hit this in production: JARVIS-HUD/Gateway/App (all use a LogonTrigger) failed
    to register while JARVIS-Updater (CalendarTrigger, no LogonTrigger at all) succeeded —
    the common factor was the missing <UserId>, not RestartOnFailure.
    """
    trigger_xml = sst._trigger_logon(r"DOMAIN\user")
    xml = sst._TASK_XML.format(
        description="test task", triggers=trigger_xml, user=r"DOMAIN\user",
        restart=sst._RESTART_ON_FAILURE, command=r"C:\python.exe",
        arguments='"C:\\jarvis\\hud\\server.py" --port 8765', workdir=r"C:\hermes",
    )
    root = ET.fromstring(xml.encode("utf-16"))
    logon = root.find("t:Triggers/t:LogonTrigger", NS)
    assert logon is not None
    user_id = logon.find("t:UserId", NS)
    assert user_id is not None and user_id.text, "LogonTrigger must carry an explicit UserId"
    assert user_id.text == r"DOMAIN\user"
