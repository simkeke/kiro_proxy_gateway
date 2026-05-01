"""
Kiro 鉴权管理

通过 refresh_token 获取和维护 access_token 的生命周期：
- 接口: POST https://prod.{region}.auth.desktop.kiro.dev/refreshToken
- 请求: {"refreshToken": "..."}
- 响应: {"accessToken": "...", "expiresIn": 3600, "profileArn": "...", "refreshToken": "..."}
"""

import asyncio
from datetime import datetime, timezone, timedelta

import httpx
from loguru import logger

# 提前刷新缓冲时间（秒）
_REFRESH_BUFFER = 300


class KiroAuth:
    """Kiro 账号鉴权，管理 token 获取、自动刷新、过期判断"""

    def __init__(self, refresh_token: str, region: str = "us-east-1", profile_arn: str | None = None) -> None:
        self._refresh_token = refresh_token
        self._region = region
        self._access_token: str | None = None
        self._profile_arn: str | None = profile_arn
        self._expires_at: datetime | None = None
        self._lock = asyncio.Lock()

    # ---- 属性 ----

    @property
    def profile_arn(self) -> str | None:
        return self._profile_arn

    @property
    def region(self) -> str:
        return self._region

    # ---- 公开方法 ----

    def has_valid_token(self) -> bool:
        """轻量检查 token 是否有效（不触发刷新，供 is_available 使用）"""
        if not self._access_token:
            return True  # 还没获取过，首次 send 时会刷新
        if not self._expires_at:
            return True
        return datetime.now(timezone.utc) < self._expires_at

    async def get_token(self) -> str:
        """获取有效 access_token，过期前自动刷新"""
        async with self._lock:
            if self._access_token and not self._is_expiring_soon():
                return self._access_token
            await self._do_refresh()
            return self._access_token

    async def force_refresh(self) -> str:
        """强制刷新 token（收到 403 后调用）"""
        async with self._lock:
            await self._do_refresh()
            return self._access_token

    # ---- 内部方法 ----

    def _is_expiring_soon(self) -> bool:
        if not self._expires_at:
            return True
        return datetime.now(timezone.utc) >= self._expires_at - timedelta(seconds=_REFRESH_BUFFER)

    async def _do_refresh(self) -> None:
        url = f"https://prod.{self._region}.auth.desktop.kiro.dev/refreshToken"
        headers = {"Content-Type": "application/json", "User-Agent": "Kiro-CLI"}
        payload = {"refreshToken": self._refresh_token}

        logger.info("Refreshing Kiro token...")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        access_token = data.get("accessToken")
        if not access_token:
            raise ValueError(f"Missing accessToken in refresh response: {data}")

        self._access_token = access_token
        self._profile_arn = data.get("profileArn", self._profile_arn)
        if new_rt := data.get("refreshToken"):
            self._refresh_token = new_rt
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expiresIn", 3600))

        logger.info(f"Kiro token refreshed, expires: {self._expires_at.isoformat()}")
