"""基于 DeepSeek 的问题规划与答案生成，提供可测试的接口。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from openai import AsyncOpenAI, OpenAIError

from tara_agent.agent.context import build_answer_model_input
from tara_agent.agent.models import (
    ModelStreamDelta,
    ModelUsage,
    ToolDefinition,
    ToolPlan,
)
from tara_agent.config import Settings

PLANNER_SYSTEM_PROMPT = """
你是 Tara Agent 的任务规划组件。针对用户提出的 Tara Oceans 问题，从可用的 MCP 工具中
选择且仅选择一个工具。不得建议执行 Python、SQL、文件系统访问或任何未列出的工具。
必须调用且仅调用一个已提供的工具，参数必须严格符合该工具的输入结构。
涉及标记分析时必须明确使用 v4 或 v9。除非用户明确要求子字符串匹配，否则分类学查询
默认使用层级匹配。不得虚构用户没有提供的样本 ID、标记、分类单元、筛选值或环境变量。

参数规则：
- 只有用户明确提出某项约束时，才加入对应的可选筛选参数。
- 保留问题中的学名和准确样本 ID。
- 将用户给出的中文地名转换为数据集使用的英文名称，例如将“地中海”转换为
  “Mediterranean”。
- 用户明确只要一条结果时，将对应的结果数量上限设为 1。

工具选择规则：
- 仅当用户给出准确样本 ID 时使用 get_sample_info。
- 用户按地点或环境条件查找、筛选或列出样本时使用 find_samples。
- 列出匹配的 ASV 或分类学出现情况时使用 find_taxa，不用它计算丰度。
- 只有查询原始测序读数或相对丰度时使用 taxon_abundance。
- 只有查询观测 ASV 丰富度或 Shannon 多样性时使用 diversity_analysis。
- 只有查询与允许使用的某个环境变量之间的相关性时使用 environment_association。
""".strip()

ANSWER_SYSTEM_PROMPT = """
你是 Tara Agent。只能依据所提供的确定性工具结果回答用户问题。回答应使用中文，简洁、
清晰并保持科学审慎。不得虚构结果中不存在的数值、因果关系或分析。V4 与 V9 是相互独立
的标记，不得直接合并解释。

回答结构：
1. 先直接回答用户的核心问题。
2. 再概括支持结论的关键数量、趋势或统计结果。
3. 只有在会影响结果解释时，才简要说明数据范围、缺失值处理或方法限制。

界面会单独展示图表和结构化结果，因此不得逐条复述样本、ASV、观测值或相关性数据，
不得列出前若干条记录作为示例，也不得输出原始 JSON。提供给你的工具结果是用于组织回答
的摘要，完整明细由应用直接展示。若摘要中包含分页信息，只需准确说明查询结果总数，
不要推断或描述当前页实际展示了多少条明细。
""".strip()

class AgentModelError(RuntimeError):
    """语言模型返回无法使用的回复时抛出。"""


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
    """使用 DeepSeek 兼容 OpenAI 的 Chat Completions API。"""

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

    @property
    def provider(self) -> str:
        return "deepseek"

    @property
    def trace_parameters(self) -> dict[str, Any]:
        """返回不含密钥、可用于链路追踪的模型请求配置。"""

        return {
            "planner": {
                "max_tokens": 1_200,
                "thinking": "disabled",
            },
            "answer": {
                "max_tokens": 4_000,
                "reasoning_effort": self.reasoning_effort,
                "thinking": "enabled",
            },
        }

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
                usage=_model_usage(getattr(response, "usage", None)),
            )
        except (TypeError, ValueError) as exc:
            raise AgentModelError("DeepSeek returned an invalid tool plan") from exc

    async def stream_answer(
        self,
        question: str,
        plan: ToolPlan,
        result: dict[str, Any],
    ) -> AsyncIterator[ModelStreamDelta]:
        user_content = json.dumps(
            build_answer_model_input(question, plan.tool_name, result),
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
                stream_options={"include_usage": True},
                extra_body={"thinking": {"type": "enabled"}},
            )
            received_content = False
            async for chunk in stream:
                usage = _model_usage(getattr(chunk, "usage", None))
                if usage is not None:
                    yield ModelStreamDelta(kind="usage", usage=usage)
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


def _schema_for_model(value: Any) -> Any:
    """移除生成提示，同时保留 MCP 校验契约。"""

    if isinstance(value, dict):
        return {
            key: _schema_for_model(item)
            for key, item in value.items()
            if key not in {"default", "examples"}
        }
    if isinstance(value, list):
        return [_schema_for_model(item) for item in value]
    return value


def _model_usage(value: Any) -> ModelUsage | None:
    """把兼容 OpenAI 的用量对象转换为稳定的内部结构。"""

    if value is None:
        return None
    prompt_details = getattr(value, "prompt_tokens_details", None)
    completion_details = getattr(value, "completion_tokens_details", None)
    return ModelUsage(
        input_tokens=value.prompt_tokens,
        output_tokens=value.completion_tokens,
        total_tokens=value.total_tokens,
        cached_tokens=getattr(prompt_details, "cached_tokens", None),
        reasoning_tokens=getattr(completion_details, "reasoning_tokens", None),
    )
