#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
批量补全 task json 中旧版 post_meta 的 unique_id（抖音号 / 小红书号）。

旧数据特征：post_meta 中没有 unique_id 字段。
通过各平台 homepage.user_info 拉取 user_meta，写回 post_meta。
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional

project_path = os.path.abspath("../")
project_path = Path(project_path)
sys.path.append(project_path.as_posix())

from toolbox.douyin.homepage.user_info import UserInfo as DouyinUserInfo
from toolbox.xiaohongshu.homepage.user_info import UserInfo as XiaohongshuUserInfo

logger = logging.getLogger("toolbox")

SUPPORTED_PLATFORMS = ("douyin", "xiaohongshu")


def is_legacy_post_meta(post_meta: Dict[str, Any]) -> bool:
    return "unique_id" not in post_meta


def resolve_author_user_id(platform: str, post_meta: Dict[str, Any]) -> str:
    author_user_id = str(post_meta.get("author_user_id") or "").strip()
    if author_user_id:
        return author_user_id
    if platform == "xiaohongshu":
        return str(post_meta.get("user_id") or "").strip()
    return ""


def fetch_user_meta(platform: str, post_meta: Dict[str, Any], client: Any) -> Optional[Dict[str, Any]]:
    if platform == "douyin":
        sec_user_id = str(post_meta.get("sec_user_id") or "").strip()
        author_user_id = resolve_author_user_id(platform, post_meta)
        if sec_user_id:
            return client.get_user_meta_by_sec_uid(sec_user_id)
        if author_user_id:
            return client.get_user_meta_by_author_user_id(author_user_id)
        return None

    if platform == "xiaohongshu":
        author_user_id = resolve_author_user_id(platform, post_meta)
        if not author_user_id:
            return None
        return client.get_user_meta_by_author_user_id(author_user_id)

    raise ValueError(f"unsupported platform: {platform}")


def apply_user_meta_to_post_meta(platform: str, post_meta: Dict[str, Any], user_meta: Dict[str, Any]) -> Dict[str, Any]:
    unique_id = str(user_meta.get("unique_id") or "").strip()
    if unique_id:
        post_meta["unique_id"] = unique_id
        post_meta["user_id"] = unique_id

    author_user_id = str(user_meta.get("author_user_id") or "").strip()
    if author_user_id:
        post_meta["author_user_id"] = author_user_id

    nickname = str(user_meta.get("nickname") or "").strip()
    if nickname:
        post_meta["nickname"] = nickname

    if platform == "douyin":
        sec_uid = str(user_meta.get("sec_uid") or "").strip()
        if sec_uid:
            post_meta["sec_user_id"] = sec_uid
        short_id = str(user_meta.get("short_id") or "").strip()
        if short_id:
            post_meta["short_id"] = short_id

    return post_meta


def create_user_info_client(platform: str) -> Any:
    if platform == "douyin":
        return DouyinUserInfo()
    if platform == "xiaohongshu":
        return XiaohongshuUserInfo()
    raise ValueError(f"unsupported platform: {platform}")


def iter_task_json_files(task_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.json" if recursive else "*.json"
    return sorted(p for p in task_dir.glob(pattern) if p.is_file())


def update_task_file(task_file: Path, platform: str, client: Any, dry_run: bool) -> bool:
    payload = json.loads(task_file.read_text(encoding="utf-8-sig"))
    post_meta = payload.get("post_meta")
    if not isinstance(post_meta, dict):
        logger.info("skip (no post_meta): %s", task_file)
        return False
    if not is_legacy_post_meta(post_meta):
        logger.info("skip (already has unique_id): %s", task_file)
        return False

    user_meta = fetch_user_meta(platform, post_meta, client)
    if not user_meta:
        logger.warning("skip (user_meta fetch failed): %s", task_file)
        return False

    updated_post_meta = apply_user_meta_to_post_meta(platform, dict(post_meta), user_meta)
    payload["post_meta"] = updated_post_meta

    logger.info(
        "update %s: author_user_id=%s unique_id=%s",
        task_file,
        updated_post_meta.get("author_user_id"),
        updated_post_meta.get("unique_id"),
    )
    if dry_run:
        return True

    task_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> None:
    """
    python3 update_task_file.py --platform xiaohongshu --task_dir /code/temp/banniu_39369/step_5_4_post_review_image_item_review --dry-run


    :return:
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="补全 task json 中旧版 post_meta 的 unique_id")
    parser.add_argument("platform", choices=SUPPORTED_PLATFORMS, help="平台：douyin / xiaohongshu")
    parser.add_argument("task_dir", help="task json 所在目录")
    parser.add_argument("--recursive", action="store_true", help="递归遍历子目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写回文件")
    args = parser.parse_args()

    task_dir = Path(args.task_dir).resolve()
    if not task_dir.is_dir():
        raise SystemExit(f"目录不存在: {task_dir}")

    client = create_user_info_client(args.platform)
    task_files = iter_task_json_files(task_dir, args.recursive)
    if not task_files:
        logger.info("目录下无 json 文件: %s", task_dir)
        return

    updated = 0
    for task_file in task_files:
        if update_task_file(task_file, args.platform, client, args.dry_run):
            updated += 1

    logger.info("done: scanned=%s updated=%s dry_run=%s", len(task_files), updated, args.dry_run)


if __name__ == "__main__":
    main()
