"""Per-user daily Windows task; the action only prunes the private cache."""
from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET

from .path_settings import config_path

NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def task_name():
    key = hashlib.sha256(str(config_path().parent).casefold().encode()).hexdigest()[:12]
    return "ZzzHeTMA-CloudCache-" + key


def task_xml():
    ET.register_namespace("", NAMESPACE)
    def add(parent, tag, text=None, **attributes):
        node = ET.SubElement(parent, "{" + NAMESPACE + "}" + tag, attributes)
        if text is not None: node.text = text
        return node
    task = ET.Element("{" + NAMESPACE + "}Task", {"version": "1.2"})
    registration = add(task, "RegistrationInfo")
    add(registration, "Description", "每天清理 ZzzHe TMA 云文件的过期本地缓存；不连接或删除云盘文件。")
    triggers = add(task, "Triggers")
    daily = add(triggers, "CalendarTrigger")
    add(daily, "StartBoundary", datetime.now().strftime("%Y-%m-%dT03:00:00"))
    add(daily, "Enabled", "true")
    schedule = add(daily, "ScheduleByDay"); add(schedule, "DaysInterval", "1")
    principals = add(task, "Principals")
    principal = add(principals, "Principal", id="Author")
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    if user: add(principal, "UserId", (domain + "\\" if domain else "") + user)
    # InteractiveToken uses the registering user and needs no Windows password.
    add(principal, "LogonType", "InteractiveToken")
    add(principal, "RunLevel", "LeastPrivilege")
    settings = add(task, "Settings")
    for key, value in {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
                       "StopIfGoingOnBatteries": "false", "StartWhenAvailable": "true",
                       "ExecutionTimeLimit": "PT10M", "Enabled": "true"}.items():
        add(settings, key, value)
    actions = add(task, "Actions", Context="Author"); action = add(actions, "Exec")
    if getattr(sys, "frozen", False):
        command, arguments = sys.executable, "--cloud-cleanup"
        working_directory = Path(sys.executable).resolve().parent
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        command = str(pythonw) if pythonw.exists() else sys.executable
        arguments = '"' + str(Path(__file__).resolve().parents[1] / "run.py") + '" --cloud-cleanup'
        working_directory = Path(__file__).resolve().parents[1]
    arguments += ' --cloud-config-folder "' + str(config_path().parent.resolve()) + '"'
    add(action, "Command", command)
    add(action, "Arguments", arguments)
    add(action, "WorkingDirectory", str(working_directory))
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def install_daily_task():
    if os.name != "nt":
        return {"installed": False, "message": "每日后台清理需要 Windows；应用运行期间仍会自动清理"}
    descriptor, temporary = tempfile.mkstemp(prefix="zzzhe-cloud-task-", suffix=".xml")
    try:
        with os.fdopen(descriptor, "wb") as handle: handle.write(task_xml())
        result = subprocess.run(["schtasks.exe", "/Create", "/TN", task_name(), "/XML", temporary, "/F"],
            capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
        return {"installed": result.returncode == 0, "message": "每日 03:00 自动清理已启用（错过时在登录后补执行）" if result.returncode == 0 else
                "Windows 每日计划未能建立；应用运行期间仍会自动清理。" + result.stderr.decode("mbcs", errors="replace").strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"installed": False, "message": "Windows 每日计划未能建立：" + str(exc)}
    finally:
        Path(temporary).unlink(missing_ok=True)
