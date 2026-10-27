"""Sprint 3–4 tests: persistent cache, circuit breaker, followups, CE rerank."""

import asyncio
import os
import tempfile
import time

import pytest


@pytest.fixture()
def orch_db(monkeypatch):
    """Isolated DATA_DIR + fresh trace_store connection per test."""
    from open_webui.retrieval.graphrag import trace_store

    monkeypatch.setenv('DATA_DIR', tempfile.mkdtemp())
    monkeypatch.setattr(trace_store, '_conn_cache', None)
    yield trace_store
    if trace_store._conn_cache is not None:
        trace_store._conn_cache.close()
        monkeypatch.setattr(trace_store, '_conn_cache', None)


class TestPersistentCache:
    def test_roundtrip_and_expiry(self, orch_db):
        ts = orch_db
        ts.cache_put('k1', {'status': 'answered'}, 60)
        got = ts.cache_get('k1')
        assert got is not None and got[1]['status'] == 'answered'
        ts.cache_put('expired', {'x': 1}, -1)
        assert ts.cache_get('expired') is None

    def test_miss_returns_none(self, orch_db):
        assert orch_db.cache_get('nope') is None

    def test_overwrite(self, orch_db):
        orch_db.cache_put('dup', {'v': 1}, 60)
        orch_db.cache_put('dup', {'v': 2}, 60)
        assert orch_db.cache_get('dup')[1]['v'] == 2

    def test_orchestration_layer_cache(self, orch_db, monkeypatch):
        """_cache_get/_cache_put in orchestration ride the DB layer."""
        from open_webui.retrieval.graphrag import orchestration as o

        o._cache.clear()
        o._cache_put('key-x', {'status': 'answered'}, 60)
        # simulate restart: drop memory copy, persistence must serve it
        o._cache.clear()
        entry = o._cache_get('key-x')
        assert entry is not None and entry['status'] == 'answered'
        # expired TTL never served
        o._cache_put('key-y', {'status': 'answered'}, -5)
        o._cache.clear()
        assert o._cache_get('key-y') is None


class TestCircuitBreaker:
    def test_lifecycle(self):
        from open_webui.retrieval.graphrag.circuit_breaker import CircuitBreakerRegistry

        cb = CircuitBreakerRegistry(threshold=2, reset_s=0.15)
        assert cb.allow('neo4j')
        cb.record_failure('neo4j')
        assert cb.allow('neo4j'), 'below threshold stays closed'
        cb.record_failure('neo4j')
        assert not cb.allow('neo4j'), 'open after threshold'
        assert cb.status()['neo4j'] == 'open'
        time.sleep(0.16)
        assert cb.allow('neo4j'), 'half-open probe allowed after cool-off'
        cb.record_success('neo4j')
        assert cb.status()['neo4j'] == 'closed'

    def test_failure_reopens(self):
        from open_webui.retrieval.graphrag.circuit_breaker import CircuitBreakerRegistry

        cb = CircuitBreakerRegistry(threshold=1, reset_s=0.05)
        cb.record_failure('emb')
        assert not cb.allow('emb')
        time.sleep(0.06)
        assert cb.allow('emb')
        cb.record_failure('emb')
        assert not cb.allow('emb'), 'probe failure re-opens immediately'

    def test_graph_adapter_skips_when_open(self, monkeypatch):
        """run_graph returns failed/circuit_open without touching Neo4j."""
        from open_webui.retrieval.graphrag import pipeline_adapters as pa
        from open_webui.retrieval.graphrag.circuit_breaker import registry

        for _ in range(registry._threshold):
            registry.record_failure('neo4j')
        try:
            task = type('T', (), {'task_id': 't', 'pipeline': 'graph_rag', 'parameters': {}, 'timeout_ms': 100})()
            ctx = type('C', (), {'items': [], 'normalized_query': 'q', 'request_id': 'r'})()
            cand = asyncio.run(pa.run_graph(task, ctx, None, {'embedding_function': lambda *a, **k: None}))
            assert cand.status == 'failed'
            assert cand.error_code == 'circuit_open'
        finally:
            registry._breakers.pop('neo4j', None)


class TestFollowups:
    def test_dedupe_and_limit(self):
        from open_webui.retrieval.graphrag.orch_api import followup_suggestions

        out = followup_suggestions('что про Нейрон', ['Нейрон', 'Вектор', 'Граф', 'Модель'])
        assert 'Подробнее про «Нейрон»?' not in out  # already in query
        assert len(out) == 3

    def test_empty_entities(self):
        from open_webui.retrieval.graphrag.orch_api import followup_suggestions

        assert followup_suggestions('q', []) == []


class TestCEReranker:
    def test_disabled_passthrough(self, monkeypatch):
        from open_webui.retrieval.graphrag.reranker import rerank_documents

        monkeypatch.delenv('ORCH_CE_RERANK', raising=False)
        docs, metas = asyncio.run(rerank_documents('q', ['a', 'b'], [{}, {}]))
        assert docs == ['a', 'b']

    def test_enabled_but_model_missing_falls_back(self, monkeypatch):
        import open_webui.retrieval.graphrag.reranker as rr

        monkeypatch.setenv('ORCH_CE_RERANK', 'true')
        monkeypatch.setattr(rr, '_model', None)
        monkeypatch.setattr(rr, '_model_failed', False)
        monkeypatch.setitem(__import__('sys').modules, 'sentence_transformers', None)  # force ImportError
        docs, metas = asyncio.run(rr.rerank_documents('q', ['a', 'b'], [{'i': 1}, {'i': 2}]))
        assert docs == ['a', 'b'], 'model failure must keep original order'
        assert rr._model_failed is True, 'failure cached, no retry storm'

    def test_ordering_with_fake_model(self, monkeypatch):
        import open_webui.retrieval.graphrag.reranker as rr

        class FakeCE:
            def predict(self, pairs):
                return [len(d) for _, d in pairs]  # longer doc = higher score

        monkeypatch.setenv('ORCH_CE_RERANK', 'true')
        monkeypatch.setattr(rr, '_model', FakeCE())
        monkeypatch.setattr(rr, '_model_failed', False)
        docs, metas = asyncio.run(rr.rerank_documents('q', ['a', 'ccc', 'bb'], [{'i': 1}, {'i': 2}, {'i': 3}]))
        assert docs == ['ccc', 'bb', 'a']
        assert [m['i'] for m in metas] == [2, 3, 1]
