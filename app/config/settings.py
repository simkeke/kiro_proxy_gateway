from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 环境
    env: str = "dev"

    # 项目基础信息
    project_name: str = "AI Gateway"
    version: str = "0.1.0"
    server_port: int = 8800

    # CORS
    cors_origins: list[str] = ["*"]
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # 网关鉴权
    proxy_api_key: str = "Aa123123"

    # 鉴权白名单路径
    auth_whitelist: list[str] = ["/health/**", "/docs/**", "/redoc/**", "/openapi.json"]

    # 网络代理
    vpn_proxy_url: str = ""

    # 日志
    logging_level: str = "DEBUG"
    log_file_name: str = "app.log"

    # 通道配置
    channels_config_path: str = "channels.yaml"

    # 限流
    max_total_waiting: int = 50       # 总等待请求上限
    max_model_waiting: int = 10       # 单 model 等待请求上限
    throttle_timeout: float = 300.0    # 等待超时（秒）

    # SQLite
    sqlite_db_path: str = "data/gateway.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
