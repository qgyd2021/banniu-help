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
from toolbox.weibo.media.share_media_download import ShareMediaDownload

logger = logging.getLogger("toolbox")


@BaseTask.register("post_review_video_review_service")
class PostReviewVideoReviewServiceTask(BaseTask):
    """视频审核服务。"""

    def __init__(
        self,
        check_interval: int = 60,
        source_dir: str = "temp/banniu_37728/step_9_banniu_task_image_update",
        target_dir: str = "temp/banniu_37728/step_10_post_review_video_review",
        templates_dir: str = "toolbox/porter/tasks/post_review_media_review_service_task/templates",
        media_source_path: str = "*_post_meta_list/*/post_meta/video_urls",
        host: str = "0.0.0.0",
        port: int = 9000,
        service_registry_dir: str = "temp/service_registry",
        service_name: str = "post_review_video_review_service",
        service_access_path: str = "",
        service_description: str = "视频审核服务，提供流代理、媒体浏览与审核提交接口。",
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self._resolve_project_path(source_dir)
        self.target_dir = self._resolve_project_path(target_dir)
        self.templates_dir = self._resolve_project_path(templates_dir)
        self.media_source_path = str(media_source_path or "").strip() or "*_post_meta_list/*/post_meta/video_urls"
        self._meta_key_pattern, self._list_index, self._row_value_path = self._parse_media_source_path(
            self.media_source_path
        )
        self.host = host
        self.port = port
        self.service_registry_dir = self._resolve_project_path(service_registry_dir)
        self.service_name = str(service_name or "post_review_video_review_service").strip()
        self.service_access_path = str(service_access_path or "").strip()
        self.service_description = str(service_description or "").strip()
        self._weibo_share_client: Optional[ShareMediaDownload] = None
        self._weibo_meta_cache: Dict[str, Dict[str, Any]] = {}
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
            "service_type": "post_review_video_review_service",
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
            return "*_post_meta_list", None, ["post_meta", "video_urls"]
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
        row_value_path = remain if remain else ["post_meta", "video_urls"]
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
    def _host_looks_like_bilibili_video_cdn(host: str) -> bool:
        h = (host or "").lower()
        return any(part in h for part in ("bilibili.com", "hdslb.com", "bilivideo.com", "bilivideo.cn", "b23.tv"))

    @staticmethod
    def _host_looks_like_weibo_video_cdn(host: str) -> bool:
        h = (host or "").lower()
        return any(part in h for part in ("weibocdn.com", "sinaimg.cn", "sina.com.cn"))

    @staticmethod
    def _normalize_bilibili_page_referer(raw: Optional[str]) -> str:
        r = (raw or "").strip()
        if r.startswith("http") and "bilibili.com" in r and "/video/" in r.lower():
            return r
        return "https://www.bilibili.com/"

    @staticmethod
    def _bilibili_playurl_refresh_candidates(
        page_referer: Optional[str],
        bvid: Optional[str],
        aid: Optional[str],
        cid: str,
    ) -> List[str]:
        from toolbox.bilibili.media.share_video_download import ShareVideoDownload

        bv = (bvid or "").strip() or None
        av_raw = (aid or "").strip()
        av = av_raw if av_raw and not bv else None
        try:
            cid_int = int(str(cid).strip())
        except ValueError:
            return []
        if not bv and not av:
            return []
        pref = PostReviewVideoReviewServiceTask._normalize_bilibili_page_referer(page_referer)
        if pref == "https://www.bilibili.com/":
            try:
                aid_for_canon = int(av) if av and av.isdigit() else (av or 0)
            except ValueError:
                aid_for_canon = av or 0
            pref = ShareVideoDownload.canonical_video_page_url(bv, aid_for_canon)
        client = ShareVideoDownload()
        play = client.get_playurl_for_cid(bvid=bv, aid=av, cid=cid_int, page_referer=pref)
        return ShareVideoDownload._pick_video_url_from_playurl_data(play)

    def _extract_item_title(self, row: dict) -> str:
        if not isinstance(row, dict):
            return ""
        post_meta = row.get("post_meta") or {}
        if isinstance(post_meta, dict):
            return str(post_meta.get("title") or post_meta.get("desc") or "")
        return str(row.get("title") or row.get("desc") or "")

    def _get_weibo_share_client(self) -> ShareMediaDownload:
        if self._weibo_share_client is None:
            self._weibo_share_client = ShareMediaDownload()
        return self._weibo_share_client

    def _refresh_weibo_video_url(
        self,
        share_url: str,
        video_index: int,
        fallback_url: str,
    ) -> Optional[str]:
        """
        微博视频 CDN URL 会过期：失败时用 share_url 重新抓取 post_meta，按索引取新视频链接重试。
        """
        s = str(share_url or "").strip()
        if not s:
            return None
        if s in self._weibo_meta_cache:
            post_meta = self._weibo_meta_cache[s]
        else:
            client = self._get_weibo_share_client()
            post_meta = client.get_post_meta_by_share_url(s) or {}
            if not isinstance(post_meta, dict):
                return None
            self._weibo_meta_cache[s] = post_meta

        idx = max(0, int(video_index or 0))
        candidates = post_meta.get("video_url_candidates")
        if isinstance(candidates, list) and idx < len(candidates):
            group = candidates[idx]
            if isinstance(group, list):
                for u in group:
                    if isinstance(u, str) and u.startswith("http"):
                        return u
        urls = post_meta.get("video_urls")
        if isinstance(urls, list) and idx < len(urls):
            u = urls[idx]
            if isinstance(u, str) and u.startswith("http"):
                return u
        if isinstance(fallback_url, str) and fallback_url.startswith("http"):
            return fallback_url
        return None

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
                    pages = post_meta.get("pages") if isinstance(post_meta.get("pages"), list) else []
                    media_items: List[Dict[str, Any]] = []
                    for i, u in enumerate(media_urls):
                        entry: Dict[str, Any] = {"type": "video", "url": u}
                        ref = str(post_meta.get("final_url") or "").strip()
                        if ref:
                            entry["cdn_referer"] = ref
                        bv = post_meta.get("bvid")
                        if isinstance(bv, str) and bv.strip():
                            entry["stream_bvid"] = bv.strip()
                        aid = post_meta.get("aid")
                        if aid is not None and str(aid).strip() != "":
                            entry["stream_aid"] = str(aid).strip()
                        if i < len(pages) and isinstance(pages[i], dict):
                            pcid = pages[i].get("cid")
                            if pcid is not None and str(pcid).strip() != "":
                                entry["stream_cid"] = str(pcid).strip()
                        entry["source_file"] = fp.as_posix()
                        entry["post_index"] = idx
                        entry["video_index"] = i
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
                            "image_urls": [],
                            "video_urls": media_urls,
                            "media_items": media_items,
                        }
                    )
        rows.sort(key=lambda x: (x["platform"], x["task_id"], x["post_index"]))
        return rows

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Post Review Video Review Service")
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
            bvid: Optional[str] = None,
            aid: Optional[str] = None,
            cid: Optional[str] = None,
            source_file: Optional[str] = None,
            post_index: Optional[str] = None,
            video_index: Optional[str] = None,
            share_url: Optional[str] = None,
        ):
            media_url = str(url or "").strip()
            if not (media_url.startswith("http://") or media_url.startswith("https://")):
                raise HTTPException(status_code=400, detail="invalid media url")
            netloc = (urlparse(media_url).netloc or "").lower()
            bili_cdn = task._host_looks_like_bilibili_video_cdn(netloc)
            page_ref = task._normalize_bilibili_page_referer(page_referer)
            headers: Dict[str, str] = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": request.headers.get("accept") or "*/*",
                "Accept-Language": request.headers.get("accept-language") or "zh-CN,zh;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
            }
            if bili_cdn:
                headers["Referer"] = page_ref
                headers["Origin"] = "https://www.bilibili.com"
            weibo_cdn = task._host_looks_like_weibo_video_cdn(netloc)
            if weibo_cdn and page_ref:
                headers["Referer"] = page_ref
                headers["Origin"] = "https://weibo.com"
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
            if upstream.status_code in (401, 403, 404) and (bili_cdn or weibo_cdn):
                upstream.close()
                if bili_cdn:
                    retry_headers = {
                        **headers,
                        "Referer": page_ref,
                        "Origin": "https://www.bilibili.com",
                        "Sec-Fetch-Dest": "video",
                        "Sec-Fetch-Mode": "no-cors",
                        "Sec-Fetch-Site": "cross-site",
                    }
                else:
                    retry_headers = {
                        **headers,
                        "Referer": page_ref,
                        "Origin": "https://weibo.com",
                        "Sec-Fetch-Dest": "video",
                        "Sec-Fetch-Mode": "no-cors",
                        "Sec-Fetch-Site": "cross-site",
                    }
                upstream = _open_upstream(media_url, retry_headers)

            has_ids = bool((cid or "").strip()) and (bool((bvid or "").strip()) or bool((aid or "").strip()))
            # 微博视频 CDN URL 可能已过期，先尝试用 share_url 重新拉取新链接
            if upstream.status_code not in (200, 206) and weibo_cdn and share_url:
                upstream.close()
                try:
                    refreshed = task._refresh_weibo_video_url(
                        share_url=str(share_url or "").strip(),
                        video_index=int(str(video_index or "0") or "0"),
                        fallback_url=media_url,
                    )
                except Exception:
                    refreshed = None
                if refreshed and refreshed != media_url:
                    media_url = refreshed
                    try:
                        weibo_ref = str(page_ref or "https://weibo.com/").strip()
                        refresh_headers = dict(headers)
                        refresh_headers["Referer"] = weibo_ref
                        refresh_headers["Origin"] = "https://weibo.com"
                        upstream = _open_upstream(media_url, refresh_headers)
                    except Exception as e:
                        raise HTTPException(status_code=502, detail=f"upstream refresh request failed: {e}") from e
            if upstream.status_code not in (200, 206) and bili_cdn and has_ids:
                upstream.close()
                candidates = task._bilibili_playurl_refresh_candidates(
                    page_referer=page_referer,
                    bvid=(bvid or "").strip() or None,
                    aid=(aid or "").strip() or None,
                    cid=str(cid or "").strip(),
                )
                retry_headers = {
                    **headers,
                    "Referer": page_ref,
                    "Origin": "https://www.bilibili.com",
                    "Sec-Fetch-Dest": "video",
                    "Sec-Fetch-Mode": "no-cors",
                    "Sec-Fetch-Site": "cross-site",
                }
                upstream = None
                last_status = 502
                for cand in candidates:
                    if not (cand.startswith("http://") or cand.startswith("https://")):
                        continue
                    try:
                        resp = _open_upstream(cand, retry_headers)
                    except Exception:
                        continue
                    if resp.status_code in (200, 206):
                        upstream = resp
                        break
                    last_status = resp.status_code
                    resp.close()
                if upstream is None:
                    raise HTTPException(status_code=last_status, detail="upstream response not ok after playurl refresh")
            if upstream.status_code not in (200, 206):
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
            return StreamingResponse(iter_chunks(), status_code=upstream.status_code, media_type=media_type, headers=resp_headers)

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

            js["post_review_video_review"] = {"image_marks": media_marks}
            js["post_review_video_review_status"] = "done"
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
                    "media_type": "video",
                    "media_source_path": task.media_source_path,
                },
            )

        return app

    async def do_task(self):
        logger.info(f"[{self.flag}] start video review service on http://{self.host}:{self.port}/gallery")
        logger.info(f"{self.flag}service info file: {self.server_info_file.as_posix()}")
        config = uvicorn.Config(app=self.app, host=self.host, port=self.port, reload=False, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


if __name__ == "__main__":
    pass
