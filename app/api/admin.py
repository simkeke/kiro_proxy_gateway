"""
管理接口

- GET /admin/models  查询所有支持的模型
- GET /admin/stats   查询通道组和通道的统计信息
"""

from fastapi import APIRouter

from app.channels.registry import get_registry

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/models")
async def list_models():
    """查询所有支持的模型及其所属通道组"""
    model_groups: dict[str, list[str]] = {}

    for group in get_registry().groups:
        for model in group.models:
            model_groups.setdefault(model, []).append(group.name)

    return {
        "models": [
            {"id": model, "groups": groups}
            for model, groups in sorted(model_groups.items())
        ]
    }


@router.get("/stats")
async def get_stats():
    """查询通道组和通道的统计信息"""
    groups_data = []

    for group in get_registry().groups:
        group_stats = await group.get_stats()
        channels_data = []

        for ch in group.get_channels():
            ch_stats = await ch.get_stats()
            channels_data.append({
                "name": ch.name,
                "healthy": ch.is_healthy(),
                "throttled": ch.is_throttled(),
                "models": ch.models,
                "stats": {
                    "total_requests": ch_stats.total_requests,
                    "success_count": ch_stats.success_count,
                    "failure_count": ch_stats.failure_count,
                    "total_prompt_tokens": ch_stats.total_prompt_tokens,
                    "total_completion_tokens": ch_stats.total_completion_tokens,
                },
            })

        groups_data.append({
            "name": group.name,
            "priority": group.priority,
            "strategy": group.strategy,
            "channels": channels_data,
            "total_requests": group_stats.total_requests,
            "success_count": group_stats.success_count,
            "failure_count": group_stats.failure_count,
        })

    return {"groups": groups_data}
