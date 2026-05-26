#!/usr/bin/python3
# -*- coding: utf-8 -*-
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Dict, List, Tuple
import time
from zoneinfo import ZoneInfo

import requests


NODE_BRIDGE_SCRIPT = r"""
'use strict';
const fs = require('fs');
const vm = require('vm');

const [, , acrawlerPath, ctxPath] = process.argv;
const acrawlerSrc = fs.readFileSync(acrawlerPath, 'utf8');
const ctx = JSON.parse(fs.readFileSync(ctxPath, 'utf8'));

const cookieStore = { value: '__ac_nonce=' + ctx.nonce };
const sandbox = {};

sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.top = sandbox;
sandbox.parent = sandbox;
sandbox.globalThis = sandbox;

sandbox.location = {
  href: ctx.url,
  hostname: 'www.douyin.com',
  host: 'www.douyin.com',
  protocol: 'https:',
  origin: 'https://www.douyin.com',
  pathname: '/',
  search: '',
  hash: '',
  reload() {},
  replace() {},
  assign() {},
  toString() { return this.href; },
};

function makeFakeElement(tag) {
  return {
    tagName: (tag || '').toUpperCase(),
    style: {},
    children: [],
    setAttribute() {},
    getAttribute() { return null; },
    appendChild() {},
    removeChild() {},
    addEventListener() {},
    removeEventListener() {},
    getContext() { return null; },
    toDataURL() { return ''; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
}

sandbox.document = {
  get cookie() { return cookieStore.value; },
  set cookie(v) {
    if (typeof v !== 'string') return;
    const seg = v.split(';')[0];
    if (!seg) return;
    const eq = seg.indexOf('=');
    if (eq <= 0) return;
    const key = seg.slice(0, eq).trim();
    const val = seg.slice(eq + 1).trim();
    const parts = cookieStore.value ? cookieStore.value.split('; ') : [];
    const next = parts.filter(p => p.split('=')[0] !== key);
    next.push(key + '=' + val);
    cookieStore.value = next.join('; ');
  },
  referrer: ctx.referrer || '',
  title: '抖音',
  URL: ctx.url,
  documentElement: { clientWidth: 1920, clientHeight: 1080, lang: 'zh-CN' },
  body: makeFakeElement('body'),
  head: makeFakeElement('head'),
  createElement(tag) { return makeFakeElement(tag); },
  createTextNode() { return {}; },
  getElementsByTagName() { return []; },
  getElementById() { return null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() { return true; },
  hidden: false,
};

sandbox.navigator = {
  userAgent: ctx.userAgent,
  appVersion: ctx.userAgent.replace(/^Mozilla\//, ''),
  appName: 'Netscape',
  appCodeName: 'Mozilla',
  product: 'Gecko',
  productSub: '20030107',
  vendor: 'Google Inc.',
  vendorSub: '',
  platform: 'Win32',
  language: 'zh-CN',
  languages: ['zh-CN', 'zh', 'en'],
  cookieEnabled: true,
  doNotTrack: null,
  hardwareConcurrency: 8,
  deviceMemory: 8,
  maxTouchPoints: 0,
  webdriver: false,
  plugins: { length: 0, item() { return null; }, namedItem() { return null; } },
  mimeTypes: { length: 0, item() { return null; }, namedItem() { return null; } },
  javaEnabled() { return false; },
};

sandbox.screen = {
  width: 1920, height: 1080,
  availWidth: 1920, availHeight: 1040,
  colorDepth: 24, pixelDepth: 24,
  orientation: { type: 'landscape-primary', angle: 0 },
};

sandbox.history = {
  length: 1, state: null,
  back() {}, forward() {}, go() {},
  pushState() {}, replaceState() {},
};

sandbox.performance = {
  timing: { navigationStart: Date.now() },
  now() { return Date.now(); },
  getEntries() { return []; },
  getEntriesByType() { return []; },
};

function makeStorage() {
  const data = Object.create(null);
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    clear() { for (const k of Object.keys(data)) delete data[k]; },
    key(i) { return Object.keys(data)[i] || null; },
    get length() { return Object.keys(data).length; },
  };
}
sandbox.localStorage = makeStorage();
sandbox.sessionStorage = makeStorage();

sandbox.setTimeout = (fn) => 0;
sandbox.clearTimeout = () => {};
sandbox.setInterval = () => 0;
sandbox.clearInterval = () => {};
sandbox.requestAnimationFrame = () => 0;
sandbox.cancelAnimationFrame = () => {};

sandbox.console = console;
sandbox.atob = (s) => Buffer.from(String(s), 'base64').toString('binary');
sandbox.btoa = (s) => Buffer.from(String(s), 'binary').toString('base64');

sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
sandbox.dispatchEvent = () => true;
sandbox.postMessage = () => {};

sandbox.XMLHttpRequest = function () {
  return {
    open() {}, send() {}, setRequestHeader() {},
    addEventListener() {}, removeEventListener() {}, abort() {},
    readyState: 0, status: 0, responseText: '', response: '',
  };
};
sandbox.fetch = () => Promise.resolve({ ok: true, status: 200, text: async () => '', json: async () => ({}) });

vm.createContext(sandbox);

try {
  vm.runInContext(acrawlerSrc, sandbox, { timeout: 5000, filename: 'acrawler.js' });
} catch (e) {
  console.error('runInContext(acrawler) error:', e && e.stack || e);
  process.exit(2);
}

try {
  if (sandbox.byted_acrawler && typeof sandbox.byted_acrawler.init === 'function') {
    sandbox.byted_acrawler.init({ aid: 99999999, dfp: 0 });
  } else if (sandbox.window && sandbox.window.byted_acrawler && typeof sandbox.window.byted_acrawler.init === 'function') {
    sandbox.window.byted_acrawler.init({ aid: 99999999, dfp: 0 });
  }
} catch (e) {
  console.error('byted_acrawler.init warning:', e && e.message || e);
}

const acrawler = sandbox.byted_acrawler || (sandbox.window && sandbox.window.byted_acrawler);
if (!acrawler || typeof acrawler.sign !== 'function') {
  console.error('byted_acrawler not registered after evaluating challenge script.');
  process.exit(3);
}

let signature;
try {
  signature = acrawler.sign(ctx.referrer || '', ctx.nonce);
} catch (e) {
  console.error('byted_acrawler.sign error:', e && e.stack || e);
  process.exit(4);
}

process.stdout.write(JSON.stringify({ signature: signature }) + '\n');
"""


class NonceSignRefererUtils(object):
    url = "https://www.douyin.com/"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

    def __init__(self):
        self._nonce_signature = None
        self._nonce_signature_expire_ts = None

    def get_nonce_dict(self) -> dict:
        max_try = 10
        for i in range(max_try):
            response = requests.request(
                method="GET",
                url=self.url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Connection": "close",
                },
                timeout=30
            )
            html = response.text

            nonce = None
            nonce_expires_at = None
            for cookie in response.cookies:
                if cookie.name == "__ac_nonce":
                    nonce = cookie.value
                    nonce_expires_at = cookie.expires  # Unix 时间戳，秒
                    break

            if nonce is None:
                nonce = self.get_nonce_from_html(html)
            # print(f"nonce: {nonce}")
            if "byted_acrawler" in html or "_$jsvmprt" in html:
                acrawler_script = self.get_acrawler_script_from_html(html)
                return {
                    "nonce": nonce,
                    "nonce_expires_at": nonce_expires_at,
                    "acrawler_script": acrawler_script,
                }
        raise AssertionError(f"未获取到反爬挑战页（重试 {max_try} 次仍失败）；")

    @staticmethod
    def get_nonce_from_html(html: str) -> str:
        match = re.search(r"__ac_nonce\s*=\s*['\"]([0-9a-f]{15,})['\"]", html)
        if match is None:
            match = re.search(r"document\.cookie\s*=\s*['\"]__ac_nonce=([0-9a-f]{15,})", html)
        if match is None:
            return None
        result = match.group(1)
        return result

    @staticmethod
    def get_acrawler_script_from_html(html: str) -> Tuple[str, str]:
        scripts: List[str] = re.findall(
            r"<script\b[^>]*>([\s\S]*?)</script>", html, flags=re.IGNORECASE
        )
        acrawler_script = ""
        for script in scripts:
            # print(f"script: {script}")
            if "byted_acrawler" in script and "sign" in script:
                if "_$jsvmprt" in script or len(script) > 20_000:
                    acrawler_script = script
            elif "_$jsvmprt" in script and not acrawler_script:
                acrawler_script = script
        if not acrawler_script:
            # 兜底：选最长的一段
            scripts_sorted = sorted(scripts, key=len, reverse=True)
            acrawler_script = scripts_sorted[0] if scripts_sorted else ""
        if not acrawler_script:
            raise AssertionError("未在挑战页中定位到 byted_acrawler 实现脚本")
        return acrawler_script

    def get_signature(
            self, nonce: str, acrawler_script: str
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="dy_acrawler_") as tmpdir:
            tmp = Path(tmpdir)
            acrawler_path = tmp / "acrawler.js"
            bridge_path = tmp / "bridge.js"
            ctx_path = tmp / "ctx.json"

            acrawler_path.write_text(acrawler_script, encoding="utf-8")
            bridge_path.write_text(NODE_BRIDGE_SCRIPT, encoding="utf-8")
            ctx_path.write_text(json.dumps({
                "nonce": nonce,
                "userAgent": self.user_agent,
                "url": self.url,
                "referrer": "",
                }, ensure_ascii=False,
            ), encoding="utf-8")

            completed = subprocess.run(
                args=[
                    "node",
                    bridge_path.as_posix(),
                    acrawler_path.as_posix(),
                    ctx_path.as_posix(),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
            )

            if completed.returncode != 0:
                raise AssertionError(
                    "node 计算 __ac_signature 失败:\nstdout: {completed.stdout}\nstderr: {completed.stderr}"
                )

            payload = self.parse_bridge_stdout(completed.stdout)
            signature_dict = payload.get("signature")
            if not isinstance(signature_dict, str) or not signature_dict:
                raise AssertionError(
                    f"未获得有效的 __ac_signature；bridge 输出: {completed.stdout!r}"
                )
            return signature_dict

    @staticmethod
    def parse_bridge_stdout(stdout: str) -> Dict[str, str]:
        # bridge 把诊断信息打到 stderr，结果以单行 JSON 放在 stdout 末尾
        last_line = ""
        for line in stdout.splitlines()[::-1]:
            line = line.strip()
            if line:
                last_line = line
                break
        if not last_line:
            return {}
        try:
            data = json.loads(last_line)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def get_nonce_signature(self, time_zone_info: str = "Asia/Shanghai"):
        nonce_dict = self.get_nonce_dict()
        nonce = nonce_dict["nonce"]
        nonce_expires_at = nonce_dict["nonce_expires_at"]
        acrawler_script = nonce_dict["acrawler_script"]
        signature: str = self.get_signature(nonce, acrawler_script)

        expires_at_str = datetime.fromtimestamp(
            nonce_expires_at, tz=ZoneInfo(time_zone_info)
        ).strftime("%Y-%m-%d %H:%M:%S")

        result = {
            "expires_at_ts": nonce_expires_at,
            "expires_at_str": expires_at_str,
            "__ac_nonce": nonce,
            "__ac_signature": signature,
            "__ac_referer": "__ac_blank",
        }
        return result

    def set_nonce_signature(self):
        js = self.get_nonce_signature()
        expires_at_ts = js["expires_at_ts"]
        expires_at_str = js["expires_at_str"]
        self._nonce_signature = {
            "__ac_nonce": js["__ac_nonce"],
            "__ac_signature": js["__ac_signature"],
            "__ac_referer": js["__ac_referer"]
        }
        # 过期时间提前60秒，留出余量。
        self._nonce_signature_expire_ts = expires_at_ts - 60

    @property
    def ac_nonce_signature(self) -> dict:
        if self._nonce_signature is None:
            self.set_nonce_signature()
        else:
            now = time.time()
            if now > self._nonce_signature_expire_ts:
                self.set_nonce_signature()
        return self._nonce_signature


def main():
    client = NonceSignRefererUtils()

    result: str = client.get_nonce_signature()
    print(f"result: {json.dumps(result, ensure_ascii=False, indent=2)}")
    print(f"now: {time.time()}")
    return


if __name__ == "__main__":
    main()
