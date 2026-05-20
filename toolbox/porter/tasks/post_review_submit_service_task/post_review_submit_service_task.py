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
from toolbox.porter.tasks.base_task import BaseTask, TaskJsonUtils
from toolbox.porter.entity.banniu_task import BanniuTaskFormatted
from toolbox.porter.entity.post_meta import PostMeta
from toolbox.porter.entity.post_review import PostReview
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
class PostReviewSubmitServiceTask(BaseTask, TaskJsonUtils):
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
        service_registry_dir: str = "temp/banniu_37728_v2/service_registry",
        service_name: str = "post_review_submit_service",
        service_access_path: str = "",
        service_description: str = "帖子综合审核服务，展示完整帖子信息（标题、描述、作者、互动数据、图片、视频），支持审核提交。",
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        self.source_dir = self.resolve_project_path(source_dir)
        self.target_dir = self.resolve_project_path(target_dir)
        self.templates_dir = self.resolve_project_path(templates_dir)
        self.host = host
        self.port = port
        self.service_registry_dir = self.resolve_project_path(service_registry_dir)
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

        self.server_info_file = self.register_service_info()
        self.app = self._build_app()

    def register_service_info(self) -> Path:
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

    def collect_post_rows(self) -> List[Dict[str, Any]]:
        if not self.source_dir.exists():
            return []

        rows: List[Dict[str, Any]] = []
        for fp in sorted(self.source_dir.rglob("*.json")):
            with open(fp.as_posix(), "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                continue

            platform = fp.parent.name

            task_formatted = payload.get("task_formatted")
            task_formatted = BanniuTaskFormatted.from_dict(task_formatted)
            post_meta = payload.get("post_meta")
            post_meta = PostMeta.from_dict(post_meta)
            post_review = payload.get("post_review")
            post_review = PostReview.from_dict(post_review)

            prf_raw = payload.get("post_review_final")
            if isinstance(prf_raw, dict):
                post_review_final = prf_raw
            else:
                post_review_final = post_review.review_final.model_dump()

            approved = post_review_final.get("approved")
            if approved is True:
                final_approved_key = "true"
            elif approved is False:
                final_approved_key = "false"
            else:
                final_approved_key = "none"

            row = {
                "task_id": task_formatted.task_id_str,
                "platform": platform,
                "source_file": fp.as_posix(),
                "product_model": task_formatted.product_model or "",
                "created_at": task_formatted.created_at or "",
                "review_status": task_formatted.review_status or "",
                "task_status": task_formatted.task_status or "",
                "flow_status": task_formatted.flow_status or "",
                "final_approved_key": final_approved_key,
                "share_url": post_meta.share_url,
                "title": post_meta.title,
                "desc": post_meta.desc,
                "author_nickname": post_meta.nickname,
                "author_uid": post_meta.user_id,
                "review_text": post_review.review_text.model_dump(),
                "review_duplicate": post_review.review_duplicate.model_dump(),
                "review_image": post_review.review_image.model_dump(),
                "review_video": post_review.review_video.model_dump(),
                "review_final": post_review.review_final.model_dump(),
                "digg_count": post_meta.liked_count,
                "comment_count": post_meta.comment_count,
                "collect_count": post_meta.collected_count,
                "share_count": post_meta.share_count,
                "image_urls": post_meta.image_urls,
                "video_urls": post_meta.video_urls,
                "image_count": len(post_meta.image_urls),
                "video_count": len(post_meta.video_urls),
            }
            rows.append(row)

        rows.sort(key=lambda x: (x["platform"], x["task_id"]))
        return rows

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Post Review Submit Service")
        templates = Jinja2Templates(directory=self.templates_dir.as_posix())
        task = self

        class SubmitRowRequest(BaseModel):
            source_file: str
            media_marks: Optional[Dict[str, str]] = None
            # 仅随「保存图片/视频标注」一并提交；不能单独用这两项归档。
            approved: Optional[bool] = None
            reason: Optional[str] = ""

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
            data_root = task.source_dir.resolve()
            step_target_root = task.target_dir.resolve()
            raw_src = Path(payload.source_file)
            src = (raw_src if raw_src.is_absolute() else (data_root / raw_src)).resolve()
            try:
                rel = src.relative_to(data_root)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid source_file path") from exc

            target = step_target_root / rel

            # 用「是否为 None」区分：未传 media_marks 键则为 None。
            do_media = payload.media_marks is not None
            if not do_media:
                raise HTTPException(status_code=400, detail="请提交 media_marks（保存图片/视频标注）")

            # 仅在「源文件已不存在」时视为已归档；避免目标目录残留同名文件导致无法保存标注。
            if not src.exists() or not src.is_file():
                if target.exists() and target.is_file():
                    return {
                        "ok": True,
                        "already_submitted": True,
                        "source_file": src.as_posix(),
                        "target_file": target.as_posix(),
                    }
                raise HTTPException(status_code=404, detail=f"source file not found: {src.as_posix()}")

            try:
                with open(src.as_posix(), "r", encoding="utf-8") as f:
                    js = json.load(f)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"source file is not valid json: {exc}") from exc
            if not isinstance(js, dict):
                raise HTTPException(status_code=400, detail="source file is not valid json object")

            raw_marks = payload.media_marks or {}
            media_marks: Dict[str, str] = {}
            for k, v in (raw_marks or {}).items():
                if isinstance(k, str) and k:
                    mark_label = "" if v is None else str(v)
                    if mark_label not in ("符合", "不符合", ""):
                        mark_label = str(v)
                    media_marks[k] = mark_label

            # 基于文件内 post_meta 的媒体清单，把 marks 拆分到图片/视频字段中，保持与 pretty 任务一致的结构。
            image_url_set: set[str] = set()
            video_url_set: set[str] = set()

            top_post_meta = js.get("post_meta")
            if not isinstance(top_post_meta, dict):
                raise HTTPException(status_code=400, detail="missing top-level post_meta")
            if isinstance(top_post_meta.get("image_urls"), list):
                for u in top_post_meta.get("image_urls") or []:
                    if isinstance(u, str) and u.startswith("http"):
                        image_url_set.add(u)
            if isinstance(top_post_meta.get("video_urls"), list):
                for u in top_post_meta.get("video_urls") or []:
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

            # 将提交标记写回 post_review.review_image / post_review.review_video
            # 风格参考 post_review_text_tags_review_task.py：PostReview.from_dict → 修改字段 → to_dict 回写。
            post_review = PostReview.from_dict(js.get("post_review", dict()))

            def _count_marks(url_set: set[str], marks: Dict[str, str]) -> tuple[int, int, int]:
                """返回 (total, check_count, cross_count)；未标记默认视为“符合”。"""
                total = len(url_set)
                cross_count = 0
                for u in url_set:
                    if marks.get(u) == "不符合":
                        cross_count += 1
                check_count = total - cross_count
                return total, check_count, cross_count

            img_total, img_check, img_cross = _count_marks(image_url_set, image_marks)
            vid_total, vid_check, vid_cross = _count_marks(video_url_set, video_marks)

            post_review.review_image.total_count = img_total
            post_review.review_image.check_count = img_check
            post_review.review_image.cross_count = img_cross
            post_review.review_image.marks = image_marks

            post_review.review_video.total_count = vid_total
            post_review.review_video.check_count = vid_check
            post_review.review_video.cross_count = vid_cross
            post_review.review_video.marks = video_marks

            if payload.approved is not None:
                post_review.review_final.approved = payload.approved
                post_review.review_final.reply_to_user = str(payload.reason or "").strip()

            js["post_review"] = post_review.to_dict()

            src.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src.as_posix(), target.as_posix())
            return {
                "ok": True,
                "moved": True,
                "saved_media": True,
                "saved_review_final": payload.approved is not None,
                "source_file": src.as_posix(),
                "target_file": target.as_posix(),
            }

        @app.get("/", response_class=HTMLResponse)
        @app.get("/gallery", response_class=HTMLResponse)
        def gallery_page(request: Request) -> HTMLResponse:
            rows = task.collect_post_rows()

            def _uniq(field: str) -> List[str]:
                seen: set[str] = set()
                out: List[str] = []
                for r in rows:
                    s = str(r.get(field) or "").strip()
                    if s and s not in seen:
                        seen.add(s)
                        out.append(s)
                return sorted(out)

            return templates.TemplateResponse(
                request=request,
                name="gallery.html",
                context={
                    "rows": rows,
                    "data_dir": task.source_dir.as_posix(),
                    "count": len(rows),
                    "product_models": _uniq("product_model"),
                    "review_statuses": _uniq("review_status"),
                    "task_statuses": _uniq("task_status"),
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
        source_dir="temp/banniu_37728_v2/step_5_3_post_review_text_tags_review",
        target_dir="temp/banniu_37728_v2/step_6_post_review_submit",
        templates_dir="toolbox/porter/tasks/post_review_submit_service_task/templates",
        host="0.0.0.0",
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
