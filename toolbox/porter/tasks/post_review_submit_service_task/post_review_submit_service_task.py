#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from project_settings import project_path
from toolbox.porter.tasks.base_task import BaseTask
from toolbox.bilibili.utils.fresh_media_url import FreshImageUrl as BilibiliFreshImageUrl
from toolbox.weibo.utils.fresh_media_url import FreshImageUrl as WeiboFreshImageUrl
from toolbox.xiaohongshu.utils.fresh_media_url import FreshImageUrl as XiaoHongShuFreshImageUrl
from toolbox.douyin.utils.fresh_media_url import FreshImageUrl as DouyinFreshImageUrl
from toolbox.kuaishou.utils.fresh_media_url import FreshImageUrl as KuaishouFreshImageUrl
from toolbox.dewu.utils.fresh_media_url import FreshImageUrl as DewuFreshImageUrl
from toolbox.xiaoheihe.utils.fresh_media_url import FreshImageUrl as XiaoHeiHeFreshImageUrl

from toolbox.bilibili.utils.fresh_media_url import FreshVideoUrl as BilibiliFreshVideoUrl
from toolbox.weibo.utils.fresh_media_url import FreshVideoUrl as WeiboFreshVideoUrl
from toolbox.xiaohongshu.utils.fresh_media_url import FreshVideoUrl as XiaoHongShuFreshVideoUrl
from toolbox.douyin.utils.fresh_media_url import FreshVideoUrl as DouyinFreshVideoUrl
from toolbox.kuaishou.utils.fresh_media_url import FreshVideoUrl as KuaishouFreshVideoUrl
from toolbox.dewu.utils.fresh_media_url import FreshVideoUrl as DewuFreshVideoUrl
from toolbox.xiaoheihe.utils.fresh_media_url import FreshVideoUrl as XiaoHeiHeFreshVideoUrl

logger = logging.getLogger("toolbox")


@BaseTask.register("post_review_submit_service")
class PostReviewSubmitServiceTask(BaseTask):
    """帖子综合信息展示与审核提交服务。

    将图片审核、视频审核的流程合并为一个综合审核页面，
    让审核人员可以在一页上看到帖子的完整信息（标题、描述、作者、
    点赞/评论/收藏/分享数、图片、视频等），直观判断帖子是否通过或被拒。
    """

    def __init__(
        self,
        check_interval: int = 60,
        source_dir: str = "temp/banniu_37728/step_10_post_review_video_review",
        target_dir: str = "temp/banniu_37728/step_11_post_review_submit",
        templates_dir: str = "toolbox/porter/tasks/post_review_submit_service_task/templates",
        host: str = "0.0.0.0",
        port: int = 10000,
        service_registry_dir: str = "temp/service_registry",
        service_name: str = "post_review_submit_service",
        service_access_path: str = "",
        service_description: str = "帖子综合审核服务，展示完整帖子信息（标题、描述、作者、互动数据、图片、视频），支持审核提交。",
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self._resolve_project_path(source_dir)
        self.target_dir = self._resolve_project_path(target_dir)
        self.templates_dir = self._resolve_project_path(templates_dir)
        self.host = host
        self.port = port
        self.service_registry_dir = self._resolve_project_path(service_registry_dir)
        self.service_name = str(service_name or "post_review_submit_service").strip()
        self.service_access_path = str(service_access_path or "").strip()
        self.service_description = str(service_description or "").strip()

        self._image_clients: Dict[str, Any] = {
            "bilibili": BilibiliFreshImageUrl(),
            "weibo": WeiboFreshImageUrl(),
            "xiaohongshu": XiaoHongShuFreshImageUrl(),
            "douyin": DouyinFreshImageUrl(),
            "kuaishou": KuaishouFreshImageUrl(),
            "dewu": DewuFreshImageUrl(),
            "xiaoheihe": XiaoHeiHeFreshImageUrl(),
        }
        self._video_clients: Dict[str, Any] = {
            "bilibili": BilibiliFreshVideoUrl(),
            "weibo": WeiboFreshVideoUrl(),
            "xiaohongshu": XiaoHongShuFreshVideoUrl(),
            "douyin": DouyinFreshVideoUrl(),
            "kuaishou": KuaishouFreshVideoUrl(),
            "dewu": DewuFreshVideoUrl(),
            "xiaoheihe": XiaoHeiHeFreshVideoUrl(),
        }

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
            "service_type": "post_review_submit_service",
            "service_access_path": access_path,
            "description": self.service_description,
            "meta": {
                "source_dir": self.source_dir.as_posix(),
                "target_dir": self.target_dir.as_posix(),
            },
        }
        server_file = service_dir / "server.json"
        server_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return server_file

    def _collect_post_rows(self) -> List[Dict[str, Any]]:
        """收集所有帖子数据，整理成前端需要的结构。"""
        if not self.source_dir.exists():
            return []

        def _pick_score(payload_obj: Dict[str, Any], field_key: str) -> Optional[float]:
            """仅从 post_review_get_*_score.score 取分（不从 task_formatted 回退）。"""
            raw = payload_obj.get(field_key)
            if isinstance(raw, dict):
                # 对于明确旁路/无内容的情况，不展示为 0，统一视为“无分数”。
                if field_key == "post_review_get_video_score":
                    status = str(payload_obj.get("post_review_video_review_status") or "")
                    video_count = raw.get("video_count")
                    if (isinstance(video_count, int) and video_count <= 0) or status.startswith("bypass") or status.startswith("bypassed"):
                        return None
                if field_key == "post_review_get_image_score":
                    image_count = raw.get("image_count")
                    if isinstance(image_count, int) and image_count <= 0:
                        return None

                score = raw.get("score")
                if isinstance(score, (int, float)):
                    return float(score)
                if isinstance(score, str):
                    try:
                        return float(score.strip())
                    except Exception:
                        pass
            return None

        rows: List[Dict[str, Any]] = []
        for fp in sorted(self.source_dir.rglob("*.json")):
            payload = self._safe_read_json(fp)
            if not isinstance(payload, dict):
                continue

            task_id = str(payload.get("task_id") or fp.stem)
            platform = fp.parent.name

            # 提取 task_formatted 中的关键字段
            task_formatted = payload.get("task_formatted") or {}
            post_title = str(task_formatted.get("标题") or task_formatted.get("title") or "")
            post_desc = str(task_formatted.get("描述") or task_formatted.get("desc") or "")
            author = str(task_formatted.get("创建人") or task_formatted.get("author") or "")
            product_model = str(task_formatted.get("产品型号") or task_formatted.get("product_model") or "")
            activity_desc = str(task_formatted.get("活动简介") or task_formatted.get("activity_desc") or "")

            text_score = _pick_score(payload, "post_review_get_text_score")
            image_score = _pick_score(payload, "post_review_get_image_score")
            video_score = _pick_score(payload, "post_review_get_video_score")

            post_meta_entries: List[Dict[str, Any]] = []
            for key, value in payload.items():
                if not (str(key).endswith("_post_meta_list") and isinstance(value, list) and value):
                    continue
                for idx, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    post_meta_entries.append({"post_index": idx, "item": item})

            if not post_meta_entries:
                continue

            for entry in post_meta_entries:
                idx = int(entry["post_index"])
                item = entry["item"]

                post_meta = item.get("post_meta") or {}
                interact_info = post_meta.get("interact_info") or {}
                author_info = post_meta.get("author") or {}

                share_url = str(item.get("share_url") or post_meta.get("share_url") or "").strip()
                post_title_from_meta = str(post_meta.get("title") or post_meta.get("desc") or "").strip()
                post_desc_from_meta = str(post_meta.get("desc") or "").strip()
                post_author_nickname = str(author_info.get("nickname") or author_info.get("name") or "")
                post_author_uid = str(author_info.get("uid") or author_info.get("sec_uid") or "")

                digg_count = interact_info.get("digg_count") or 0
                comment_count = interact_info.get("comment_count") or 0
                collect_count = interact_info.get("collect_count") or 0
                share_count = interact_info.get("share_count") or 0

                image_urls = []
                if isinstance(post_meta.get("image_urls"), list):
                    image_urls = [u for u in post_meta["image_urls"] if isinstance(u, str) and u.startswith("http")]
                if not image_urls and isinstance(post_meta.get("image_url_candidates"), list):
                    for candidates in post_meta["image_url_candidates"]:
                        if isinstance(candidates, list) and candidates:
                            first_url = candidates[0]
                            if isinstance(first_url, str) and first_url.startswith("http"):
                                image_urls.append(first_url)

                video_urls = []
                if isinstance(post_meta.get("video_urls"), list):
                    video_urls = [u for u in post_meta["video_urls"] if isinstance(u, str) and u.startswith("http")]

                media_type = "video" if video_urls else ("image" if image_urls else "unknown")

                rows.append({
                    "task_id": task_id,
                    "platform": platform,
                    "source_file": fp.as_posix(),
                    "post_index": idx,
                    "share_url": share_url,
                    "title": post_title_from_meta or post_title,
                    "desc": post_desc_from_meta or post_desc,
                    "author_nickname": post_author_nickname,
                    "author_uid": post_author_uid,
                    "author": author,
                    "product_model": product_model,
                    "activity_desc": activity_desc,
                    "text_score": text_score,
                    "image_score": image_score,
                    "video_score": video_score,
                    "digg_count": digg_count,
                    "comment_count": comment_count,
                    "collect_count": collect_count,
                    "share_count": share_count,
                    "image_urls": image_urls,
                    "video_urls": video_urls,
                    "media_type": media_type,
                    "image_count": len(image_urls),
                    "video_count": len(video_urls),
                })

        rows.sort(key=lambda x: (x["platform"], x["task_id"], x["post_index"]))
        return rows

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Post Review Submit Service")
        templates = Jinja2Templates(directory=self.templates_dir.as_posix())
        task = self

        class SubmitRowRequest(BaseModel):
            source_file: str
            media_marks: Optional[Dict[str, str]] = None

        @app.get("/api/media-stream")
        def api_media_stream(
            request: Request,
            url: str,
            platform: str,
            share_url: Optional[str] = None,
            image_index: Optional[str] = None,
            video_index: Optional[str] = None,
            media_type: str = "image",
        ):
            """代理拉取图片或视频，根据平台调用对应的 FreshImageUrl/FreshVideoUrl 实现。"""
            media_url = str(url or "").strip()
            if not (media_url.startswith("http://") or media_url.startswith("https://")):
                raise HTTPException(status_code=400, detail="invalid media url")

            p = str(platform or "").strip().lower()
            m_type = str(media_type or "image").strip().lower()

            if m_type == "video":
                client = task._video_clients.get(p)
                if not client:
                    raise HTTPException(status_code=400, detail=f"unsupported platform for video: {platform}")
                vid_idx = int(str(video_index or "0") or "0")
                share = str(share_url or "").strip()
                try:
                    response = client.ensure_video_url(
                        video_url=media_url,
                        video_index=vid_idx,
                        share_url=share,
                    )
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"upstream request failed: {e}") from e
                media_type_out = response.headers.get("Content-Type") or "video/mp4"
            else:
                client = task._image_clients.get(p)
                if not client:
                    raise HTTPException(status_code=400, detail=f"unsupported platform for image: {platform}")
                img_idx = int(str(image_index or "0") or "0")
                share = str(share_url or "").strip()
                try:
                    response = client.ensure_image_url(
                        image_url=media_url,
                        image_index=img_idx,
                        share_url=share,
                    )
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"upstream request failed: {e}") from e
                media_type_out = response.headers.get("Content-Type") or "image/jpeg"

            if response.status_code not in (200, 206):
                response.close()
                raise HTTPException(status_code=response.status_code, detail="upstream response not ok")

            def iter_chunks():
                try:
                    for chunk in response.raw.stream(1024 * 128, decode_content=False):
                        if chunk:
                            yield chunk
                finally:
                    response.close()

            resp_headers = {"Accept-Ranges": response.headers.get("Accept-Ranges", "bytes")}
            for key in ("Content-Type", "Content-Length", "Content-Range", "Cache-Control", "ETag", "Last-Modified"):
                value = response.headers.get(key)
                if value:
                    resp_headers[key] = value
            return StreamingResponse(
                iter_chunks(), status_code=response.status_code, media_type=media_type_out, headers=resp_headers
            )

        @app.post("/api/submit-row")
        def api_submit_row(payload: SubmitRowRequest) -> Dict[str, Any]:
            """提交审核结果，将任务文件移动到 target_dir。"""
            data_root = task.source_dir.resolve()
            step_target_root = task.target_dir.resolve()
            raw_src = Path(payload.source_file)
            src = (raw_src if raw_src.is_absolute() else (data_root / raw_src)).resolve()
            try:
                rel = src.relative_to(data_root)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid source_file path") from exc

            target = step_target_root / rel
            if target.exists() and target.is_file():
                return {"ok": True, "already_submitted": True, "source_file": src.as_posix(), "target_file": target.as_posix()}

            if not src.exists() or not src.is_file():
                raise HTTPException(status_code=404, detail=f"source file not found: {src.as_posix()}")

            js = task._safe_read_json(src)
            if not isinstance(js, dict):
                raise HTTPException(status_code=400, detail="source file is not valid json object")

            raw_marks = payload.media_marks or {}
            media_marks: Dict[str, str] = {}
            for k, v in raw_marks.items():
                if isinstance(k, str) and k:
                    mark_label = "" if v is None else str(v)
                    if mark_label not in ("符合", "不符合", ""):
                        mark_label = str(v)
                    media_marks[k] = mark_label

            # 基于文件内 post_meta 的媒体清单，把 marks 拆分到图片/视频字段中，保持与 pretty 任务一致的结构。
            image_url_set: set[str] = set()
            video_url_set: set[str] = set()
            for key, value in js.items():
                if not (isinstance(key, str) and key.endswith("_post_meta_list") and isinstance(value, list)):
                    continue
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    post_meta = item.get("post_meta") if isinstance(item.get("post_meta"), dict) else {}
                    if isinstance(post_meta.get("image_urls"), list):
                        for u in post_meta.get("image_urls") or []:
                            if isinstance(u, str) and u.startswith("http"):
                                image_url_set.add(u)
                    if isinstance(post_meta.get("video_urls"), list):
                        for u in post_meta.get("video_urls") or []:
                            if isinstance(u, str) and u.startswith("http"):
                                video_url_set.add(u)

            image_marks: Dict[str, str] = {}
            video_marks: Dict[str, str] = {}
            for url, label in media_marks.items():
                if url in image_url_set:
                    image_marks[url] = label
                elif url in video_url_set:
                    video_marks[url] = label
                else:
                    pass

            js["post_review_submit"] = {
                "image_marks": image_marks,
                "video_marks": video_marks,
            }
            js["post_review_submit_status"] = "done"

            src.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src.as_posix(), target.as_posix())
            return {"ok": True, "source_file": src.as_posix(), "target_file": target.as_posix()}

        @app.get("/", response_class=HTMLResponse)
        @app.get("/gallery", response_class=HTMLResponse)
        def gallery_page(request: Request) -> HTMLResponse:
            rows = task._collect_post_rows()
            return templates.TemplateResponse(
                request=request,
                name="gallery.html",
                context={
                    "rows": rows,
                    "data_dir": task.source_dir.as_posix(),
                    "count": len(rows),
                },
            )

        return app

    async def do_task(self):
        logger.info(f"[{self.flag}] start post review submit service on http://{self.host}:{self.port}/gallery")
        logger.info(f"{self.flag} service info file: {self.server_info_file.as_posix()}")
        config = uvicorn.Config(app=self.app, host=self.host, port=self.port, reload=False, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


async def main():
    task = PostReviewSubmitServiceTask(
        check_interval=60,
        source_dir="temp/banniu_37728/step_14_finished",
        target_dir="temp/banniu_37728/step_14_finished2",
        templates_dir="toolbox/porter/tasks/post_review_submit_service_task/templates",
        host="127.0.0.1",
        port=8001,
        service_registry_dir="temp/service_registry",
        service_name="post_review_submit_service",
        service_access_path="",
        service_description="帖子综合审核服务，展示完整帖子信息（标题、描述、作者、互动数据、图片、视频），支持审核提交。",
    )
    await task.do_task()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        # 避免 Windows Proactor 在客户端中断连接时输出大量 connection_lost 噪声异常栈。
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
