#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from toolbox.bilibili.media.share_download_base import BilibiliShareDownloadBase


class ShareOpusDownload(BilibiliShareDownloadBase):
    @staticmethod
    def get_share_url_by_share_text(text: str) -> str:
        patterns = [
            r"https?://b23\.tv/[A-Za-z0-9]+(?:\?[^\s]*)?",
            r"https?://(?:www\.)?bilibili\.com/opus/\d+(?:\?[^\s]*)?",
            r"https?://t\.bilibili\.com/\d+(?:\?[^\s]*)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise AssertionError(f"no opus/b23/t.bilibili share url found; text: {text}")

    @staticmethod
    def get_opus_id_from_url(url: str) -> Optional[str]:
        match = re.search(r"bilibili\.com/opus/(\d+)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"t\.bilibili\.com/(\d+)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _fetch_dynamic_detail_state(self, opus_id: str) -> Dict[str, Any]:
        js = self.get_web_dynamic(opus_id)
        item = js["data"]["item"]
        if not item:
            raise AssertionError(f"dynamic detail api returned empty item; opus_id: {opus_id}")

        # author = item["modules"]["author"]
        dynamic = item["modules"]["module_dynamic"]
        major = dynamic["major"]
        desc = dynamic["desc"]

        return self._dynamic_item_to_initial_state(item)

    @staticmethod
    def _dynamic_desc_to_paragraph(desc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        if isinstance(desc, dict):
            for node in desc.get("rich_text_nodes") or []:
                if not isinstance(node, dict):
                    continue
                piece = node.get("orig_text") or node.get("text")
                if piece:
                    nodes.append({"type": "TEXT_NODE_TYPE_RICH", "rich": {"orig_text": piece}})
            text = desc.get("text")
            if not nodes and isinstance(text, str) and text:
                nodes.append({"type": "TEXT_NODE_TYPE_WORD", "word": {"words": text}})
        return {"text": {"nodes": nodes}}

    @staticmethod
    def _dynamic_item_to_initial_state(item: Dict[str, Any]) -> Dict[str, Any]:
        modules = item.get("modules") or {}
        author = modules.get("module_author") or {}
        dynamic = modules.get("module_dynamic") or {}
        major = dynamic.get("major") or {}

        paragraph = ShareOpusDownload._dynamic_desc_to_paragraph(dynamic.get("desc"))
        draw = major.get("draw") or {}
        if isinstance(draw.get("items"), list):
            paragraph["pics"] = draw.get("items") or []

        detail_modules: List[Dict[str, Any]] = [
            {"module_type": "MODULE_TYPE_AUTHOR", "module_author": author},
            {"module_type": "MODULE_TYPE_CONTENT", "module_content": {"paragraphs": [paragraph], "major": major}},
            {"module_type": "MODULE_TYPE_STAT", "module_stat": modules.get("module_stat") or {}},
        ]

        return {
            "detail": {
                "basic": item.get("basic") or {},
                "id_str": item.get("id_str") or "",
                "modules": detail_modules,
            }
        }

    @staticmethod
    def _node_to_text(node: Dict[str, Any]) -> str:
        if not isinstance(node, dict):
            return ""
        node_type = node.get("type")
        if node_type == "TEXT_NODE_TYPE_WORD":
            word = node.get("word") or {}
            return str(word.get("words") or "")
        if node_type == "TEXT_NODE_TYPE_RICH":
            rich = node.get("rich") or {}
            return str(rich.get("orig_text") or rich.get("text") or "")
        return ""

    def paragraph_to_text_and_images(self, paragraph: Dict[str, Any]) -> Tuple[str, List[str]]:
        texts: List[str] = []
        images: List[str] = []

        text_block = paragraph.get("text") or {}
        for node in text_block.get("nodes") or []:
            if isinstance(node, dict):
                piece = self._node_to_text(node)
                if piece:
                    texts.append(piece)

        for key in ("pics", "images", "pic_list"):
            block = paragraph.get(key)
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, dict):
                        url = self._dig_image_url(item)
                        if url:
                            images.append(url)

        pic = paragraph.get("pic")
        if isinstance(pic, dict):
            url = self._dig_image_url(pic)
            if url:
                images.append(url)

        return "".join(texts), images

    @staticmethod
    def _dig_image_url(obj: Dict[str, Any]) -> Optional[str]:
        if not isinstance(obj, dict):
            return None
        remote = obj.get("remote") or {}
        if isinstance(remote, dict):
            u = remote.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u
        for u in obj.get("url_list") or []:
            if isinstance(u, str) and u.startswith("http"):
                return u
        src = obj.get("url") or obj.get("src")
        if isinstance(src, str) and src.startswith("http"):
            return src
        nested = obj.get("image_src") or obj.get("img")
        if isinstance(nested, dict):
            return ShareOpusDownload._dig_image_url(nested)
        return None

    _IMG_URL_IN_STRING = re.compile(
        r"https://[a-z0-9.-]*(?:hdslb|douyinpic)\.com/[^\s\"'<>\\]+",
        re.IGNORECASE,
    )

    @classmethod
    def _is_noise_image_url(cls, url: str) -> bool:
        low = url.lower()
        if "/bfs/emote" in low or "/bfs/face" in low or "/bfs/nft" in low:
            return True
        if "static.hdslb.com" in low or "/bfs/vip/" in low or "/bfs/garb" in low:
            return True
        if "hdslb.com" in low and "/bfs/" not in low:
            return True
        # 动态里常见短视频片段 / 活动角标，不是正文配图
        if "/dyn_video/" in low or low.endswith(".mp4") or low.endswith(".m4s") or "/bfs/activity-plat/" in low:
            return True
        if "/bfs/story" in low and ".mp4" in low:
            return True
        return False

    @classmethod
    def _register_image_url(cls, url: str, out: List[str], seen: set, exclude: Optional[set] = None) -> None:
        if not url:
            return
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if url in seen:
            return
        if exclude and url in exclude:
            return
        if cls._is_noise_image_url(url):
            return
        # 只保留静态图（避免把短视频 dyn 文件当图下）
        low = url.lower().split("?", 1)[0]
        if not (
            low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
            or "/new_dyn/" in low
            or "tplv" in low
        ):
            return
        seen.add(url)
        out.append(url)

    @classmethod
    def _walk_collect_image_urls(
        cls,
        obj: Any,
        out: List[str],
        seen: set,
        limit: int = 200,
        exclude: Optional[set] = None,
    ) -> None:
        """在 JSON 子树中收集图床链接：url/src 字段 + 任意字符串里的图链（无扩展名、带 tplv 等）。"""
        if len(out) >= limit:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("url", "src") and isinstance(v, str) and v.startswith("http"):
                    low = v.lower()
                    if ("hdslb.com" in v or "douyinpic.com" in v) and "/bfs/" in v:
                        if any(low.split("?", 1)[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")) or "tplv" in low or "new_dyn" in low or "archive" in low or "~" in v:
                            cls._register_image_url(v, out, seen, exclude=exclude)
                else:
                    cls._walk_collect_image_urls(v, out, seen, limit, exclude=exclude)
        elif isinstance(obj, list):
            for item in obj:
                cls._walk_collect_image_urls(item, out, seen, limit, exclude=exclude)
        elif isinstance(obj, str):
            for m in cls._IMG_URL_IN_STRING.finditer(obj):
                u = m.group(0).rstrip("),.;'\"\\")
                if "/bfs/" in u:
                    cls._register_image_url(u, out, seen, exclude=exclude)

    @classmethod
    def _extract_image_urls_from_html(
        cls,
        html: str,
        out: List[str],
        seen: set,
        exclude: Optional[set] = None,
    ) -> None:
        """从整页 HTML 再扫一遍图链（部分图片只出现在 SSR / data 属性里，不在 __INITIAL_STATE__）。"""
        for m in cls._IMG_URL_IN_STRING.finditer(html or ""):
            u = m.group(0).rstrip("),.;'\"\\")
            cls._register_image_url(u, out, seen, exclude=exclude)

    def build_opus_meta(self, final_url: str, item: Dict[str, Any], html: str = "") -> Dict[str, Any]:
        # print(json.dumps(item, ensure_ascii=False, indent=2))
        basic = item["basic"]
        opus_id = self.get_opus_id_from_url(final_url) or item["id_str"]
        title = basic.get("title", "")
        rid_str = basic["rid_str"]
        comment_id_str = basic["comment_id_str"]

        author_name = ""
        author_mid = None
        pub_time = ""
        avatar_url = ""
        for module in item["modules"]:
            if not isinstance(module, dict) or module.get("module_type") != "MODULE_TYPE_AUTHOR":
                continue
            block = module["module_author"]
            author_name = block["name"]
            author_mid = block["mid"]
            pub_time = block["pub_time"]
            face = block["face"]
            if isinstance(face, str) and face.startswith("http"):
                avatar_url = face
            break

        exclude_urls = set()
        if avatar_url:
            exclude_urls.add(avatar_url)

        body_lines: List[str] = []
        content_images: List[str] = []
        seen_img: set = set()

        for module in item["modules"]:
            if not isinstance(module, dict) or module.get("module_type") != "MODULE_TYPE_CONTENT":
                continue
            content = module["module_content"]
            for paragraph in content["paragraphs"] or []:
                if not isinstance(paragraph, dict):
                    continue
                text, images = self.paragraph_to_text_and_images(paragraph)
                if text.strip():
                    body_lines.append(text.strip())
                for u in images:
                    self._register_image_url(u, content_images, seen_img, exclude=exclude_urls)
            self._walk_collect_image_urls(content, content_images, seen_img, exclude=exclude_urls)

        # 正文模块以外的 item 子树（部分版本把图集放在其它节点）
        self._walk_collect_image_urls(item, content_images, seen_img, exclude=exclude_urls)

        # 整页 HTML（补漏：仅 STATE 时抓不到的图）
        self._extract_image_urls_from_html(html, content_images, seen_img, exclude=exclude_urls)

        like_c = comment_c = forward_c = 0
        for mod in item.get("modules") or []:
            if not isinstance(mod, dict) or mod.get("module_type") != "MODULE_TYPE_STAT":
                continue
            st = mod.get("module_stat") or {}
            like_c = (st.get("like") or {}).get("count") or 0
            comment_c = (st.get("comment") or {}).get("count") or 0
            forward_c = (st.get("forward") or {}).get("count") or 0
            break

        body_text = "\n".join(body_lines).strip()
        if content_images and body_text:
            media_type = "mixed"
        elif content_images:
            media_type = "image"
        else:
            media_type = "text"

        bvids: List[str] = []
        seen_bv: set = set()
        for mod in item.get("modules") or []:
            if not isinstance(mod, dict) or mod.get("module_type") != "MODULE_TYPE_CONTENT":
                continue
            blob = json.dumps(mod.get("module_content") or {}, ensure_ascii=False)
            for m in re.finditer(r"BV[a-zA-Z0-9]{10}", blob, flags=re.IGNORECASE):
                token = m.group(0)
                if token not in seen_bv:
                    seen_bv.add(token)
                    bvids.append(token)

        return {
            "opus_id": str(opus_id),
            "post_type": "opus",
            "media_type": media_type,
            "title": title,
            "body_text": body_text,
            "image_urls": content_images,
            "image_url_candidates": [[u] for u in content_images],
            "embedded_bvids": bvids,
            "final_url": final_url.split("?", 1)[0].rstrip("/") + "/",
            "rid_str": rid_str,
            "comment_id_str": comment_id_str,
            "author": {
                "mid": author_mid,
                "name": author_name,
                "avatar_url": avatar_url,
                "pub_time": pub_time,
            },
            "interact_info": {
                "like_count": like_c,
                "comment_count": comment_c,
                "forward_count": forward_c,
            },
        }

    def get_opus_meta_by_html(self, final_url: str):
        response = requests.get(final_url, headers=self.headers, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, final_url: {final_url}")
        if self.looks_like_captcha_or_risk(response):
            raise AssertionError(
                "页面为验证码或风控，无法解析 Opus。请在浏览器打开链接完成验证后，"
                "使用地址栏中的 https://www.bilibili.com/opus/数字 再试，或配置登录 Cookie。"
            )
        html = response.text
        state = self.extract_initial_state_json(html)
        if state is None:
            return None
        opus_meta = self.build_opus_meta(final_url, item=state["detail"], html=html)
        return opus_meta

    def get_opus_meta_by_web_dynamic(self, final_url: str):
        opus_id = self.get_opus_id_from_url(final_url)
        js = self.get_web_dynamic(opus_id)
        opus_meta = self.build_opus_meta_by_web_dynamic(final_url, item=js["data"]["item"])
        return opus_meta

    def build_opus_meta_by_web_dynamic(self, final_url: str, item: dict) -> Dict[str, Any]:
        basic = item["basic"]
        opus_id = self.get_opus_id_from_url(final_url) or item["id_str"]
        rid_str = basic["rid_str"]
        comment_id_str = basic["comment_id_str"]

        modules = item["modules"]

        opus = modules["module_dynamic"]["major"]["opus"]
        image_urls = [pic["url"] for pic in opus["pics"]]
        title = opus["title"]
        body_text = opus["summary"]["text"]

        module_author = modules["module_author"]
        avatar_url = module_author["face"]
        author_mid = module_author["mid"]
        author_name = module_author["name"]
        pub_time = module_author["pub_time"]

        module_stat = modules["module_stat"]
        comment_c = module_stat["comment"]["count"]
        forward_c = module_stat["forward"]["count"]
        like_c = module_stat["like"]["count"]

        opus_meta = {
            "opus_id": str(opus_id),
            "post_type": "opus",
            # "media_type": media_type,
            "title": title,
            "body_text": body_text,
            "image_urls": image_urls,
            "image_url_candidates": [[u] for u in image_urls],
            # "embedded_bvids": bvids,
            "final_url": final_url.split("?", 1)[0].rstrip("/") + "/",
            "rid_str": rid_str,
            "comment_id_str": comment_id_str,
            "author": {
                "mid": author_mid,
                "name": author_name,
                "avatar_url": avatar_url,
                "pub_time": pub_time,
            },
            "interact_info": {
                "like_count": like_c,
                "comment_count": comment_c,
                "forward_count": forward_c,
            },
        }
        return opus_meta

    def get_opus_meta_by_share_url(self, share_url: str) -> Dict[str, Any]:
        final_url = self.get_final_url_by_share_url(share_url)
        opus_meta = None
        if opus_meta is None:
            opus_meta = self.get_opus_meta_by_html(final_url)
        if opus_meta is None:
            opus_meta = self.get_opus_meta_by_web_dynamic(final_url)
        if opus_meta is None:
            raise AssertionError()
        return opus_meta

    def get_opus_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.get_opus_meta_by_share_url(share_url)

    def download_opus_by_url(self, share_url: str, output_dir: str = "output_bilibili_opus") -> Dict[str, Any]:
        opus_meta = self.get_opus_meta_by_share_url(share_url)

        referer = opus_meta.get("final_url") or "https://www.bilibili.com/"

        slug = self.sanitize_filename(opus_meta["title"])
        save_dir = Path(output_dir) / f"{opus_meta['opus_id']}_{slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for index, image_url in enumerate(opus_meta.get("image_urls") or [], start=1):
            ext = ".jpg"
            lower = image_url.split("?", 1)[0].lower()
            if lower.endswith(".png"):
                ext = ".png"
            elif lower.endswith(".webp"):
                ext = ".webp"
            elif lower.endswith(".gif"):
                ext = ".gif"
            path = save_dir / f"image_{index:02d}{ext}"
            self.download_file(image_url, path, referer=referer)
            downloaded_images.append(path.as_posix())

        result = {
            **opus_meta,
            "downloaded_images": downloaded_images,
            "save_dir": save_dir.as_posix(),
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def download_opus_by_share_text(self, text: str, output_dir: str = "output_bilibili_opus") -> Dict[str, Any]:
        share_url = self.get_share_url_by_share_text(text)
        return self.download_opus_by_url(share_url, output_dir=output_dir)


def main():
    client = ShareOpusDownload()
    # share_text = """"
# https://t.bilibili.com/1202874151861223426?from_spmid=dt.dt.0.0.pv&plat_id=493&share_from=dynamic&share_medium=android&share_plat=android&share_session_id=2a8ae822-79c3-40bc-9ede-c2737b7de2e8&share_source=COPY&share_tag=s_i&spmid=dt.dt.0.0&timestamp=1778904366&unique_k=njmyI6r
#     """
    share_text = """"
https://b23.tv/oBke03t
    """
#     share_text = """"
# https://b23.tv/6UGNFEQ
#     """
    try:
        meta = client.get_opus_meta_by_share_text(share_text)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    except AssertionError as exc:
        print("failed:", str(exc))


if __name__ == "__main__":
    main()
