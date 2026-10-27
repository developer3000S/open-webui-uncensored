"""Tests for Sprint 2 features: query rewriting, cross-encoder stage, shadow mode.

Run: python3 backend/tests/test_orch_sprint2.py  (no external deps needed)
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
# graphrag modules import lazily from open_webui internals; keep pure-python parts.
from open_webui.retrieval.graphrag.query_rewrite import (  # noqa: E402
    causal_variant,
    decompose_compound,
    rewrite_variants,
    topic_pinned_variant,
)


def test_comparison_decomposition():
    variants = decompose_compound('Сравнi подход Waterfall и Agile по рискам', intent='comparison')
    assert 'Waterfall' in variants[0] or 'Agile' in variants[-1]
    assert len(variants) >= 2
    # primary phrasing preserved among variants
    assert any('Waterfall' in v and 'Agile' in v for v in variants)


def test_causal_variant():
    assert causal_variant('Почему упала производительность?') != []
    assert causal_variant('Какая столица Франции?') == []


def test_topic_pin_for_short_followups():
    history = [{'role': 'user', 'content': 'Расскажи про архитектуру микросервисов в Kubernetes'}]
    out = topic_pinned_variant('А как масштабировать?', history)
    assert out and 'Kubernetes' in out[0]
    # long queries are not pinned
    assert topic_pinned_variant('как правильно настроить горизонтальное автомасштабирование подсистемы', history) == []


def test_rewrite_dedupe_and_cap():
    out = rewrite_variants('Простой вопрос про бюджеты', max_variants=4)
    assert out[0] == 'Простой вопрос про бюджеты'
    assert len(out) <= 4
    assert len({v.lower() for v in out}) == len(out)


def test_hyde_off_by_default(monkeypatch=None):
    os.environ.pop('ORCH_HYDE', None)
    from open_webui.retrieval.graphrag.query_rewrite import hyde_lite

    assert hyde_lite('что такое Redis', ['Redis']) == []


def test_shadow_sampling_is_stable_and_bounded():
    """Mirror of orchestration's bucketing expression (deterministic, 0..100)."""

    def bucket(request_id: str) -> int:
        return int(request_id[:8], 16) % 100

    ids = [f'{i:08x}deadbeef' for i in range(1000)]
    assert all(0 <= bucket(r) < 100 for r in ids)
    # percent=0 → nobody sampled; percent=50 → roughly half (statistical bound)
    sampled = sum(1 for r in ids if bucket(r) < 50)
    assert 400 < sampled < 600


def test_settings_have_new_flags():
    from open_webui.retrieval.graphrag.settings import OrchestratorSettings

    s = OrchestratorSettings()
    assert isinstance(s.shadow_percent, int) and isinstance(s.eval_llm_enabled, bool)
    d = s.to_dict()
    assert 'shadow_percent' in d and 'eval_llm_enabled' in d


def test_explain_trace_projection(tmp_path=None):
    from open_webui.retrieval.graphrag import trace_store
    from open_webui.retrieval.graphrag.orch_api import explain_trace

    payload = {
        'trace_id': 'tr-exp-1', 'request_id': 'req-1', 'tenant_id': 't', 'user_id': 'u',
        'query_analysis': {'intent': 'definition'},
        'execution_plan': {'mode': 'single', 'rationale': 'fast path'},
        'pipeline_runs': [{'pipeline': 'native_rag', 'status': 'success', 'latency_ms': 120}],
        'evaluation_report': {'confidence': 0.7},
        'final_response': {'status': 'answered', 'confidence': 0.7, 'citations': []},
        'total_latency_ms': 130, 'total_cost_units': 0.05, 'warnings': [],
    }
    trace_store.store_trace(payload)
    ex = asyncio.run(_explain('tr-exp-1'))
    assert ex is not None
    assert ex['rationale'] == 'fast path'
    assert ex['pipelines'][0]['pipeline'] == 'native_rag'
    assert ex['status'] == 'answered'


async def _explain(trace_id):
    from open_webui.retrieval.graphrag import orch_api

    return await orch_api.explain_trace(trace_id)


def test_followup_suggestions():
    from open_webui.retrieval.graphrag.orch_api import followup_suggestions

    out = followup_suggestions('что такое Redis', ['Redis', 'Kafka', 'RabbitMQ'])
    assert 'Kafka' in ''.join(out) and 'Redis' not in ''.join(out)
    assert len(out) <= 3


if __name__ == '__main__':
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except Exception as e:
                fails += 1
                print(f'FAIL {name}: {e}')
    raise SystemExit(1 if fails else 0)
