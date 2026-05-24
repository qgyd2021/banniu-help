#!/usr/bin/python3
# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cacheout
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

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

from toolbox.porter.tasks.utils.post_review import PostReviewChecker
from project_settings import project_path

logger = logging.getLogger("toolbox")


# 短期 TTL 缓存：避免同一份 task json 在一次/相邻请求中被多次 IO 读出。
# - 同一条 task 走 _iter_task_indices + collect_post_rows + api_next_rows 时只读一次盘。
# - TTL 较短，保证多审核员协作场景下与磁盘状态基本一致；
#   文件被 ``api_submit_row`` move 到 target_dir 后即不会再被访问，旧缓存自然失效。
_TASK_JSON_CACHE: cacheout.Cache = cacheout.Cache(maxsize=10000, ttl=60)


@_TASK_JSON_CACHE.memoize(ttl=60)
def _read_task_json(source_file: str) -> Optional[Dict[str, Any]]:
    """读取 task json 文件并解析为 dict；失败或非 dict 返回 None。"""
    try:
        with open(source_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


class SubmitRowRequest(BaseModel):
    source_file: str
    media_marks: Optional[Dict[str, str]] = None
    approved: Optional[bool] = None
    reason: Optional[str] = ""


class NextRowsRequest(BaseModel):
    """前端按筛选条件分批拉取 row 的请求体。

    后端按 ``task_id`` 记录"首次分发给哪个 client_id"，规则：
    - 已被别的 ``client_id`` 锁定的 task，本次请求跳过（多人之间不撞车）；
    - 已锁定给当前 ``client_id`` 的 task，仍可以再次分发给它本人
      （刷新页面拿到原来的 client_id 时，刚才看到的帖子还在）；
    - 没人拿过的 task，分发并把"归属"记为当前 ``client_id``；
    - 每条记录 10 分钟 TTL，每次再次分发给同一 client 会续期；
      若被分发后该 client 长时间不再访问，自动释放给其他人。
    """

    client_id: Optional[str] = ""
    keyword: Optional[str] = ""
    product_model: Optional[str] = ""
    review_status: Optional[str] = ""
    task_status: Optional[str] = ""
    final_approved: Optional[str] = ""
    created_start: Optional[str] = ""
    created_end: Optional[str] = ""
    exclude_task_ids: Optional[List[str]] = None
    limit: Optional[int] = 2


@BaseTask.register("post_review_submit_service", exist_ok=True)
class PostReviewSubmitServiceTask(BaseTask, TaskJsonUtils):
    def __init__(
        self,
        check_interval: int = 60,
        source_dirs: List[str] = None,
        target_dir: str = "temp/banniu_37728/step_11_post_review_submit",
        templates_dir: str = "toolbox/porter/tasks/post_review_submit_service_task/templates",
        host: str = "0.0.0.0",
        port: int = 10000,
        service_registry_dir: str = "temp/banniu_37728_v2/service_registry",
        service_name: str = "post_review_submit_service",
        service_access_path: str = "",
        service_description: str = "帖子综合审核服务，展示完整帖子信息（标题、描述、作者、互动数据、图片、视频），支持审核提交。",
        post_review_checker_kwargs: Dict[str, Any] = None,
    ):
        super().__init__(flag=f"[{self.__class__.__name__}]", check_interval=check_interval)
        source_dirs = source_dirs or []
        self.source_dirs = [self.resolve_project_path(source_dir) for source_dir in source_dirs]
        self.target_dir = self.resolve_project_path(target_dir)
        self.templates_dir = self.resolve_project_path(templates_dir)
        self.host = host
        self.port = port
        self.service_registry_dir = self.resolve_project_path(service_registry_dir)
        self.service_name = str(service_name or "post_review_submit_service").strip()
        self.service_access_path = str(service_access_path or "").strip()
        self.service_description = str(service_description or "").strip()

        self.post_review_checker_kwargs = post_review_checker_kwargs or {}
        self.post_review_checker = PostReviewChecker(
            **self.post_review_checker_kwargs
        )

        self.image_stream_client_map: Dict[str, Any] = {
            "bilibili": BilibiliFreshImageUrl(),
            "weibo": WeiboFreshImageUrl(),
            "xiaohongshu": XiaoHongShuFreshImageUrl(),
            "douyin": DouyinFreshImageUrl(),
            "kuaishou": KuaishouFreshImageUrl(),
            "dewu": DewuFreshImageUrl(),
            "xiaoheihe": XiaoHeiHeFreshImageUrl(),
        }
        self.video_stream_client_map: Dict[str, Any] = {
            "bilibili": BilibiliFreshVideoUrl(),
            "weibo": WeiboFreshVideoUrl(),
            "xiaohongshu": XiaoHongShuFreshVideoUrl(),
            "douyin": DouyinFreshVideoUrl(),
            "kuaishou": KuaishouFreshVideoUrl(),
            "dewu": DewuFreshVideoUrl(),
            "xiaoheihe": XiaoHeiHeFreshVideoUrl(),
        }

        # task_id 归属记录：key = task_id，value = 首次拿到它的 client_id。
        # - 同一 client_id 可以反复拿到自己已锁定的 task（刷新后帖子还在）；
        # - 不同 client_id 之间互斥：被别人锁定的 task 不会再分发给当前请求；
        # - 每次分发会重新 set 续期，10 分钟内无续期则自动释放，避免审核员
        #   长时间挂着不操作导致 task 死锁。
        self.dispense_cache: cacheout.Cache = cacheout.Cache(maxsize=100000, ttl=600)

        self.server_info_file = self.register_service_info()

        self.app = FastAPI(title="Post Review Submit Service")
        self.templates = Jinja2Templates(directory=self.templates_dir.as_posix())
        self.add_router()

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
                "source_dirs": [source_dir.as_posix() for source_dir in self.source_dirs],
                "target_dir": self.target_dir.as_posix(),
            },
        }
        server_file = service_dir / "server.json"
        server_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return server_file

    # ------------------------------------------------------------------
    # 数据收集：
    #   - 读盘只走 ``_read_task_json`` 一个入口（带 60 秒 TTL 缓存），避免二次 IO。
    #   - ``_row_from_payload`` 仅做 dict → row dict 的字段转换，不做 IO。
    #   - ``_iter_task_indices`` 用于初次页面的下拉项；``api_next_rows`` 走流式扫描。
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_image_urls(raw: Any) -> List[str]:
        """班牛 image_urls：支持 list，或 ``;`` / ``；`` 分隔的字符串。"""
        if isinstance(raw, list):
            out: List[str] = []
            for item in raw:
                if isinstance(item, str) and item.strip().startswith("http"):
                    out.append(item.strip())
            return out
        if not isinstance(raw, str) or not raw.strip():
            return []
        parts = re.split(r"[;；\n]+", raw)
        return [p.strip() for p in parts if p.strip().startswith("http")]

    @staticmethod
    def _norm_video_urls(raw_urls: Any) -> List[Dict[str, str]]:
        """统一前端视频结构：兼容 str、dict、VideoMeta/Pydantic 对象。"""
        out: List[Dict[str, str]] = []
        for item in raw_urls or []:
            if isinstance(item, str) and item.startswith("http"):
                out.append({"video_url": item, "cover_url": ""})
            elif isinstance(item, dict):
                url = item.get("video_url") or item.get("url") or ""
                if isinstance(url, str) and url.startswith("http"):
                    cover = item.get("cover_url") or ""
                    out.append({
                        "video_url": url,
                        "cover_url": cover if isinstance(cover, str) else "",
                    })
            else:
                url = getattr(item, "video_url", "") or getattr(item, "url", "") or ""
                if isinstance(url, str) and url.startswith("http"):
                    cover = getattr(item, "cover_url", "") or ""
                    out.append({
                        "video_url": url,
                        "cover_url": cover if isinstance(cover, str) else "",
                    })
        return out

    @staticmethod
    def _final_approved_key(prf_raw: Any, post_review: PostReview) -> str:
        if isinstance(prf_raw, dict):
            approved = prf_raw.get("approved")
        else:
            approved = post_review.review_final.approved
        if approved is True:
            return "true"
        if approved is False:
            return "false"
        return "none"

    @staticmethod
    def _parse_dt(s: Optional[str]) -> Optional[float]:
        if not s:
            return None
        s = str(s).strip()
        if not s:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(s, fmt).timestamp()
            except ValueError:
                continue
        return None

    def _iter_task_indices(self) -> List[Dict[str, Any]]:
        """扫描所有 source_dir 下的 task json，按 task_id 去重后返回轻量索引。

        仅用于 ``gallery_page`` 计算筛选下拉项。
        ``api_next_rows`` 走的是不依赖此索引的流式扫描路径，无需任何缓存。

        同一个 task_id 在多个 source_dir（流水线不同 step）中可能多次出现，
        这里按 ``self.source_dirs`` 的顺序"后者覆盖前者"，保留更靠后的副本。
        """
        idx_map: Dict[str, Dict[str, Any]] = {}
        for source_dir in self.source_dirs:
            if not source_dir.exists():
                continue
            for fp in sorted(source_dir.rglob("**/*.json")):
                payload = _read_task_json(fp.as_posix())
                if not payload:
                    continue
                platform = fp.parent.name
                task_formatted = BanniuTaskFormatted.from_dict(payload.get("task_formatted"))
                task_id = task_formatted.task_id_str or ""
                if not task_id:
                    continue

                prf_raw = payload.get("post_review_final")
                try:
                    post_review = PostReview.from_dict(payload.get("post_review") or {})
                except Exception:
                    post_review = PostReview.from_dict({})
                final_key = self._final_approved_key(prf_raw, post_review)

                post_meta_raw = payload.get("post_meta") or {}
                if not isinstance(post_meta_raw, dict):
                    post_meta_raw = {}

                product_model = (task_formatted.product_model or "").strip()
                order_no = (task_formatted.order_no or "").strip()
                task_status = (task_formatted.task_status or "").strip()
                review_status = (task_formatted.review_status or "").strip()
                created_at = (task_formatted.created_at or "").strip()

                search_blob = " ".join(
                    str(x or "")
                    for x in [
                        task_id,
                        platform,
                        post_meta_raw.get("title", ""),
                        post_meta_raw.get("desc", ""),
                        post_meta_raw.get("nickname", ""),
                        post_meta_raw.get("user_id", ""),
                        post_meta_raw.get("share_url", ""),
                        product_model,
                        order_no,
                        task_status,
                        review_status,
                    ]
                ).lower()

                idx_map[task_id] = {
                    "source_file": fp.as_posix(),
                    "task_id": task_id,
                    "platform": platform,
                    "product_model": product_model,
                    "review_status": review_status,
                    "task_status": task_status,
                    "created_at": created_at,
                    "final_approved_key": final_key,
                    "search_blob": search_blob,
                }
        return list(idx_map.values())

    def _row_from_payload(
        self,
        payload: Dict[str, Any],
        fp: Path,
    ) -> Optional[Dict[str, Any]]:
        """把一份已读出的 task payload 转成模板用的 row dict。仅做字段映射，不 IO。"""
        if not isinstance(payload, dict):
            return None
        platform = fp.parent.name
        task_formatted = BanniuTaskFormatted.from_dict(payload.get("task_formatted"))
        post_meta = PostMeta.from_dict(payload.get("post_meta"))
        post_review = PostReview.from_dict(payload.get("post_review"))
        prf_raw = payload.get("post_review_final")
        if isinstance(prf_raw, dict):
            post_review_final = prf_raw
        else:
            post_review_final = post_review.review_final.model_dump()
        final_key = self._final_approved_key(prf_raw, post_review)

        purchase_info: Any = task_formatted.purchase_info or ""
        try:
            purchase_info = json.loads(purchase_info)
            purchase_info = purchase_info[0]
        except (json.decoder.JSONDecodeError, IndexError, TypeError):
            purchase_info = dict()
        if not isinstance(purchase_info, dict):
            purchase_info = dict()

        return {
            "source_file": fp.as_posix(),
            "final_approved_key": final_key,
            "banniu_data": {
                "task_id": task_formatted.task_id_str,
                "工单编号": task_formatted.order_work_no,
                "订单号": task_formatted.order_no,
                "任务状态": task_formatted.task_status,
                "流程状态": task_formatted.flow_status,
                "审核状态": task_formatted.review_status,
                "创建时间": task_formatted.created_at,
                "产品型号": task_formatted.product_model,
                "旺店通-商家编号": purchase_info.get("39400", ""),
                "旺店通-规格名称": purchase_info.get("39401", ""),
                "旺店通-商品数量": purchase_info.get("39402", ""),
                "旺店通-子货品名称": purchase_info.get("39403", ""),
                "内容链接": task_formatted.share_text,
                "image_urls": self._parse_image_urls(task_formatted.image_urls),
            },
            "post_data": {
                "platform": platform,
                "share_url": post_meta.share_url,
                "title": post_meta.title,
                "desc": post_meta.desc,
                "author_nickname": post_meta.nickname,
                "author_uid": post_meta.user_id,
                "digg_count": post_meta.liked_count,
                "comment_count": post_meta.comment_count,
                "collect_count": post_meta.collected_count,
                "share_count": post_meta.share_count,
                "image_urls": post_meta.image_urls or [],
                "video_urls": self._norm_video_urls(post_meta.video_urls),
                "image_count": len(post_meta.image_urls or []),
                "video_count": len(post_meta.video_urls or []),
                "tags": post_meta.tags or [],
            },
            "review_data": {
                "review_text": post_review.review_text.model_dump(),
                "review_duplicate": post_review.review_duplicate.model_dump(),
                "review_image": post_review.review_image.model_dump(),
                "review_video": post_review.review_video.model_dump(),
                "review_final": post_review_final,
            },
        }

    def _match_filter(
        self,
        payload: Dict[str, Any],
        task_formatted: BanniuTaskFormatted,
        platform: str,
        req: NextRowsRequest,
    ) -> bool:
        """直接对一个 task 的 payload 做筛选判断（流式扫描用，无需建索引）。"""
        product = (req.product_model or "").strip()
        if product and (task_formatted.product_model or "").strip() != product:
            return False
        review_status = (req.review_status or "").strip()
        if review_status and (task_formatted.review_status or "").strip() != review_status:
            return False
        task_status = (req.task_status or "").strip()
        if task_status and (task_formatted.task_status or "").strip() != task_status:
            return False

        start_ts = self._parse_dt(req.created_start)
        end_ts = self._parse_dt(req.created_end)
        if start_ts is not None or end_ts is not None:
            created_ts = self._parse_dt(task_formatted.created_at or "")
            if created_ts is None:
                return False
            if start_ts is not None and created_ts < start_ts:
                return False
            if end_ts is not None and created_ts > end_ts:
                return False

        final_approved = (req.final_approved or "").strip()
        if final_approved:
            prf_raw = payload.get("post_review_final")
            if isinstance(prf_raw, dict):
                approved = prf_raw.get("approved")
            else:
                pr = payload.get("post_review") or {}
                rf = pr.get("review_final") if isinstance(pr, dict) else {}
                approved = (rf or {}).get("approved") if isinstance(rf, dict) else None
            if approved is True:
                final_key = "true"
            elif approved is False:
                final_key = "false"
            else:
                final_key = "none"
            if final_key != final_approved:
                return False

        q = (req.keyword or "").strip().lower()
        if q:
            pm = payload.get("post_meta") or {}
            if not isinstance(pm, dict):
                pm = {}
            search_blob = " ".join(
                str(x or "")
                for x in [
                    task_formatted.task_id_str,
                    platform,
                    pm.get("title", ""),
                    pm.get("desc", ""),
                    pm.get("nickname", ""),
                    pm.get("user_id", ""),
                    pm.get("share_url", ""),
                    task_formatted.product_model,
                    task_formatted.order_no,
                    task_formatted.task_status,
                    task_formatted.review_status,
                ]
            ).lower()
            if q not in search_blob:
                return False
        return True

    @staticmethod
    def _uniq_index(entries: List[Dict[str, Any]], field: str) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for e in entries:
            v = str(e.get(field) or "").strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return sorted(out)

    def collect_post_rows(self) -> List[Dict[str, Any]]:
        """旧接口：构造全部完整 rows（保留作兼容外部调用入口，gallery 已不调用）。"""
        rows: List[Dict[str, Any]] = []
        for e in self._iter_task_indices():
            payload = _read_task_json(e["source_file"])
            if not payload:
                continue
            row = self._row_from_payload(payload, Path(e["source_file"]))
            if row is not None:
                rows.append(row)
        rows.sort(
            key=lambda x: (
                x["post_data"]["platform"],
                x["banniu_data"]["创建时间"],
            )
        )
        return rows

    def api_media_stream(
        self,
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
            client = self.video_stream_client_map.get(p)
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
            client = self.image_stream_client_map.get(p)
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

    def resolve_source_file(self, source_file: str) -> Path:
        """把请求里的 source_file 解析为 source_dir 之内的绝对路径，超出范围抛 400。"""
        data_root = project_path.resolve()
        raw_src = Path(source_file)
        src = (raw_src if raw_src.is_absolute() else (data_root / raw_src)).resolve()
        try:
            src.relative_to(data_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid source_file path") from exc
        return src

    @staticmethod
    def build_post_review_with_marks(
        js: Dict[str, Any],
        media_marks_raw: Optional[Dict[str, str]],
        approved: Optional[bool],
        reason: Optional[str],
    ) -> PostReview:
        """把前端传来的 media_marks / approved / reason 套到 PostReview 上，供 checker 使用或落盘。"""
        raw_marks = media_marks_raw or {}
        media_marks: Dict[str, str] = {}
        for k, v in (raw_marks or {}).items():
            if isinstance(k, str) and k:
                mark_label = "" if v is None else str(v)
                if mark_label not in ("符合", "不符合", ""):
                    mark_label = str(v)
                media_marks[k] = mark_label

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
                elif isinstance(u, dict):
                    url = u.get("video_url") or u.get("url") or ""
                    if isinstance(url, str) and url.startswith("http"):
                        video_url_set.add(url)

        image_marks: Dict[str, str] = {}
        video_marks: Dict[str, str] = {}
        for url, label in media_marks.items():
            if url in image_url_set:
                image_marks[url] = label
            elif url in video_url_set:
                video_marks[url] = label

        def _count_marks(url_set: set[str], marks: Dict[str, str]) -> tuple[int, int, int]:
            """返回 (total, check_count, cross_count)；未标记默认视为“符合”。"""
            total = len(url_set)
            cross_count = sum(1 for u in url_set if marks.get(u) == "不符合")
            check_count = total - cross_count
            return total, check_count, cross_count

        img_total, img_check, img_cross = _count_marks(image_url_set, image_marks)
        vid_total, vid_check, vid_cross = _count_marks(video_url_set, video_marks)

        post_review = PostReview.from_dict(js.get("post_review", dict()))
        post_review.review_image.total_count = img_total
        post_review.review_image.check_count = img_check
        post_review.review_image.cross_count = img_cross
        post_review.review_image.marks = image_marks

        post_review.review_video.total_count = vid_total
        post_review.review_video.check_count = vid_check
        post_review.review_video.cross_count = vid_cross
        post_review.review_video.marks = video_marks

        if approved is not None:
            post_review.review_final.approved = approved
            post_review.review_final.reply_to_user = str(reason or "").strip()

        return post_review

    def api_post_review_check(self, payload: SubmitRowRequest) -> Dict[str, Any]:
        """根据当前界面上的 marks/approved/reason，调用 PostReviewChecker 给出实时审核结果。

        与 ``api_submit_row`` 不同：本接口不写文件、不归档，仅返回是否会通过审核以及失败原因。
        """
        src = self.resolve_source_file(payload.source_file)
        if not src.exists() or not src.is_file():
            raise HTTPException(status_code=404, detail=f"source file not found: {src.as_posix()}")

        try:
            with open(src.as_posix(), "r", encoding="utf-8") as f:
                js = json.load(f)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"source file is not valid json: {exc}") from exc
        if not isinstance(js, dict):
            raise HTTPException(status_code=400, detail="source file is not valid json object")

        post_review = self.build_post_review_with_marks(
            js=js,
            media_marks_raw=payload.media_marks,
            approved=payload.approved,
            reason=payload.reason,
        )
        task_formatted = BanniuTaskFormatted.from_dict(js.get("task_formatted"))
        product_model = (task_formatted.product_model or "").strip()

        result = self.post_review_checker.predict(post_review, product_model=product_model)
        return {
            "ok": True,
            "approval": bool(result.get("approval", False)),
            "review_msg": result.get("review_msg", {}) or {},
        }

    def api_submit_row(self, payload: SubmitRowRequest) -> Dict[str, Any]:
        data_root = project_path.resolve()
        step_target_root = self.target_dir.resolve()
        src = self.resolve_source_file(payload.source_file)
        rel = src.relative_to(data_root)

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

        post_review = self.build_post_review_with_marks(
            js=js,
            media_marks_raw=payload.media_marks,
            approved=payload.approved,
            reason=payload.reason,
        )
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

    def gallery_page(self, request: Request) -> HTMLResponse:
        """渲染外壳页：仅传入筛选下拉项与是否有数据；rows 不在初次渲染时下发。"""
        entries = self._iter_task_indices()
        return self.templates.TemplateResponse(
            request=request,
            name="gallery.html",
            context={
                "has_data": bool(entries),
                "data_dir": project_path.as_posix(),
                "count": len(entries),
                "product_models": self._uniq_index(entries, "product_model"),
                "review_statuses": self._uniq_index(entries, "review_status"),
                "task_statuses": self._uniq_index(entries, "task_status"),
            },
        )

    def api_next_rows(self, payload: NextRowsRequest) -> Dict[str, Any]:
        """流式扫描 source_dirs，找到 ``limit`` 条满足筛选且可分发的 task 后立即返回。

        - 不维护全量索引/缓存，每次都直接读盘。这保证与磁盘最新状态完全一致，
          也让多审核员场景下"刚归档的 task"不会再被误下发。
        - ``self.source_dirs`` 倒序遍历：流水线后期 step 的副本（信息最全）优先；
          同一 task_id 在更早 step 中再出现时会被本次的 ``seen_tids`` 跳过。
        - ``dispense_cache`` 记录 ``task_id -> 首次拿到它的 client_id``：
            * 已属于"别的 client_id"的 task → 跳过，防止多人撞车；
            * 已属于"当前 client_id"或还没人拿过的 task → 可以分发，同时
              ``set`` 一下续期 / 落归属；
            * 因此前端刷新（只要 client_id 持久化没变）能再次看到刚才的帖子。
        - ``exclude_task_ids`` 是前端当前**屏幕上**还在的 task_id 列表：
          这些已经显示给用户了，不需要本次再下发一份（即便它属于当前 client）。
        """
        client_id = (payload.client_id or "").strip()
        if not client_id:
            raise HTTPException(status_code=400, detail="missing client_id")

        exclude = set(payload.exclude_task_ids or [])
        limit = max(1, min(int(payload.limit or 2), 20))

        row_template = self.templates.get_template("_row.html")
        rows_out: List[Dict[str, Any]] = []
        seen_tids: set = set()
        matched_scanned = 0
        stopped_early = False

        for source_dir in self.source_dirs:
            if not source_dir.exists():
                continue
            for fp in sorted(source_dir.rglob("**/*.json")):
                payload_dict = _read_task_json(fp.as_posix())
                if not payload_dict:
                    continue
                task_formatted = BanniuTaskFormatted.from_dict(payload_dict.get("task_formatted"))
                tid = task_formatted.task_id_str or ""
                if not tid or tid in seen_tids:
                    continue
                seen_tids.add(tid)

                platform = fp.parent.name
                if not self._match_filter(payload_dict, task_formatted, platform, payload):
                    continue
                matched_scanned += 1

                if tid in exclude:
                    continue

                owner = self.dispense_cache.get(tid)
                if owner and owner != client_id:
                    continue  # 已被其他 client 锁定

                row = self._row_from_payload(payload_dict, fp)
                if not row:
                    continue
                rows_out.append({
                    "task_id": tid,
                    "source_file": fp.as_posix(),
                    "platform": platform,
                    "html": row_template.render(row=row),
                })
                self.dispense_cache.set(tid, client_id)

                if len(rows_out) >= limit:
                    stopped_early = True
                    break
            if stopped_early:
                break

        reached_end = not stopped_early
        return {
            "ok": True,
            "rows": rows_out,
            "reached_end": reached_end,
            "matched_scanned": matched_scanned,
            "total_matched": matched_scanned,
            "served": len(rows_out),
        }

    def add_router(self) -> FastAPI:
        self.app.add_api_route("/", self.gallery_page, methods=["GET"], response_class=HTMLResponse)
        self.app.add_api_route("/gallery", self.gallery_page, methods=["GET"], response_class=HTMLResponse)
        self.app.add_api_route("/api/media-stream", self.api_media_stream, methods=["GET"])
        self.app.add_api_route("/api/submit-row", self.api_submit_row, methods=["POST"])
        self.app.add_api_route("/api/post-review-check", self.api_post_review_check, methods=["POST"])
        self.app.add_api_route("/api/next-rows", self.api_next_rows, methods=["POST"])
        return self.app

    async def do_task(self):
        logger.info(f"{self.flag} start post review submit service on http://{self.host}:{self.port}/gallery")
        logger.info(f"{self.flag} service info file: {self.server_info_file.as_posix()}")
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uv_logger = logging.getLogger(name)
            uv_logger.handlers = []
            for h in logging.getLogger("toolbox").handlers:
                uv_logger.addHandler(h)
            uv_logger.setLevel(logging.INFO)
            uv_logger.propagate = False

        config = uvicorn.Config(
            app=self.app, host=self.host, port=self.port,
            reload=False, log_level="info", log_config=None,
        )
        server = uvicorn.Server(config)
        await server.serve()


async def main():
    import log
    from project_settings import log_directory, time_zone_info

    log.setup_size_rotating(log_directory=log_directory, tz_info=time_zone_info)

    task = PostReviewSubmitServiceTask(
        check_interval=60,
        source_dirs=[
            "temp/banniu_39369/step_1_banniu_task_download",
            "temp/banniu_39369/step_2_post_review_router",
            "temp/banniu_39369/step_3_bilibili_share_media_download",
            "temp/banniu_39369/step_3_dewu_share_media_download",
            "temp/banniu_39369/step_3_douyin_share_media_download",
            "temp/banniu_39369/step_3_kuaishou_share_media_download",
            "temp/banniu_39369/step_3_weibo_share_media_download",
            "temp/banniu_39369/step_3_xiaoheihe_share_media_download",
            "temp/banniu_39369/step_3_xiaohongshu_share_media_download",
            "temp/banniu_39369/step_4_post_review_duplicate_review",
            "temp/banniu_39369/step_5_1_post_review_text_emotion_review",
            "temp/banniu_39369/step_5_2_post_review_text_length_review",
            "temp/banniu_39369/step_5_3_post_review_text_tags_review",
            "temp/banniu_39369/step_6_post_review_submit",
            "temp/banniu_39369/step_7_post_review_final",
            "temp/banniu_39369/step_8_finished",
        ],
        target_dir="temp/banniu_39369/step_6_post_review_submit",
        templates_dir="toolbox/porter/tasks/post_review_submit_service_task/templates",
        host="0.0.0.0",
        port=18001,
        service_registry_dir="temp/banniu_39369/service_registry",
        post_review_checker_kwargs={
            "positive_emotion_labels": ["积极"],
            "min_total_text_length": 30,
            "required_tags": ["迈从"],
            "min_image_count": 3,
            "max_image_cross_rate": 0.4,
            "min_video_count": 1,
            "max_video_cross_rate": 0.5
        }
    )
    await task.do_task()


if __name__ == "__main__":
    asyncio.run(main())
