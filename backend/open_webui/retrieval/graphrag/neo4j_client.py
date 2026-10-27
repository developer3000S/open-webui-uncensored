"""Neo4j gateway for the knowledge-graph layer.

The community image of Neo4j 5.26 is the deployment target, so nothing here may
rely on APOC or GDS (both enterprise-only plugins in practice). Node merge,
relationship merge and vector search are therefore plain Cypher with bound
parameters; the only strings interpolated into query text are relationship
types, which `extractor.canonical_relation_type` has already restricted to
[A-Z0-9_].

Embeddings are 1024-dim (the RAG embedding model in use); the vector index is
created with that dimension and a mismatch fails loudly at DDL time, not at
query time.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)


class GraphUnavailableError(RuntimeError):
    """Neo4j is not configured or not reachable."""


class Neo4jGraph:
    """Driver wrapper with lazy connection and idempotent schema setup."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = 'neo4j',
        embedding_dim: int = 1024,
        vector_index: str = 'entity_embedding',
    ):
        if not uri:
            raise GraphUnavailableError('NEO4J_URI is not configured')
        # Imported lazily so that a deployment without the driver installed can
        # still import the app; graphrag calls surface as GraphUnavailableError.
        try:
            from neo4j import GraphDatabase
        except ImportError as e:
            raise GraphUnavailableError('python "neo4j" package is not installed') from e

        self._uri = uri
        self._database = database
        self._embedding_dim = embedding_dim
        # Parameterized so tests can point at an index of their own dimension;
        # CREATE ... IF NOT EXISTS would silently keep a mismatched existing one.
        self._vector_index = vector_index
        try:
            self._driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=10,
                max_connection_lifetime=600,
                liveness_check_timeout=30,
            )
        except Exception as e:
            raise GraphUnavailableError(f'cannot create Neo4j driver for {uri}: {e}') from e
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def verify(self) -> None:
        try:
            self._driver.verify_connectivity()
        except Exception as e:
            raise GraphUnavailableError(f'Neo4j at {self._uri} is unreachable: {e}') from e

    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass

    def _run(self, cypher: str, **params) -> list[dict]:
        # Consume the result INSIDE the session context: a Result read after the
        # `with` block raises ResultConsumedError (the session discards it on
        # close). Every caller gets plain dicts.
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    def query(self, cypher: str, **params) -> list[dict]:
        return self._run(cypher, **params)

    @staticmethod
    def _count(rows: list[dict], key: str = 'n') -> int:
        return int(rows[0][key]) if rows and rows[0].get(key) is not None else 0

    # ----------------------------------------------------------------- schema

    def _ddl_statements(self) -> tuple:
        idx = self._vector_index
        return (
            'CREATE CONSTRAINT entity_id_gid IF NOT EXISTS FOR (e:Entity) REQUIRE (e.id, e.gid) IS UNIQUE',
            'CREATE CONSTRAINT chunk_id_gid IF NOT EXISTS FOR (c:Chunk) REQUIRE (c.id, c.gid) IS UNIQUE',
            'CREATE INDEX entity_gid IF NOT EXISTS FOR (e:Entity) ON (e.gid)',
            'CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)',
            (
                f'CREATE VECTOR INDEX {idx} IF NOT EXISTS FOR (e:Entity) ON e.embedding '
                'OPTIONS {indexConfig: {`vector.dimensions`: {dim}, '
                "`vector.similarity_function`: 'cosine', `vector.hnsw.m`: 16, "
                '`vector.hnsw.ef_construction`: 100}}'
            ),
        )

    def ensure_schema(self) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            for ddl in self._ddl_statements():
                # .replace, not .format: the vector DDL embeds a Cypher map
                # literal ({indexConfig: {...}}) whose braces .format would try
                # to interpret as fields.
                self._run(ddl.replace('{dim}', str(self._embedding_dim)))
            self._wait_vector_index_online()
            self._schema_ready = True
            log.info(
                'graphrag: Neo4j schema ensured (dim=%s, index=%s)',
                self._embedding_dim,
                self._vector_index,
            )

    def _wait_vector_index_online(self, timeout: float = 180.0) -> None:
        """Block until the vector index reports ONLINE.

        Index creation is asynchronous and db.awaitIndex/db.awaitIndexes are
        unreliable for it (awaitIndex even raises IndexNotFound while the
        schema job is still registering, and a pending DROP of a same-named
        index can make CREATE ... IF NOT EXISTS a no-op followed by nothing).
        Polling the state view is the only version-stable answer.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = self.query(
                'SHOW INDEXES YIELD name, type, state WHERE name = $name AND type = $t RETURN state',
                name=self._vector_index,
                t='VECTOR',
            )
            if rows and rows[0]['state'] == 'ONLINE':
                return
            if rows and rows[0]['state'] == 'FAILED':
                raise GraphUnavailableError(f'vector index {self._vector_index} failed to build')
            time.sleep(0.5)
        raise GraphUnavailableError(f'vector index {self._vector_index} did not come online within {timeout:.0f}s')

    # ------------------------------------------------------------ write paths

    def upsert_chunk(
        self,
        gid: str,
        chunk_id: str,
        chunk_hash: str,
        text: str = '',
        ntokens: int = 0,
        done: bool = False,
    ) -> None:
        # The chunk node exists before extraction and flips `done` after it
        # succeeds, so resume skips only fully processed chunks; a crash between
        # the two re-extracts the chunk (every write below is MERGE-idempotent).
        # `hash` dedupes the file-collection copy against the KB-collection copy
        # of the same text, whose Chroma id differs.
        self._run(
            """
            MERGE (c:Chunk {id: $chunk_id, gid: $gid})
            SET c.hash = $chunk_hash, c.text = $text, c.tokens = $ntokens,
                c.done = $done
            """,
            gid=gid,
            chunk_id=chunk_id,
            chunk_hash=chunk_hash,
            text=text,
            ntokens=ntokens,
            done=done,
        )

    def indexed_chunk_hashes(self, gid: str) -> set[str]:
        rows = self.query('MATCH (c:Chunk {gid: $gid}) WHERE c.done = true RETURN c.hash AS h', gid=gid)
        return {r['h'] for r in rows if r.get('h')}

    def upsert_entities(self, gid: str, entities: list[dict]) -> int:
        """Merge Entity nodes and link them to their source chunks.

        Each item: {id, name, type, description, embedding, chunk_ids}.
        A node carries the union of the chunks it was seen in so retrieval can
        cite provenance.
        """
        if not entities:
            return 0
        result = self._run(
            """
            UNWIND $rows AS row
            MERGE (e:Entity {id: row.id, gid: $gid})
            ON CREATE SET
                e.name = row.name,
                e.type = row.type,
                e.description = row.description,
                e.embedding = row.embedding,
                e.chunks = row.chunk_ids
            ON MATCH SET
                e.name = CASE WHEN size(coalesce(e.name, '')) = 0 THEN row.name ELSE e.name END,
                e.type = CASE WHEN row.type <> '' THEN row.type ELSE e.type END,
                e.description = CASE
                    WHEN size(coalesce(row.description, '')) > size(coalesce(e.description, ''))
                    THEN row.description ELSE e.description END,
                e.embedding = row.embedding
            WITH e, row
            SET e.chunks = [c IN coalesce(e.chunks, []) WHERE NOT c IN row.chunk_ids] + row.chunk_ids
            WITH e, row
            UNWIND row.chunk_ids AS cid
            OPTIONAL MATCH (c:Chunk {id: cid, gid: $gid})
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [c] END |
                MERGE (c)-[:MENTIONS]->(e)
            )
            RETURN count(DISTINCT e) AS n
            """,
            gid=gid,
            rows=entities,
        )
        return self._count(result)

    def upsert_relations(self, gid: str, relations: list[dict]) -> int:
        """Merge relationships between entity ids of the same gid.

        Relationship types vary per document and cannot be parameterized in
        Cypher, so rows are grouped by a sanitized type and one query runs per
        group (a handful of distinct types per chunk in practice).
        """
        if not relations:
            return 0
        groups: dict[str, list[dict]] = {}
        for rel in relations:
            groups.setdefault(rel['type'], []).append(rel)
        total = 0
        for rtype, rows in groups.items():
            if not rtype.isidentifier() or not rtype.isupper():
                log.warning('graphrag: skipping unsafe relationship type %r', rtype)
                continue
            result = self._run(
                f"""
                UNWIND $rows AS row
                MATCH (a:Entity {{id: row.source, gid: $gid}})
                MATCH (b:Entity {{id: row.target, gid: $gid}})
                MERGE (a)-[r:`{rtype}` {{chunk_id: row.chunk_id}}]->(b)
                ON CREATE SET r.strength = row.strength, r.evidence = row.evidence,
                              r.type_name = '{rtype}'
                ON MATCH SET r.strength = CASE WHEN row.strength > coalesce(r.strength, 0)
                                               THEN row.strength ELSE r.strength END,
                             r.evidence = coalesce(r.evidence, row.evidence)
                RETURN count(r) AS n
                """,
                gid=gid,
                rows=rows,
            )
            total += self._count(result)
        return total

    def delete_gid(self, gid: str) -> int:
        """Remove everything a single source contributed (per-file graph state).

        Entities are keyed by (id, gid), so one document's subgraph is exactly
        its nodes and their edges; cross-document merging, if ever added, must
        revisit this.
        """
        result = self._run('MATCH (n {gid: $gid}) DETACH DELETE n RETURN count(n) AS n', gid=gid)
        return self._count(result)

    # ------------------------------------------------------------ read paths

    def vector_search(self, embedding: list[float], limit: int, gid_filter: list[str] | None = None) -> list[dict]:
        where = ''
        params: dict = {'v': embedding, 'limit': int(limit)}
        if gid_filter:
            where = 'WHERE node.gid IN $gids'
            params['gids'] = list(gid_filter)
        return self.query(
            f"""
            CALL db.index.vector.queryNodes('{self._vector_index}', $limit, $v) YIELD node, score
            {where}
            RETURN node.id AS id, node.name AS name, node.type AS type,
                   node.description AS description, node.gid AS gid,
                   node.chunks AS chunks, score
            """,
            **params,
        )

    def neighbors(self, entity_ids: list[tuple[str, str]], depth: int = 1, limit_per: int = 12) -> list[dict]:
        """Expand the entity graph around found entities.

        `entity_ids` is [(id, gid), ...] — the same id under two gids is two
        nodes. Each hop keeps the relationship text and the neighbour summary so
        the assembled context is self-explanatory.

        Every node on the path must be an Entity of the same gid: the structural
        Chunk-[:MENTIONS]->Entity edges otherwise make two entities that merely
        share a chunk look adjacent, and since those edges carry no strength
        they surface at the coalesce() default of 1.0 -- i.e. the noise outscores
        the real relations in the text handed to the model.
        """
        if not entity_ids:
            return []
        rows = [{'id': i, 'gid': g} for i, g in entity_ids if i and g]
        if not rows:
            return []
        depth = max(1, min(int(depth), 3))
        return self.query(
            f"""
            UNWIND $rows AS row
            MATCH (e:Entity {{id: row.id, gid: row.gid}})
            CALL {{
                WITH e
                MATCH path = (e)-[r*1..{depth}]-(m:Entity)
                WHERE m <> e AND ALL(n IN nodes(path) WHERE n:Entity AND n.gid = e.gid)
                WITH e, r, m, length(path) AS hops
                ORDER BY hops ASC, coalesce(r[-1].strength, 1.0) DESC
                LIMIT $limit_per
                RETURN [x IN r | type(x)] AS types,
                       [x IN r | coalesce(x.strength, 1.0)] AS strengths,
                       m.id AS mid, m.gid AS mgid, m.name AS mname,
                       m.type AS mtype, m.description AS mdesc, hops
            }}
            RETURN e.id AS from_id, e.gid AS from_gid, types, strengths,
                   mid, mgid, mname, mtype, mdesc, hops
            """,
            rows=rows,
            limit_per=int(limit_per),
        )

    def stats(self, gid_filter: list[str] | None = None) -> dict:
        params = {'gids': gid_filter} if gid_filter else {}
        where = 'WHERE n.gid IN $gids' if gid_filter else ''
        nodes = self.query(f'MATCH (n:Entity) {where} RETURN count(n) AS c', **params)[0]['c']
        # Entity-to-Entity only: `()`-[]->`(:Entity)` also counts the structural
        # Chunk-[:MENTIONS]->Entity edges and inflates the number.
        where_r = 'WHERE a.gid IN $gids' if gid_filter else ''
        rels = self.query(f'MATCH (a:Entity)-[r]->(b:Entity) {where_r} RETURN count(r) AS c', **params)[0]['c']
        chunks_where = 'WHERE c.gid IN $gids' if gid_filter else ''
        chunks = self.query(f'MATCH (c:Chunk) {chunks_where} RETURN count(c) AS c', **params)[0]['c']
        return {'entities': nodes, 'relations': rels, 'chunks': chunks}

    def top_entities(self, gid: str, limit: int = 20) -> list[dict]:
        rows = self.query(
            """
            MATCH (e:Entity {gid: $gid})
            OPTIONAL MATCH (e)<-[:MENTIONS]-(c:Chunk)
            WITH e, count(c) AS deg
            RETURN e.name AS name, e.type AS type, deg
            ORDER BY deg DESC LIMIT $limit
            """,
            gid=gid,
            limit=int(limit),
        )
        return rows


_graph: Neo4jGraph | None = None
_graph_lock = threading.Lock()


def get_graph() -> Neo4jGraph:
    """Process-wide graph gateway built from the .env-backed config."""
    global _graph
    with _graph_lock:
        if _graph is None:
            from open_webui.config import (
                NEO4J_PASSWORD,
                NEO4J_URI,
                NEO4J_USER,
            )

            _graph = Neo4jGraph(
                uri=NEO4J_URI or '',
                user=NEO4J_USER or 'neo4j',
                password=NEO4J_PASSWORD or '',
            )
        return _graph


def reset_graph_for_tests() -> None:
    global _graph
    with _graph_lock:
        _graph = None
