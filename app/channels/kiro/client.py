"""
Kiro HTTP 客户端 + AWS Event Stream 解析

职责：
- 构建请求 headers（Bearer Token、X-Amz-Target、User-Agent 伪装等）
- 发送 HTTP 请求，支持重试（403 刷 token、429/5xx 指数退避）
- 解析 AWS Event Stream 二进制流，提取 JSON 事件
- 调用 ListAvailableModels / GetUsageLimits 管理接口

上游接口（抓包确认）：
- URL: POST https://q.{region}.amazonaws.com/
- 操作由 X-Amz-Target header 指定
- Content-Type: application/x-amz-json-1.0
- Authorization: Bearer {accessToken}
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

import httpx
from loguru import logger

from app.channels.kiro.auth import KiroAuth
from app.channels.kiro.converter import KiroConverter
from app.schemas.internal import InternalStreamChunk

_MAX_RETRIES = 3
_BASE_RETRY_DELAY = 1.0


class KiroClient:
    """Kiro HTTP 客户端，持有 auth（鉴权）和 converter（事件转换）"""

    def __init__(self, auth: KiroAuth, converter: KiroConverter) -> None:
        self._auth = auth
        self._converter = converter

    # ==================== 管理接口 ====================

    async def fetch_models(self) -> list[str]:
        """调用 ListAvailableModels 获取模型列表"""
        headers = await self._management_headers("AmazonCodeWhispererService.ListAvailableModels")
        profile_arn = self._auth.profile_arn or ""

        params: dict = {"origin": "AI_EDITOR"}
        body: dict = {"origin": "AI_EDITOR"}
        if profile_arn:
            params["profileArn"] = profile_arn
            body["profileArn"] = profile_arn

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._base_url, json=body, headers=headers, params=params)
                resp.raise_for_status()
            models = [m["modelId"] for m in resp.json().get("models", []) if "modelId" in m]
            logger.info(f"Fetched {len(models)} models from Kiro API: {models}")
            return models
        except Exception as e:
            logger.error(f"Failed to fetch models: {e}")
            return []

    async def fetch_usage_limits(self) -> dict:
        """调用 GetUsageLimits 获取额度信息"""
        headers = await self._management_headers("AmazonCodeWhispererService.GetUsageLimits")
        profile_arn = self._auth.profile_arn or ""

        params: dict = {"origin": "AI_EDITOR", "isEmailRequired": "false"}
        body: dict = {"profileArn": profile_arn, "origin": "AI_EDITOR", "isEmailRequired": False}
        if profile_arn:
            params["profileArn"] = profile_arn

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._base_url, json=body, headers=headers, params=params)
                resp.raise_for_status()
            for item in resp.json().get("usageBreakdownList", []):
                if item.get("resourceType") == "CREDIT":
                    result = {
                        "usage_limit": item.get("usageLimitWithPrecision", 0),
                        "current_usage": item.get("currentUsageWithPrecision", 0),
                        "next_reset": resp.json().get("nextDateReset", 0),
                    }
                    logger.info(f"Usage: {result['current_usage']}/{result['usage_limit']} Credits")
                    return result
            logger.warning("No CREDIT resource found in usage limits response")
            return {}
        except Exception as e:
            logger.error(f"Failed to fetch usage limits: {e}")
            return {}

    # ==================== 对话接口 ====================

    async def stream_chat(self, kiro_payload: dict) -> AsyncGenerator[InternalStreamChunk, None]:
        """发送对话请求，解析 event stream，逐个输出内部格式 chunk"""
        url = self._base_url
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                token = await self._auth.get_token()
                headers = self._chat_headers(token)

                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=300, write=30, pool=30)) as client:
                    req = client.build_request("POST", url, json=kiro_payload, headers=headers)
                    resp = await client.send(req, stream=True)

                    # 错误处理 + 重试
                    retry_delay = _BASE_RETRY_DELAY * (2 ** attempt)
                    if resp.status_code == 403:
                        await resp.aclose()
                        logger.warning(f"403 from Kiro API, refreshing token (attempt {attempt + 1}/{_MAX_RETRIES})")
                        await self._auth.force_refresh()
                        continue
                    if resp.status_code == 429:
                        await resp.aclose()
                        logger.warning(f"429 rate limited, waiting {retry_delay}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                        await asyncio.sleep(retry_delay)
                        continue
                    if 500 <= resp.status_code < 600:
                        await resp.aclose()
                        logger.warning(f"{resp.status_code} server error, waiting {retry_delay}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                        await asyncio.sleep(retry_delay)
                        continue
                    if resp.status_code != 200:
                        body = await resp.aread()
                        await resp.aclose()
                        raise RuntimeError(f"Kiro API error {resp.status_code}: {body.decode('utf-8', errors='replace')}")

                    # 200 — 解析 event stream
                    async for chunk in self._parse_stream(resp):
                        yield chunk
                    return

            except httpx.TimeoutException as e:
                last_error = e
                delay = _BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"Kiro API timeout, waiting {delay}s (attempt {attempt + 1}/{_MAX_RETRIES}): {e}")
                await asyncio.sleep(delay)
            except RuntimeError:
                raise
            except Exception as e:
                last_error = e
                logger.error(f"Kiro API request error: {e}")
                raise

        raise RuntimeError(f"Kiro API failed after {_MAX_RETRIES} retries: {last_error}")

    # ==================== Event Stream 解析 ====================

    async def _parse_stream(self, resp: httpx.Response) -> AsyncGenerator[InternalStreamChunk, None]:
        """解析 AWS Event Stream，提取 JSON 事件并转为内部格式"""
        buffer = ""
        try:
            async for raw in resp.aiter_bytes():
                buffer += raw.decode("utf-8", errors="ignore")
                while True:
                    event, buffer = self._extract_event(buffer)
                    if event is None:
                        break
                    chunk = self._converter.to_internal_chunk(event)
                    if chunk is not None:
                        yield chunk
        except Exception as e:
            logger.error(f"Event stream parse error: {e}")
            raise

    # ==================== 内部工具方法 ====================

    @property
    def _base_url(self) -> str:
        return f"https://q.{self._auth.region}.amazonaws.com/"

    def _chat_headers(self, token: str) -> dict:
        """对话请求 headers（对齐抓包数据）"""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-amz-json-1.0",
            "X-Amz-Target": "AmazonCodeWhispererStreamingService.GenerateAssistantResponse",
            "User-Agent": "aws-sdk-js/1.0.27 KiroIDE-0.7.45-gateway",
            "x-amz-user-agent": "aws-sdk-js/1.0.27 KiroIDE-0.7.45-gateway",
            "x-amzn-codewhisperer-optout": "true",
            "x-amzn-kiro-agent-mode": "vibe",
            "amz-sdk-invocation-id": str(uuid.uuid4()),
            "amz-sdk-request": "attempt=1; max=3",
            "Connection": "close",
        }

    async def _management_headers(self, target: str) -> dict:
        """管理接口 headers（ListAvailableModels / GetUsageLimits）"""
        token = await self._auth.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-amz-json-1.0",
            "X-Amz-Target": target,
            "User-Agent": "aws-sdk-js/1.0.27 KiroIDE-0.7.45-gateway",
            "x-amz-user-agent": "aws-sdk-js/1.0.27 KiroIDE-0.7.45-gateway",
            "x-amzn-codewhisperer-optout": "false",
            "amz-sdk-invocation-id": str(uuid.uuid4()),
            "amz-sdk-request": "attempt=1; max=3",
        }

    @staticmethod
    def _extract_event(buffer: str) -> tuple[dict | None, str]:
        """从 buffer 中提取下一个 JSON 事件"""
        patterns = ['{"content":', '{"name":', '{"input":', '{"stop":', '{"followupPrompt":', '{"usage":', '{"unit":', '{"contextUsagePercentage":']
        earliest = -1
        for p in patterns:
            pos = buffer.find(p)
            if pos != -1 and (earliest == -1 or pos < earliest):
                earliest = pos
        if earliest == -1:
            return None, buffer

        end = KiroClient._find_brace(buffer, earliest)
        if end == -1:
            return None, buffer

        raw = buffer[earliest:end + 1]
        rest = buffer[end + 1:]
        try:
            return json.loads(raw), rest
        except json.JSONDecodeError:
            logger.warning(f"JSON parse failed: {raw[:100]}")
            return None, rest

    @staticmethod
    def _find_brace(text: str, start: int) -> int:
        """找匹配的闭合大括号（考虑嵌套和字符串转义）"""
        if start >= len(text) or text[start] != "{":
            return -1
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\" and in_str:
                esc = True
                continue
            if c == '"' and not esc:
                in_str = not in_str
                continue
            if not in_str:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return i
        return -1
