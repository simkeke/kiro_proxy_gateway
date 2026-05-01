"""
Kiro 协议转换器

请求方向: InternalRequest → Kiro API payload
- system 消息合并到第一条 user 消息（Kiro 不支持 system 角色）
- tool 消息转为 user + toolResults
- 相邻同角色合并，确保 user/assistant 严格交替
- tools 转为 Kiro toolSpecification 格式
- 无 tools 时剥离 tool 内容为文本（Kiro 拒绝无 tools 但有 toolResults）

响应方向: Kiro 原始事件 → InternalStreamChunk
- {"content": "..."} → 文本 chunk
- {"name": ..., "toolUseId": ...} → 工具调用开始
- {"input": ...} → 工具调用参数续传
- {"stop": true} → 工具调用结束
- {"unit": "credit", "usage": ...} → credit 消耗（meteringEvent）
"""

import json
import time
import uuid

from loguru import logger

from app.schemas.internal import (
    InternalRequest, InternalStreamChunk, InternalChoice,
    InternalDelta, InternalToolCall, InternalFunctionCall, InternalUsage,
)

# ==================== 工具函数 ====================


def _gen_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex}"


def _gen_tool_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:8]}"


def _estimate_tokens(char_count: int) -> int:
    """字符数 → token 数估算（1 字符 ≈ 1.2 token）"""
    return max(1, int(char_count * 1.2))


# ==================== 转换器 ====================


class KiroConverter:
    """
    Kiro 协议转换器（有状态）

    响应转换需要跟踪工具调用和输出字符数，每次请求前自动 reset。
    """

    def __init__(self) -> None:
        self._reset_state()
        self._input_chars = 0

    def _reset_state(self) -> None:
        """重置响应转换状态"""
        self.completion_id = _gen_completion_id()
        self.created = int(time.time())
        self._model = ""
        self._first_chunk = True
        self._current_tool: dict | None = None
        self._tool_calls: list[dict] = []
        self._output_chars = 0

    # ==================== 请求转换 ====================

    def to_kiro_request(self, request: InternalRequest, profile_arn: str = "") -> dict:
        """InternalRequest → Kiro API payload"""
        self._reset_state()
        self._model = request.model

        # 统计输入字符数
        self._input_chars = sum(len(m.content or "") for m in request.messages)

        # 1. 提取 system prompt
        system_prompt, msgs = self._split_system(request)

        # 2. tool 消息 → user + toolResults
        msgs = self._convert_tool_msgs(msgs)

        # 3. 无 tools 时剥离 tool 内容 / 有 tools 时确保 toolResults 前有 assistant
        if not request.tools:
            msgs = self._strip_tool_content(msgs)
        else:
            msgs = self._fix_orphan_tool_results(msgs)

        # 4. 合并相邻同角色 → 确保 user 开头 → 确保交替
        msgs = self._merge_adjacent(msgs)
        msgs = self._ensure_user_first(msgs)
        msgs = self._ensure_alternating(msgs)

        if not msgs:
            raise ValueError("No messages to send")

        # 5. 拆分 history + current
        history_msgs, current = msgs[:-1], msgs[-1]

        # 6. 构建 history
        history = self._build_history(history_msgs, request.model)

        # 注入 system prompt 为伪造的一轮对话（放在 history 最前面）
        system_history = self._build_system_history(system_prompt)
        history = system_history + history

        # 7. 构建 currentMessage
        content = current.get("content") or "Continue"
        if current["role"] == "assistant":
            history.append({"assistantResponseMessage": {"content": content}})
            content = "Continue"

        user_input: dict = {"content": content, "modelId": request.model, "origin": "AI_EDITOR"}

        ctx: dict = {}
        if request.tools:
            ctx["tools"] = self._convert_tools(request.tools)
        if tr := current.get("_tool_results"):
            ctx["toolResults"] = tr
        if ctx:
            user_input["userInputMessageContext"] = ctx

        # 8. 组装 payload
        state: dict = {
            "chatTriggerType": "MANUAL",
            "conversationId": str(uuid.uuid4()),
            "currentMessage": {"userInputMessage": user_input},
        }
        if history:
            state["history"] = history

        payload: dict = {"conversationState": state}
        if profile_arn:
            payload["profileArn"] = profile_arn
        return payload

    # ---- 请求转换辅助方法 ----

    def _split_system(self, request: InternalRequest) -> tuple[str, list[dict]]:
        parts, msgs = [], []
        for m in request.messages:
            if m.role == "system":
                if m.content:
                    parts.append(m.content)
            else:
                msgs.append(m.model_dump(exclude_none=True))
        return "\n".join(parts).strip(), msgs

    @staticmethod
    def _build_system_history(system_prompt: str) -> list[dict]:
        """
        将 system prompt 包装为一轮伪造的 history 对话

        有 system prompt 时用用户的，没有时用默认通用提示词。
        通过伪造 user→assistant 对话，引导模型接受角色设定。
        """
        default_prompt = (
            "你现在是一个全能个人助手。你擅长日常对话、写作、翻译、分析、编程、问答等各类任务。"
            "请根据用户的实际需求灵活回复."
            "用户用什么语言提问，就用什么语言回答。"
        )
        prompt = system_prompt or default_prompt
        return [
            {
                "userInputMessage": {
                    "content": f"Follow this instruction:\n{prompt}",
                    "origin": "AI_EDITOR",
                }
            },
            {
                "assistantResponseMessage": {
                    "content": "好的，我会按照你的要求来回复。"
                }
            },
        ]

    def _convert_tool_msgs(self, msgs: list[dict]) -> list[dict]:
        """tool 角色 → user + toolResults"""
        result, pending = [], []
        for m in msgs:
            if m.get("role") == "tool":
                pending.append({
                    "content": [{"text": m.get("content") or "(empty result)"}],
                    "status": "success",
                    "toolUseId": m.get("tool_call_id", ""),
                })
            else:
                if pending:
                    result.append({"role": "user", "content": "", "_tool_results": pending.copy()})
                    pending.clear()
                result.append(m)
        if pending:
            result.append({"role": "user", "content": "", "_tool_results": pending.copy()})
        return result

    def _strip_tool_content(self, msgs: list[dict]) -> list[dict]:
        """无 tools 时，把 tool_calls / _tool_results 转为文本"""
        result = []
        for m in msgs:
            tc, tr = m.get("tool_calls"), m.get("_tool_results")
            if not tc and not tr:
                result.append(m)
                continue
            parts = [m.get("content") or ""]
            if tc:
                for t in tc:
                    f = t.get("function", {})
                    parts.append(f"[Tool: {f.get('name', '?')} ({t.get('id', '')})]\n{f.get('arguments', '{}')}")
            if tr:
                for t in tr:
                    texts = [i.get("text", "") for i in t.get("content", [])]
                    parts.append(f"[Tool Result ({t.get('toolUseId', '')})]\n{chr(10).join(texts) or '(empty)'}")
            result.append({"role": m["role"], "content": "\n\n".join(p for p in parts if p)})
        return result

    def _fix_orphan_tool_results(self, msgs: list[dict]) -> list[dict]:
        """确保 _tool_results 前有 assistant tool_calls，否则转文本"""
        result = []
        for m in msgs:
            if m.get("_tool_results") and not (result and result[-1].get("role") == "assistant" and result[-1].get("tool_calls")):
                parts = [m.get("content") or ""]
                for t in m["_tool_results"]:
                    texts = [i.get("text", "") for i in t.get("content", [])]
                    parts.append(f"[Tool Result ({t.get('toolUseId', '')})]\n{chr(10).join(texts) or '(empty)'}")
                result.append({"role": m["role"], "content": "\n\n".join(p for p in parts if p)})
            else:
                result.append(m)
        return result

    def _merge_adjacent(self, msgs: list[dict]) -> list[dict]:
        if not msgs:
            return []
        merged = [msgs[0]]
        for m in msgs[1:]:
            last = merged[-1]
            if m["role"] == last["role"]:
                last["content"] = f"{last.get('content', '')}\n{m.get('content', '')}".strip()
                if m.get("tool_calls"):
                    last["tool_calls"] = (last.get("tool_calls") or []) + m["tool_calls"]
                if m.get("_tool_results"):
                    last["_tool_results"] = (last.get("_tool_results") or []) + m["_tool_results"]
            else:
                merged.append(m)
        return merged

    def _ensure_user_first(self, msgs: list[dict]) -> list[dict]:
        if msgs and msgs[0]["role"] != "user":
            return [{"role": "user", "content": "(empty)"}] + msgs
        return msgs

    def _ensure_alternating(self, msgs: list[dict]) -> list[dict]:
        if len(msgs) < 2:
            return msgs
        result = [msgs[0]]
        for m in msgs[1:]:
            if m["role"] == result[-1]["role"]:
                filler_role = "assistant" if m["role"] == "user" else "user"
                result.append({"role": filler_role, "content": "(empty)"})
            result.append(m)
        return result

    def _build_history(self, msgs: list[dict], model_id: str) -> list[dict]:
        history = []
        for m in msgs:
            if m["role"] == "user":
                entry: dict = {"content": m.get("content") or "(empty)", "modelId": model_id, "origin": "AI_EDITOR"}
                if tr := m.get("_tool_results"):
                    entry["userInputMessageContext"] = {"toolResults": tr}
                history.append({"userInputMessage": entry})
            elif m["role"] == "assistant":
                entry = {"content": m.get("content") or "(empty)"}
                if tc := m.get("tool_calls"):
                    uses = []
                    for t in tc:
                        f = t.get("function", {})
                        args = f.get("arguments", "{}")
                        try:
                            inp = json.loads(args) if isinstance(args, str) and args else {}
                        except json.JSONDecodeError:
                            inp = {}
                        uses.append({"name": f.get("name", ""), "input": inp, "toolUseId": t.get("id", "")})
                    entry["toolUses"] = uses
                history.append({"assistantResponseMessage": entry})
        return history

    def _convert_tools(self, tools: list) -> list[dict]:
        return [{
            "toolSpecification": {
                "name": t.function.name,
                "description": t.function.description or f"Tool: {t.function.name}",
                "inputSchema": {"json": t.function.parameters or {}},
            }
        } for t in tools]

    # ==================== 响应转换 ====================

    def to_internal_chunk(self, event: dict) -> InternalStreamChunk | None:
        """Kiro 原始事件 → InternalStreamChunk（返回 None 表示跳过）"""

        # 文本内容
        if "content" in event:
            if event.get("followupPrompt"):
                return None
            return self._content_chunk(event["content"])

        # meteringEvent: {"unit": "credit", "usage": 0.04}
        if "unit" in event and "usage" in event:
            return self._metering_chunk(event["usage"])

        # 旧格式 usage（兼容）
        if "usage" in event and "unit" not in event:
            return self._metering_chunk(event["usage"])

        # 工具调用
        if "name" in event:
            self._tool_start(event)
            return None
        if "input" in event and "name" not in event:
            self._tool_input(event)
            return None
        if event.get("stop"):
            self._tool_stop()
            return None

        return None

    def get_pending_tool_calls(self) -> list[InternalToolCall]:
        """流结束时获取所有已完成的工具调用"""
        if self._current_tool:
            self._finalize_tool()
        return [
            InternalToolCall(id=t["id"], type="function", function=InternalFunctionCall(name=t["name"], arguments=t["arguments"]))
            for t in self._tool_calls
        ]

    # ---- 响应转换辅助方法 ----

    def _content_chunk(self, content: str) -> InternalStreamChunk:
        self._output_chars += len(content)
        delta = InternalDelta(content=content)
        if self._first_chunk:
            delta.role = "assistant"
            self._first_chunk = False
        return InternalStreamChunk(
            id=self.completion_id, object="chat.completion.chunk",
            created=self.created, model=self._model,
            choices=[InternalChoice(index=0, delta=delta, finish_reason=None)],
        )

    def _metering_chunk(self, usage_value: float | int) -> InternalStreamChunk:
        """构建 usage chunk：token 估算 + credit 记录"""
        credit = float(usage_value) if isinstance(usage_value, (int, float)) else 0.0
        prompt_tokens = _estimate_tokens(self._input_chars) + 600  # +600 for Kiro system prompt (~500 chars)
        completion_tokens = _estimate_tokens(self._output_chars)
        return InternalStreamChunk(
            id=self.completion_id, object="chat.completion.chunk",
            created=self.created, model=self._model, choices=[],
            usage=InternalUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=prompt_tokens + completion_tokens),
            credit_usage=credit,
        )

    def _tool_start(self, event: dict) -> None:
        if self._current_tool:
            self._finalize_tool()
        inp = event.get("input", "")
        self._current_tool = {
            "id": event.get("toolUseId", _gen_tool_call_id()),
            "name": event.get("name", ""),
            "arguments": json.dumps(inp) if isinstance(inp, dict) else (str(inp) if inp else ""),
        }
        if event.get("stop"):
            self._finalize_tool()

    def _tool_input(self, event: dict) -> None:
        if not self._current_tool:
            return
        inp = event.get("input", "")
        self._current_tool["arguments"] += json.dumps(inp) if isinstance(inp, dict) else (str(inp) if inp else "")

    def _tool_stop(self) -> None:
        if self._current_tool:
            self._finalize_tool()

    def _finalize_tool(self) -> None:
        if not self._current_tool:
            return
        args = self._current_tool["arguments"]
        if isinstance(args, str) and args.strip():
            try:
                self._current_tool["arguments"] = json.dumps(json.loads(args))
            except json.JSONDecodeError:
                logger.warning(f"Tool arguments JSON parse failed: {args[:200]}")
                self._current_tool["arguments"] = "{}"
        elif not args:
            self._current_tool["arguments"] = "{}"
        self._tool_calls.append(self._current_tool)
        self._current_tool = None
