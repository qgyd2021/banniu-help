#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
解析 B 站「动态 / 图文 Opus」页面（含 b23 短链跳转到 /opus/…），抽取正文与图片，并可下载到本地。

说明：
- 依赖页面内嵌的 __INITIAL_STATE__，与 share_video_download.py 中视频稿件逻辑分离。
- 若落地为验证码 / 风控页，无法解析，需浏览器过验证或带 Cookie 后再试。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from toolbox.bilibili.media.share_download_base import BilibiliShareDownloadBase


class ShareOpusDownload(BilibiliShareDownloadBase):
    @staticmethod
    def get_entry_url_by_share_text(text: str) -> str:
        patterns = [
            r"https?://b23\.tv/[A-Za-z0-9]+(?:\?[^\s]*)?",
            r"https?://(?:www\.)?bilibili\.com/opus/\d+(?:\?[^\s]*)?",
            r"https?://t\.bilibili\.com/\d+(?:\?[^\s]*)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                return match.group(0).rstrip(".,;)")
        raise AssertionError(f"no opus/b23/t.bilibili entry url found; text: {text}")

    @staticmethod
    def _parse_opus_id_from_url(url: str) -> Optional[str]:
        match = re.search(r"bilibili\.com/opus/(\d+)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"t\.bilibili\.com/(\d+)", url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def fetch_opus_page(self, entry_url: str) -> Tuple[str, str, Dict[str, Any]]:
        """
        请求入口 URL（b23 或 opus 直链），返回 (落地 URL, HTML, __INITIAL_STATE__)。
        """
        response = self.session.get(entry_url, allow_redirects=True, timeout=30)
        if response.status_code != 200:
            raise AssertionError(f"request failed; status_code: {response.status_code}, url: {entry_url}")
        if self._looks_like_captcha_or_risk(response):
            raise AssertionError(
                "页面为验证码或风控，无法解析 Opus。请在浏览器打开链接完成验证后，"
                "使用地址栏中的 https://www.bilibili.com/opus/数字 再试，或配置登录 Cookie。"
            )
        final_url = response.url
        html = response.text or ""
        if not re.search(r"bilibili\.com/opus/\d+", final_url, re.I):
            raise AssertionError(
                f"落地 URL 不是 Opus 页: {final_url}。"
                "本模块仅处理会跳转到 /opus/数字 的 b23 或 Opus 直链；视频稿件请用 share_video_download.py。"
            )
        state = self._extract_initial_state_json(html)
        if not state:
            raise AssertionError("未从 HTML 中解析到 __INITIAL_STATE__，页面结构可能已变更。")
        return final_url, html, state

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

    @staticmethod
    def _paragraph_to_text_and_images(para: Dict[str, Any]) -> Tuple[str, List[str]]:
        """从单段 paragraph 抽取纯文本与图片 URL（结构随产品迭代可能变化，尽量宽松）。"""
        texts: List[str] = []
        images: List[str] = []

        text_block = para.get("text") or {}
        for node in text_block.get("nodes") or []:
            if isinstance(node, dict):
                piece = ShareOpusDownload._node_to_text(node)
                if piece:
                    texts.append(piece)

        # 图片段落：常见为 pic / images / inline 等字段
        for key in ("pics", "images", "pic_list"):
            block = para.get(key)
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, dict):
                        url = ShareOpusDownload._dig_image_url(item)
                        if url:
                            images.append(url)

        pic = para.get("pic")
        if isinstance(pic, dict):
            url = ShareOpusDownload._dig_image_url(pic)
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
        if not url or url in seen:
            return
        if exclude and url in exclude:
            return
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
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

    def build_opus_meta(self, final_url: str, state: Dict[str, Any], html: str = "") -> Dict[str, Any]:
        detail = state.get("detail") or {}
        basic = detail.get("basic") or {}
        opus_id = self._parse_opus_id_from_url(final_url) or (detail.get("id_str") or "")

        title = (basic.get("title") or "").strip() or f"opus_{opus_id}"
        rid_str = basic.get("rid_str") or ""
        comment_id_str = basic.get("comment_id_str") or ""

        author_name = ""
        author_mid = None
        pub_time = ""
        avatar_url = ""
        for mod in detail.get("modules") or []:
            if not isinstance(mod, dict):
                continue
            if mod.get("module_type") != "MODULE_TYPE_AUTHOR":
                continue
            block = mod.get("module_author") or {}
            author_name = (block.get("name") or "").strip()
            author_mid = block.get("mid")
            pub_time = (block.get("pub_time") or "").strip()
            face = block.get("face")
            if isinstance(face, str) and face.startswith("http"):
                avatar_url = face
            break

        exclude_urls = set()
        if avatar_url:
            exclude_urls.add(avatar_url)

        body_lines: List[str] = []
        content_images: List[str] = []
        seen_img: set = set()

        for mod in detail.get("modules") or []:
            if not isinstance(mod, dict) or mod.get("module_type") != "MODULE_TYPE_CONTENT":
                continue
            content = mod.get("module_content") or {}
            for para in content.get("paragraphs") or []:
                if not isinstance(para, dict):
                    continue
                line, imgs = self._paragraph_to_text_and_images(para)
                if line.strip():
                    body_lines.append(line.strip())
                for u in imgs:
                    self._register_image_url(u, content_images, seen_img, exclude=exclude_urls)
            self._walk_collect_image_urls(content, content_images, seen_img, exclude=exclude_urls)

        # 正文模块以外的 detail 子树（部分版本把图集放在其它节点）
        self._walk_collect_image_urls(detail, content_images, seen_img, exclude=exclude_urls)

        # 整页 HTML（补漏：仅 STATE 时抓不到的图）
        self._extract_image_urls_from_html(html, content_images, seen_img, exclude=exclude_urls)

        like_c = comment_c = forward_c = 0
        for mod in detail.get("modules") or []:
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
        for mod in detail.get("modules") or []:
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

    def get_opus_meta_by_url(self, entry_url: str) -> Dict[str, Any]:
        final_url, html, state = self.fetch_opus_page(entry_url)
        return self.build_opus_meta(final_url, state, html=html)

    def get_opus_meta_by_share_text(self, text: str) -> Dict[str, Any]:
        return self.get_opus_meta_by_url(self.get_entry_url_by_share_text(text))

    def download_opus_by_url(self, entry_url: str, output_dir: str = "output_bilibili_opus") -> Dict[str, Any]:
        final_url, html, state = self.fetch_opus_page(entry_url)
        meta = self.build_opus_meta(final_url, state, html=html)
        referer = meta.get("final_url") or "https://www.bilibili.com/"

        slug = self.sanitize_filename(meta["title"])
        save_dir = Path(output_dir) / f"{meta['opus_id']}_{slug}"
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded_images: List[str] = []
        for index, image_url in enumerate(meta.get("image_urls") or [], start=1):
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
            **meta,
            "downloaded_images": downloaded_images,
            "save_dir": save_dir.as_posix(),
        }
        with open(save_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def download_opus_by_share_text(self, text: str, output_dir: str = "output_bilibili_opus") -> Dict[str, Any]:
        return self.download_opus_by_url(self.get_entry_url_by_share_text(text), output_dir=output_dir)


def main():
    client = ShareOpusDownload()
    share_text = "https://b23.tv/1uHyBhd"
    try:
        meta = client.get_opus_meta_by_share_text(share_text)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    except AssertionError as exc:
        print("failed:", str(exc))


if __name__ == "__main__":
    main()
