import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.middleware import register_middleware

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    lifespan=lifespan,
)

# 注册全局异常处理器
register_exception_handlers(app)

# 注册自定义中间件
register_middleware(app)

# 注册 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# ========== 路由注册 ==========
from app.api.health import router as health_router
from app.api.chat import router as chat_router
from app.api.admin import router as admin_router

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(admin_router)
# ==============================

if __name__ == "__main__":
    os.environ["ENV"] = "dev"
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        timeout_graceful_shutdown=5,
        port=settings.server_port,
    )
