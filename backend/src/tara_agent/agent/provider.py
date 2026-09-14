"""DeepSeek-backed planning and answer generation with a testable interface."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from openai import AsyncOpenAI, OpenAIError

from tara_agent.agent.models import ModelStreamDelta, ToolDefinition, ToolPlan
from tara_agent.config import Settings

PLANNER_SYSTEM_PROMPT = """
You are the planning component of Tara-Agent. Select exactly one available MCP tool for the
user's Tara Oceans question. Never propose Python, SQL, filesystem access, or an unlisted tool.
Call exactly one supplied tool. Arguments must match the selected tool's input schema exactly.
Use marker v4 or v9 explicitly for marker analyses. Default taxonomy matching to level unless the
user clearly requests substring matching. Never invent a sample ID, marker, taxon, filter value,
or environmental variable that the user did not supply.

Argument rules:
- Include an optional filter only when the user explicitly states that constraint.
- Preserve scientific names and exact sample IDs from the question.
- Translate a user-supplied Chinese place name to the English dataset term; for example, 地中海
  means Mediterranean.
- When the user asks for exactly one result, set the corresponding limit to 1.

Selection rules:
- Use get_sample_info only when the user supplies an exact sample ID in the question.
- Use find_samples when the user asks to find, filter, or list samples by location or environment.
- Use find_taxa to list matching ASVs or taxonomy occurrences, not to calculate abundance.
- Use taxon_abundance only for raw reads or relative abundance.
- Use diversity_analysis only for observed ASV richness or Shannon diversity.
- Use environment_association only for correlation with one allowlisted environmental variable.
""".strip()

ANSWER_SYSTEM_PROMPT = """
You are Tara-Agent. Answer the user's question using only the supplied deterministic tool result.
Be concise, scientifically cautious, and mention important warnings. Do not invent values, causal
claims, or analyses that are absent from the result. V4 and V9 are independent markers. The JSON
result may be truncated for answer generation, while the application still receives the full data.
""".strip()


class AgentModelError(RuntimeError):
    """Raised when the language model returns an unusable response."""


class AgentModel(Protocol):
    @property
    def name(self) -> str: ...

    async def plan(
        self,
        question: str,
        tools: list[ToolDefinition],
    ) -> ToolPlan: ...

    def stream_answer(
        self,
        question: str,
        plan: ToolPlan,
        result: dict[str, Any],
    ) -> AsyncIterator[ModelStreamDelta]: ...


class DeepSeekChatModel:
    """Use DeepSeek's OpenAI-compatible Chat Completions API."""

    def __init__(self, settings: Settings) -> None:
        if settings.deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required")
        self._name = settings.deepseek_model
        self.reasoning_effort = settings.deepseek_reasoning_effort
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            timeout=settings.deepseek_timeout_seconds,
        )

    @property
    def name(self) -> str:
        return self._name

    async def plan(
        self,
        question: str,
        tools: list[ToolDefinition],
    ) -> ToolPlan:
        function_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name.value,
                    "description": tool.description,
                    "parameters": _schema_for_model(tool.input_schema),
                },
            }
            for tool in tools
        ]
        try:
            response = await self.client.chat.completions.create(
                model=self.name,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                tools=function_tools,
                tool_choice="required",
                max_tokens=1_200,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except OpenAIError as exc:
            raise AgentModelError("DeepSeek planning request failed") from exc

        tool_calls = response.choices[0].message.tool_calls or []
        if len(tool_calls) != 1:
            raise AgentModelError("DeepSeek must select exactly one tool")
        tool_call = tool_calls[0]
        try:
            arguments = json.loads(tool_call.function.arguments)
            return ToolPlan(
                tool_name=tool_call.function.name,
                arguments=arguments,
                rationale=f"问题需要调用 {tool_call.function.name}。",
            )
        except (TypeError, ValueError) as exc:
            raise AgentModelError("DeepSeek returned an invalid tool plan") from exc

    async def stream_answer(
        self,
        question: str,
        plan: ToolPlan,
        result: dict[str, Any],
    ) -> AsyncIterator[ModelStreamDelta]:
        compact_result = _compact_value(result)
        user_content = json.dumps(
            {
                "question": question,
                "tool_name": plan.tool_name.value,
                "tool_result": compact_result,
            },
            ensure_ascii=False,
        )
        try:
            stream = await self.client.chat.completions.create(
                model=self.name,
                messages=[
                    {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=4_000,
                reasoning_effort=self.reasoning_effort,
                stream=True,
                extra_body={"thinking": {"type": "enabled"}},
            )
            received_content = False
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield ModelStreamDelta(kind="reasoning", content=reasoning)
                content = delta.content
                if content:
                    received_content = True
                    yield ModelStreamDelta(kind="answer", content=content)
        except OpenAIError as exc:
            raise AgentModelError("DeepSeek answer request failed") from exc
        if not received_content:
            raise AgentModelError("DeepSeek returned an empty answer")


def _compact_value(value: Any) -> Any:
    """Bound model context without changing the structured API result."""

    if isinstance(value, dict):
        return {str(key): _compact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_compact_value(item) for item in value[:20]]
        if len(value) > 20:
            items.append({"truncated_items": len(value) - 20})
        return items
    if isinstance(value, str) and len(value) > 300:
        return f"{value[:300]}..."
    return value


def _schema_for_model(value: Any) -> Any:
    """Remove generation hints while preserving the MCP validation contract."""

    if isinstance(value, dict):
        return {
            key: _schema_for_model(item)
            for key, item in value.items()
            if key not in {"default", "examples"}
        }
    if isinstance(value, list):
        return [_schema_for_model(item) for item in value]
    return value
