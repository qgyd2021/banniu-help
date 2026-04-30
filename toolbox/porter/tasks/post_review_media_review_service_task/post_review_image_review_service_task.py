#!/usr/bin/python3
# -*- coding: utf-8 -*-
import fnmatch
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask
from toolbox.xiaohongshu.media.share_media_download import ShareMediaDownload

logger = logging.getLogger("toolbox")


@BaseTask.register("post_review_image_review_service")
class PostReviewImageReviewServiceTask(BaseTask):
    """图片审核服务。"""

    def __init__(
        self,
        check_interval: int = 60,
        source_dir: str = "temp/banniu_37728/step_7_banniu_task_text_update",
        target_dir: str = "temp/banniu_37728/step_8_post_review_image_review",
        templates_dir: str = "toolbox/porter/tasks/post_review_media_review_service_task/templates",
        media_source_path: str = "*_post_meta_list/*/post_meta/image_urls",
        host: str = "0.0.0.0",
        port: int = 8000,
        service_registry_dir: str = "temp/service_registry",
        service_name: str = "post_review_image_review_service",
        service_access_path: str = "",
        service_description: str = "图片审核服务，提供媒体浏览与审核提交接口。",
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self._resolve_project_path(source_dir)
        self.target_dir = self._resolve_project_path(target_dir)
        self.templates_dir = self._resolve_project_path(templates_dir)
        self.media_source_path = str(media_source_path or "").strip() or "*_post_meta_list/*/post_meta/image_urls"
        self._meta_key_pattern, self._list_index, self._row_value_path = self._parse_media_source_path(
            self.media_source_path
        )
        self.host = host
        self.port = port
        self.service_registry_dir = self._resolve_project_path(service_registry_dir)
        self.service_name = str(service_name or "post_review_image_review_service").strip()
        self.service_access_path = str(service_access_path or "").strip()
        self.service_description = str(service_description or "").strip()
        self._xhs_share_client: Optional[ShareMediaDownload] = None
        self._xhs_meta_cache: Dict[str, Dict[str, Any]] = {}
        self.server_info_file = self._register_service_info()
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

    def _register_service_info(self) -> Path:
        registry_dir = self.service_registry_dir
        registry_dir.mkdir(parents=True, exist_ok=True)
        service_dir = registry_dir
        service_dir.mkdir(parents=True, exist_ok=True)
        access_path = self.service_access_path or f"http://{self.host}:{self.port}/gallery"
        payload = {
            "service_name": self.service_name,
            "service_type": "post_review_image_review_service",
            "service_access_path": access_path,
            "description": self.service_description,
            "meta": {
                "source_dir": self.source_dir.as_posix(),
                "target_dir": self.target_dir.as_posix(),
                "media_source_path": self.media_source_path,
            },
        }
        server_file = service_dir / "server.json"
        server_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return server_file

    @staticmethod
    def _parse_media_source_path(path: str) -> Tuple[str, Optional[int], List[str]]:
        tokens = [x.strip() for x in str(path or "").split("/") if x.strip()]
        if not tokens:
            return "*_post_meta_list", None, ["post_meta", "image_urls"]
        meta_key_pattern = tokens[0]
        remain = tokens[1:]
        list_index: Optional[int] = None
        if remain:
            selector = remain[0]
            if selector in ("*", "[*]"):
                remain = remain[1:]
            elif selector.startswith("[") and selector.endswith("]"):
                idx_token = selector[1:-1].strip()
                if idx_token.isdigit():
                    list_index = int(idx_token)
                    remain = remain[1:]
        row_value_path = remain if remain else ["post_meta", "image_urls"]
        return meta_key_pattern, list_index, row_value_path

    @staticmethod
    def _get_by_path(obj: object, path_tokens: List[str]) -> object:
        cur = obj
        for token in path_tokens:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(token)
        return cur

    @staticmethod
    def _normalize_url_list(raw_value: object) -> List[str]:
        if isinstance(raw_value, str):
            return [raw_value] if raw_value.startswith("http") else []
        if isinstance(raw_value, list):
            return [u for u in raw_value if isinstance(u, str) and u.startswith("http")]
        return []

    @staticmethod
    def _weibo_cdn_page_referer(image_url: str, item: dict, post_meta: dict) -> Optional[str]:
        """
        微博图床（*.sinaimg.cn）常校验 Referer；直连或 no-referrer 会 403。
        优先用帖子分享页 / final_url 作为 Referer，否则退回 weibo 首页。
        """
        try:
            host = (urlparse(image_url).netloc or "").lower()
        except Exception:
            return None
        if "sinaimg" not in host:
            return None
        share = str((item or {}).get("share_url") or "").strip()
        if share and ("weibo.com" in share.lower() or "weibo.cn" in share.lower()):
            return share.split("#", 1)[0]
        final_url = str((post_meta or {}).get("final_url") or "").strip()
        if final_url and ("weibo.com" in final_url.lower() or "weibo.cn" in final_url.lower()):
            return final_url.split("#", 1)[0]
        return "https://weibo.com/"

    def _extract_item_title(self, row: dict) -> str:
        if not isinstance(row, dict):
            return ""
        post_meta = row.get("post_meta") or {}
        if isinstance(post_meta, dict):
            return str(post_meta.get("title") or post_meta.get("desc") or "")
        return str(row.get("title") or row.get("desc") or "")

    @staticmethod
    def _host_looks_like_xhs_cdn(host: str) -> bool:
        h = str(host or "").lower()
        return ("xhscdn.com" in h) or ("xhsimg.com" in h)

    def _refresh_xhs_image_url(self, share_url: str, image_index: int, fallback_url: str) -> Optional[str]:
        """
        小红书图链会过期：失败时用 share_url 重新抓取 post_meta，按索引取新图链重试。
        """
        s = str(share_url or "").strip()
        if not s:
            return None
        if s in self._xhs_meta_cache:
            post_meta = self._xhs_meta_cache[s]
        else:
            if self._xhs_share_client is None:
                self._xhs_share_client = ShareMediaDownload()
            post_meta = self._xhs_share_client.get_post_meta_by_share_url(s) or {}
            if not isinstance(post_meta, dict):
                return None
            self._xhs_meta_cache[s] = post_meta

        idx = max(0, int(image_index or 0))
        candidates = post_meta.get("image_url_candidates")
        if isinstance(candidates, list) and idx < len(candidates):
            row = candidates[idx]
            if isinstance(row, list):
                for u in row:
                    if isinstance(u, str) and u.startswith("http"):
                        return u
        urls = post_meta.get("image_urls")
        if isinstance(urls, list) and idx < len(urls):
            u = urls[idx]
            if isinstance(u, str) and u.startswith("http"):
                return u
        if isinstance(fallback_url, str) and fallback_url.startswith("http"):
            return fallback_url
        return None

    def _xhs_candidates_from_source_file(
        self,
        source_file: str,
        post_index: int,
        image_index: int,
        fallback_url: str,
    ) -> List[str]:
        """
        直接从本地 task json 的 image_url_candidates 读取候选 URL，避免依赖实时抓取。
        """
        out: List[str] = []
        sf = str(source_file or "").strip()
        if not sf:
            return out
        fp = Path(sf)
        if not fp.is_absolute():
            fp = (self.source_dir / fp).resolve()
        js = self._safe_read_json(fp)
        if not isinstance(js, dict):
            return out
        for _, value in js.items():
            if not isinstance(value, list):
                continue
            if int(post_index or 0) >= len(value):
                continue
            row = value[int(post_index or 0)]
            if not isinstance(row, dict):
                continue
            post_meta = row.get("post_meta")
            if not isinstance(post_meta, dict):
                continue
            candidates = post_meta.get("image_url_candidates")
            idx = int(image_index or 0)
            if isinstance(candidates, list) and idx < len(candidates):
                group = candidates[idx]
                if isinstance(group, list):
                    for u in group:
                        if isinstance(u, str) and u.startswith("http"):
                            out.append(u)
            urls = post_meta.get("image_urls")
            if isinstance(urls, list) and idx < len(urls):
                u = urls[idx]
                if isinstance(u, str) and u.startswith("http"):
                    out.append(u)
        if isinstance(fallback_url, str) and fallback_url.startswith("http"):
            out.append(fallback_url)
        dedupe: List[str] = []
        seen = set()
        for u in out:
            if u not in seen:
                seen.add(u)
                dedupe.append(u)
        return dedupe

    def _collect_gallery_rows(self) -> List[Dict[str, Any]]:
        if not self.source_dir.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for fp in sorted(self.source_dir.rglob("*.json")):
            payload = self._safe_read_json(fp)
            if not isinstance(payload, dict):
                continue
            task_id = str(payload.get("task_id") or fp.stem)
            platform = fp.parent.name
            for key, value in payload.items():
                if not isinstance(value, list):
                    continue
                if not fnmatch.fnmatch(str(key), self._meta_key_pattern):
                    continue
                for idx, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    if self._list_index is not None and idx != self._list_index:
                        continue
                    media_urls = self._normalize_url_list(self._get_by_path(item, self._row_value_path))
                    post_meta = item.get("post_meta") if isinstance(item.get("post_meta"), dict) else {}
                    media_items: List[Dict[str, Any]] = []
                    share_url = str(item.get("share_url") or "").strip()
                    for image_idx, u in enumerate(media_urls):
                        entry: Dict[str, Any] = {"type": "image", "url": u}
                        ref = self._weibo_cdn_page_referer(u, item, post_meta)
                        if ref:
                            entry["cdn_referer"] = ref
                        # 小红书图片 URL 有时会过期，预先携带刷新所需上下文给代理接口。
                        host = (urlparse(u).netloc or "").lower()
                        if self._host_looks_like_xhs_cdn(host) and share_url:
                            entry["xhs_share_url"] = share_url
                            entry["xhs_image_index"] = image_idx
                            entry["source_file"] = fp.as_posix()
                            entry["post_index"] = idx
                        media_items.append(entry)
                    if not media_items:
                        continue
                    rows.append(
                        {
                            "task_id": task_id,
                            "platform": platform,
                            "source_file": fp.as_posix(),
                            "post_index": idx,
                            "share_url": item.get("share_url"),
                            "title": self._extract_item_title(item),
                            "image_urls": media_urls,
                            "video_urls": [],
                            "media_items": media_items,
                        }
                    )
        rows.sort(key=lambda x: (x["platform"], x["task_id"], x["post_index"]))
        return rows

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Post Review Image Review Service")
        templates = Jinja2Templates(directory=self.templates_dir.as_posix())
        task = self

        class SubmitRowRequest(BaseModel):
            source_file: str
            image_marks: Dict[str, str] | None = None

        @app.get("/api/media-stream")
        def api_media_stream(
            request: Request,
            url: str,
            page_referer: Optional[str] = None,
            xhs_share_url: Optional[str] = None,
            xhs_image_index: Optional[str] = None,
            source_file: Optional[str] = None,
            post_index: Optional[str] = None,
        ):
            """代理拉取外链图片（如微博 sinaimg），带上 Referer，避免浏览器 403。"""
            media_url = str(url or "").strip()
            if not (media_url.startswith("http://") or media_url.startswith("https://")):
                raise HTTPException(status_code=400, detail="invalid media url")
            netloc = (urlparse(media_url).netloc or "").lower()
            headers: Dict[str, str] = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": request.headers.get("accept") or "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Accept-Language": request.headers.get("accept-language") or "zh-CN,zh;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
            }
            ref = (page_referer or "").strip()
            if ref:
                headers["Referer"] = ref
            elif "sinaimg" in netloc:
                headers["Referer"] = "https://weibo.com/"
            range_header = request.headers.get("range")

            def _open_upstream(target: str, hdrs: Dict[str, str]) -> requests.Response:
                h = dict(hdrs)
                if range_header:
                    h["Range"] = range_header
                return requests.get(target, headers=h, stream=True, timeout=60)

            try:
                upstream = _open_upstream(media_url, headers)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"upstream request failed: {e}") from e
            if upstream.status_code not in (200, 206) and "sinaimg" in netloc:
                upstream.close()
                weibo_refs = []
                cur_ref = str(headers.get("Referer") or "").strip()
                if cur_ref:
                    weibo_refs.append(cur_ref)
                for ref in ("https://weibo.com/", "https://m.weibo.cn/", "https://weibo.cn/"):
                    if ref not in weibo_refs:
                        weibo_refs.append(ref)
                upstream = None
                for ref in weibo_refs:
                    retry_headers = dict(headers)
                    retry_headers["Referer"] = ref
                    try:
                        resp = _open_upstream(media_url, retry_headers)
                    except Exception:
                        continue
                    if resp.status_code in (200, 206):
                        upstream = resp
                        break
                    resp.close()
                if upstream is None:
                    upstream = _open_upstream(media_url, headers)
            if upstream.status_code not in (200, 206) and task._host_looks_like_xhs_cdn(netloc):
                upstream.close()
                # 第一层兜底：从本地已保存的 image_url_candidates 逐个重试。
                local_cands = task._xhs_candidates_from_source_file(
                    source_file=str(source_file or "").strip(),
                    post_index=int(str(post_index or "0") or "0"),
                    image_index=int(str(xhs_image_index or "0") or "0"),
                    fallback_url=media_url,
                )
                upstream = None
                for cand in local_cands:
                    if cand == media_url:
                        continue
                    try:
                        resp = _open_upstream(cand, headers)
                    except Exception:
                        continue
                    if resp.status_code in (200, 206):
                        media_url = cand
                        upstream = resp
                        break
                    resp.close()
                if upstream is None:
                    upstream = _open_upstream(media_url, headers)
            if upstream.status_code not in (200, 206) and task._host_looks_like_xhs_cdn(netloc):
                upstream.close()
                try:
                    refreshed = task._refresh_xhs_image_url(
                        share_url=str(xhs_share_url or "").strip(),
                        image_index=int(str(xhs_image_index or "0") or "0"),
                        fallback_url=media_url,
                    )
                except Exception:
                    refreshed = None
                if refreshed and refreshed != media_url:
                    media_url = refreshed
                    try:
                        upstream = _open_upstream(media_url, headers)
                    except Exception as e:
                        raise HTTPException(status_code=502, detail=f"upstream refresh request failed: {e}") from e
            if upstream.status_code not in (200, 206):
                upstream.close()
                raise HTTPException(status_code=upstream.status_code, detail="upstream response not ok")

            def iter_chunks():
                try:
                    for chunk in upstream.raw.stream(1024 * 128, decode_content=False):
                        if chunk:
                            yield chunk
                finally:
                    upstream.close()

            resp_headers = {"Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes")}
            for key in ("Content-Type", "Content-Length", "Content-Range", "Cache-Control", "ETag", "Last-Modified"):
                value = upstream.headers.get(key)
                if value:
                    resp_headers[key] = value
            media_type = upstream.headers.get("Content-Type") or "application/octet-stream"
            return StreamingResponse(
                iter_chunks(), status_code=upstream.status_code, media_type=media_type, headers=resp_headers
            )

        @app.post("/api/submit-row")
        def api_submit_row(payload: SubmitRowRequest) -> Dict[str, Any]:
            data_root = task.source_dir.resolve()
            step8_root = task.target_dir.resolve()
            raw_src = Path(payload.source_file)
            src = (raw_src if raw_src.is_absolute() else (data_root / raw_src)).resolve()
            try:
                rel = src.relative_to(data_root)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid source_file path") from exc
            target = step8_root / rel
            if target.exists() and target.is_file():
                return {"ok": True, "already_submitted": True, "source_file": src.as_posix(), "target_file": target.as_posix()}
            if not src.exists() or not src.is_file():
                raise HTTPException(status_code=404, detail=f"source file not found in step_7: {src.as_posix()}")
            js = task._safe_read_json(src)
            if not isinstance(js, dict):
                raise HTTPException(status_code=400, detail="source file is not valid json object")

            raw_media_marks = payload.image_marks or {}
            media_marks: Dict[str, str] = {}
            for media_url, mark_label in raw_media_marks.items():
                if not isinstance(media_url, str) or not media_url:
                    continue
                if mark_label in ("符合", "不符合", ""):
                    media_marks[media_url] = mark_label
                elif mark_label is None:
                    media_marks[media_url] = ""
                else:
                    media_marks[media_url] = str(mark_label)

            js["post_review_image_review"] = {"image_marks": media_marks}
            js["post_review_image_review_status"] = "done"
            src.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src.as_posix(), target.as_posix())
            return {"ok": True, "source_file": src.as_posix(), "target_file": target.as_posix()}

        @app.get("/", response_class=HTMLResponse)
        @app.get("/gallery", response_class=HTMLResponse)
        def gallery_page(request: Request) -> HTMLResponse:
            rows = task._collect_gallery_rows()
            return templates.TemplateResponse(
                request=request,
                name="gallery.html",
                context={
                    "rows": rows,
                    "data_dir": task.source_dir.as_posix(),
                    "count": len(rows),
                    "media_type": "image",
                    "media_source_path": task.media_source_path,
                },
            )

        return app

    async def do_task(self):
        logger.info(f"[{self.flag}] start image review service on http://{self.host}:{self.port}/gallery")
        logger.info(f"{self.flag}service info file: {self.server_info_file.as_posix()}")
        config = uvicorn.Config(app=self.app, host=self.host, port=self.port, reload=False, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


if __name__ == "__main__":
    pass
