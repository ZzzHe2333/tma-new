"""Opt-in, loopback-only MCP transport and independent background batch jobs.

The SDK is imported only when a service is actually started. No Qt widgets or
desktop sessions are accessed by the HTTP or calculation threads.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import hmac
import json
from pathlib import Path
import queue
import secrets
import socket
import threading
from typing import Literal
import uuid

from . import APP_NAME, __version__
from . import path_settings

DEFAULT_PORT = 18765


def load_settings():
    value = path_settings._settings_data().get("mcp", {})
    if not isinstance(value, dict):
        raise ValueError("MCP 配置格式无效")
    result = {"enabled": False, "port": DEFAULT_PORT, "token": "", **value}
    validate_settings(result)
    return result


def validate_settings(value):
    if type(value.get("enabled")) is not bool:
        raise ValueError("MCP 开关无效")
    if type(value.get("port")) is not int or not 1024 <= value["port"] <= 65535:
        raise ValueError("端口必须在 1024–65535 之间")
    token = value.get("token", "")
    if not isinstance(token, str) or (token and (len(token) < 24 or not token.isascii() or any(c.isspace() for c in token))):
        raise ValueError("访问密钥格式无效")


def save_settings(value):
    validate_settings(value)
    data = path_settings._settings_data()
    data["mcp"] = {key: value[key] for key in ("enabled", "port", "token")}
    path_settings._save_data(data)


def endpoint(port):
    return f"http://127.0.0.1:{port}/mcp"


def client_config(settings):
    return {"mcpServers": {"zzzhe-tma": {"type": "http", "url": endpoint(settings["port"]),
             "headers": {"Authorization": "Bearer " + settings["token"]}}}}


class BatchJobs:
    """Bounded queue; one daemon worker preserves order and limits memory use."""
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs = OrderedDict()
        self.queue = queue.Queue(maxsize=20)
        self.stopped = threading.Event()
        self.worker = None

    def submit(self, files, output_directory=None, formats=None, mass_source=None):
        if not files or len(files) > 1000:
            raise ValueError("每批需要 1–1000 个 TMA 文件，顺序及重复文件均保留")
        normalized = []
        for file in files:
            if str(file).startswith("cloud://"):
                from .cloud_storage import parse_uri
                _, remote = parse_uri(file)
                if not Path(remote).suffix[1:].isdigit():
                    raise ValueError("请提供 .001 等数字后缀的云文件")
                normalized.append(str(file))
                continue
            path = Path(file).expanduser()
            if not path.is_absolute() or not path.suffix[1:].isdigit():
                raise ValueError("请提供 .001 等数字后缀文件的绝对路径")
            normalized.append(str(path.resolve()))
        formats = list(dict.fromkeys(formats or []))
        if any(f not in ("png", "xlsx", "csv") for f in formats):
            raise ValueError("导出格式只支持 png、xlsx、csv")
        if formats and (not output_directory or not Path(output_directory).is_absolute()):
            raise ValueError("导出目录必须为绝对路径")
        if mass_source is None:
            mass_source = path_settings.mass_source()
        if mass_source and not mass_source.startswith("cloud://") and not Path(mass_source).is_absolute():
            raise ValueError("称量表或目录必须为绝对路径")
        with self.lock:
            if self.stopped.is_set():
                raise ValueError("MCP 服务正在关闭")
            while len(self.jobs) >= 20:
                old = next((key for key, job in self.jobs.items() if job["state"] in ("completed", "cancelled", "failed")), None)
                if old is None:
                    raise ValueError("任务队列已满，请等待任务完成")
                self.jobs.pop(old)
            key = uuid.uuid4().hex
            job = {"job_id": key, "state": "queued", "total": len(normalized), "processed": 0,
                   "rows": [], "artifacts": [], "errors": [], "cancel_requested": False,
                   "output_directory": ""}
            self.jobs[key] = job
            try:
                self.queue.put_nowait((key, normalized, output_directory, formats, mass_source))
            except queue.Full as exc:
                self.jobs.pop(key)
                raise ValueError("任务队列已满，请稍后重试") from exc
            if self.worker is None:
                self.worker = threading.Thread(target=self._run, name="TMA-MCP-batch", daemon=True)
                self.worker.start()
            return {"job_id": key, "state": "queued", "total": len(normalized),
                    "next": "调用 tma_job_status 查询进度和结果；需要取消时调用 tma_cancel_job。"}

    def status(self, key):
        from .batch_analysis import table_text
        with self.lock:
            if key not in self.jobs:
                raise ValueError("任务不存在或已过期（仅保留最近 20 个任务，关闭服务后清空）")
            result = json.loads(json.dumps(self.jobs[key], ensure_ascii=False, allow_nan=False))
        result["tsv"] = table_text(result["rows"])
        return result

    def cancel(self, key):
        with self.lock:
            if key not in self.jobs:
                raise ValueError("任务不存在或已过期")
            job = self.jobs[key]
            if job["state"] not in ("completed", "failed", "cancelled"):
                job["cancel_requested"] = True
                if job["state"] == "queued":
                    job["state"] = "cancelled"
            return {"job_id": key, "state": job["state"], "cancel_requested": job["cancel_requested"]}

    def shutdown(self):
        self.stopped.set()
        with self.lock:
            for key in self.jobs:
                self.cancel(key)

    def _cancelled(self, job):
        return self.stopped.is_set() or job["cancel_requested"]

    def _run(self):
        from . import batch_analysis as batch
        while not self.stopped.is_set():
            try:
                key, files, directory, formats, source = self.queue.get(timeout=.25)
            except queue.Empty:
                continue
            with self.lock:
                job = self.jobs.get(key)
                if job is None or self._cancelled(job):
                    continue
                job["state"] = "running"
            try:
                folder = None
                if formats:
                    folder = Path(directory) / (datetime.now().strftime("TMA-%Y%m%d-%H%M%S-") + key[:12])
                    folder.mkdir(parents=True, exist_ok=False)
                    with self.lock:
                        job["output_directory"] = str(folder.resolve())
                rows = []
                for file in files:
                    if self._cancelled(job):
                        break
                    row = batch.calculate_file(file)
                    if not row.get("error"):
                        row = batch.match_mass(row, source)
                    if self._cancelled(job):
                        break
                    if "png" in formats and not row.get("error"):
                        path = batch.plot_paths([row], folder)[0]
                        try:
                            batch.write_plot(row, path)
                            row["png"] = str(path.resolve())
                            with self.lock:
                                job["artifacts"].append({"type": "png", "path": row["png"]})
                        except Exception as exc:
                            with self.lock:
                                job["errors"].append(f"{Path(file).name}: 出图失败：{exc}")
                    compact = batch.history_snapshot([row])[0]
                    rows.append(compact)
                    with self.lock:
                        job["rows"].append(compact)
                        job["processed"] += 1
                if not self._cancelled(job) and rows:
                    for kind in ("xlsx", "csv"):
                        if kind not in formats or self._cancelled(job):
                            continue
                        path = folder / ("TMA结果." + kind)
                        if kind == "xlsx":
                            batch.write_xlsx(rows, path)
                        else:
                            import csv
                            with path.open("x", encoding="utf-8-sig", newline="") as handle:
                                writer = csv.writer(handle)
                                writer.writerow(batch.HEADERS)
                                writer.writerows([[row.get(k) for k in batch.KEYS] for row in rows])
                        with self.lock:
                            job["artifacts"].append({"type": kind, "path": str(path.resolve())})
                with self.lock:
                    job["state"] = ("cancelled" if self._cancelled(job) else
                                    "failed" if not rows or all(row.get("error") for row in rows) or job["errors"] else "completed")
            except Exception as exc:
                with self.lock:
                    job["errors"].append(str(exc))
                    job["state"] = "cancelled" if self._cancelled(job) else "failed"


def create_http_app(settings, jobs, active):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import ToolAnnotations
    from starlette.responses import JSONResponse

    server = FastMCP(APP_NAME, instructions="先提交批量任务，再用 tma_job_status 轮询直到终态；结果包含 T1/T2/M/H、TSV 和导出路径。未匹配 M 为 null，不补默认值。",
                     host="127.0.0.1", port=settings["port"], stateless_http=True, json_response=True,
                     transport_security=TransportSecuritySettings(allowed_hosts=[f"127.0.0.1:{settings['port']}", f"localhost:{settings['port']}"],
                         allowed_origins=[f"http://127.0.0.1:{settings['port']}", f"http://localhost:{settings['port']}"]))
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=read)
    def tma_status() -> dict:
        """查看应用版本、批量算法、已配置的 M 路径和服务状态，不访问桌面曲线。"""
        return {"app": APP_NAME, "version": __version__, "algorithm": "V233", "transport": "streamable-http",
                "endpoint": endpoint(settings["port"]), "mass_source": path_settings.mass_source(),
                "max_files_per_batch": 1000, "history": "服务内存中最近 20 个任务，与桌面本次运行批次独立"}

    @server.tool(annotations=read)
    def tma_batch_analyze(files: list[str], mass_source: str | None = None) -> dict:
        """提交多个 .001 等文件的绝对路径或 cloud:// 云文件地址，按原顺序读取 T1/T2/M/H。重复文件独立保留。

        mass_source 省略时使用设置中的 M 称量表/目录；空字符串表示不匹配 M。
        返回 job_id，使用 tma_job_status 获取进度、逐文件错误、数值及可粘贴 Excel 的 TSV。
        """
        return jobs.submit(files, mass_source=mass_source)

    @server.tool(annotations=write)
    def tma_batch_export(files: list[str], output_directory: str,
                         formats: list[Literal["png", "xlsx", "csv"]], mass_source: str | None = None) -> dict:
        """后台批量计算并导出。formats 可选 png、xlsx、csv，至少选一项。

        输入文件和 output_directory 均为绝对路径。在输出目录创建独立任务子文件夹，
        不覆盖旧输出。PNG 使用文件名；重复名称自动编号；XLSX/CSV 只有 T1/T2/M/H 四列。
        返回 job_id，使用 tma_job_status 获取结果和完整导出路径。
        """
        if not formats:
            raise ValueError("至少选择一个导出格式")
        return jobs.submit(files, output_directory, formats, mass_source)

    @server.tool(annotations=read)
    def tma_job_status(job_id: str) -> dict:
        """查询任务进度、结果、错误及导出文件。终态为 completed、failed 或 cancelled。

        completed 仍可能含个别文件读取错误，应检查每行 error/warning。
        T1/T2 单位 °C，M 单位 mg，H 单位 µm，未匹配或失败值为 null/缺省。
        """
        return jobs.status(job_id)

    @server.tool(annotations=write)
    def tma_cancel_job(job_id: str) -> dict:
        """取消排队或执行中的任务；当前文件处理结束后停止，已生成的文件会保留。"""
        return jobs.cancel(job_id)

    inner = server.streamable_http_app()

    async def authenticated(scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
            expected = ("Bearer " + settings["token"]).encode("ascii")
            if not active.is_set():
                return await JSONResponse({"error": "服务已关闭"}, status_code=503)(scope, receive, send)
            if not hmac.compare_digest(supplied, expected):
                return await JSONResponse({"error": "需要 MCP 访问密钥"}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        await inner(scope, receive, send)
    return authenticated


class McpService:
    def __init__(self):
        self.thread = None
        self.server = None
        self.jobs = None
        self.active = threading.Event()
        self.state = "stopped"
        self.error = ""
        self.port = DEFAULT_PORT

    def start(self, settings):
        validate_settings(settings)
        if not settings["enabled"]:
            self.stop()
            return
        if not settings["token"]:
            raise ValueError("请先在 MCP 设置中生成并保存访问密钥")
        if self.thread and self.thread.is_alive():
            if self.port == settings["port"] and self.state in ("starting", "running"):
                return
            raise ValueError("服务正在运行或停止中，请先关闭后再修改端口")
        if self.jobs and self.jobs.worker and self.jobs.worker.is_alive():
            raise ValueError("上一批任务正在取消，请稍后再开启服务")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", settings["port"]))
            listener.listen(32)
        except OSError as exc:
            listener.close()
            self.state, self.error = "error", f"端口 {settings['port']} 无法使用：{exc}"
            raise ValueError(self.error) from exc
        self.port, self.state, self.error = settings["port"], "starting", ""
        self.active.set()
        self.jobs = BatchJobs()
        self.thread = threading.Thread(target=self._serve, args=(dict(settings), listener), name="TMA-MCP-HTTP", daemon=True)
        self.thread.start()

    def _serve(self, settings, listener):
        try:
            import asyncio
            import uvicorn
            app = create_http_app(settings, self.jobs, self.active)
            config = uvicorn.Config(app, host="127.0.0.1", port=settings["port"], loop="asyncio", http="h11",
                                    ws="none", log_config=None, log_level="warning", access_log=False,
                                    timeout_graceful_shutdown=1)
            self.server = uvicorn.Server(config)
            if not self.active.is_set():
                return
            async def run():
                task = asyncio.create_task(self.server.serve(sockets=[listener]))
                while not task.done() and not self.server.started:
                    await asyncio.sleep(.02)
                if self.server.started and self.active.is_set():
                    self.state = "running"
                if not self.active.is_set():
                    self.server.should_exit = True
                await task
            asyncio.run(run())
        except BaseException as exc:
            self.state, self.error = "error", str(exc) or type(exc).__name__
        finally:
            self.active.clear()
            self.jobs.shutdown()
            listener.close()
            if self.state != "error":
                self.state = "stopped"

    def stop(self):
        self.active.clear()
        if self.jobs:
            self.jobs.shutdown()
            if self.jobs.worker and self.jobs.worker.is_alive():
                self.jobs.worker.join(timeout=.3)
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.state = "stopping"
            self.thread.join(timeout=2)
        if not self.thread or not self.thread.is_alive():
            self.state = "stopped"


def new_token():
    return secrets.token_urlsafe(32)
