#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask

logger = logging.getLogger("toolbox")


@BaseTask.register("portal_server")
class PortalServerTask(BaseTask):
    """
    统一门户服务：递归扫描 server.json，展示服务入口列表。
    """

    def __init__(
        self,
        check_interval: int = 60,
        registry_dir: str = "temp/banniu_37728/server",
        host: str = "0.0.0.0",
        port: int = 7000,
        title: str = "审核服务入口",
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.registry_dir = self._resolve_project_path(registry_dir)
        self.host = host
        self.port = int(port)
        self.title = str(title or "审核服务入口")
        self.app = self._build_app()

    @staticmethod
    def _resolve_project_path(raw_path: str) -> Path:
        p = Path(raw_path)
        if p.is_absolute():
            return p.resolve()
        return (project_path / p).resolve()

    @staticmethod
    def _safe_read_json(path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _collect_services(self) -> List[Dict[str, str]]:
        if not self.registry_dir.exists():
            return []
        rows: List[Dict[str, str]] = []
        for fp in sorted(self.registry_dir.rglob("server.json")):
            js = self._safe_read_json(fp)
            if not isinstance(js, dict):
                continue
            name = str(js.get("service_name") or "").strip()
            desc = str(js.get("description") or "").strip()
            path = str(js.get("service_access_path") or "").strip()
            if not (name or desc or path):
                continue
            rows.append(
                {
                    "service_name": name or "-",
                    "description": desc or "-",
                    "service_access_path": path or "-",
                }
            )
        return rows

    def _build_app(self) -> FastAPI:
        app = FastAPI(title=self.title)
        task = self

        @app.get("/api/services")
        def api_services() -> Dict[str, Any]:
            services = task._collect_services()
            return {"count": len(services), "services": services}

        @app.get("/", response_class=HTMLResponse)
        @app.get("/portal", response_class=HTMLResponse)
        def portal_page(request: Request) -> HTMLResponse:
            services = task._collect_services()
            rows_html = ""
            for i, row in enumerate(services, start=1):
                access = row["service_access_path"]
                access_html = (
                    f'<a href="{access}" target="_blank" rel="noopener noreferrer">{access}</a>'
                    if access.startswith("http")
                    else access
                )
                rows_html += (
                    "<tr>"
                    f"<td>{i}</td>"
                    f"<td>{row['service_name']}</td>"
                    f"<td>{row['description']}</td>"
                    f"<td>{access_html}</td>"
                    "</tr>"
                )
            if not rows_html:
                rows_html = '<tr><td colspan="4" style="text-align:center;color:#888;">暂无可用服务</td></tr>'

            html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{task.title}</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, PingFang SC, sans-serif; margin: 0; background: #f7f8fa; color: #222; }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
    h1 {{ margin: 0 0 10px; font-size: 24px; }}
    .sub {{ color: #666; margin-bottom: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 10px 12px; text-align: left; font-size: 14px; }}
    th {{ background: #fafafa; color: #333; }}
    tr:hover td {{ background: #fcfcff; }}
    a {{ color: #1677ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{task.title}</h1>
    <div class="sub">注册目录：<code>{task.registry_dir.as_posix()}</code> ｜ 当前共 {len(services)} 个服务</div>
    <table>
      <thead>
        <tr>
          <th style="width:60px;">#</th>
          <th style="width:360px;">服务名字</th>
          <th>描述</th>
          <th style="width:420px;">访问路径</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
            return HTMLResponse(content=html)

        return app

    async def do_task(self):
        logger.info(f"{self.flag} start portal service on http://{self.host}:{self.port}/portal")
        config = uvicorn.Config(app=self.app, host=self.host, port=self.port, reload=False, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


if __name__ == "__main__":
    pass
