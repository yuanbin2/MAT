"""检索：打分、按元数据过滤、取 top-k。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .entities import wants_historical
from .index import BM25Index, load_index
from .tokenizer import content_tokens, tokenize

ALIAS_WEIGHT = 0.6
#: 单字（“月”“日”“店”）在二元组的世界里基本是噪声，降权但不丢弃。
SINGLE_CHAR_WEIGHT = 0.3
YEAR_PENALTY = 0.25
FUTURE_PENALTY = 0.6
STORE_HINT_BOOST = 1.15
#: 问某个时间窗里“出了什么事”时，正好在这个窗里生效的文档最可能是答案。
WINDOW_BOOST = 1.8
#: 文档级先验：一篇文档整体命中得好，它的其它片段也更可能是答案所在。
#: 英文邮件里“赔了多少钱”的那一段本身不含任何中文查询词，靠的就是这一项。
DOC_PRIOR = 0.35
#: 别名词典本身不是答案，得压一压，不然它永远排第一。
ALIAS_DOC_PENALTY = 0.5
#: 周报、纪要里的数字是人工估的，问数字的时候给它们降点权。
ESTIMATE_DOC_PENALTY = 0.7
#: 检索接口（`expand=False`）里一篇文档最多占一格：多留几篇不同的文档，
#: 比同一篇留两段有用。实测支持这一点：自拟题 X04「Super Souper 晚上几点关门」
#: 放开到两格后，KB-030 的第二块会把 gold 文档 KB-062 挤出 top-5。
MAX_CHUNKS_PER_DOC = 1
#: 问答链路（`expand=True`）放宽到两格。实测反过来的教训：
#: 「冷萃乌龙茶上市第一个月的销量达标了吗」——匹配到商品名的是 KB-028 第 1 块，
#: 而"首月目标 900 杯"在第 3 块，只占一格时第 3 块连候选都排不进，
#: 模型只能答"知识库里没有查到目标数值"。
QA_CHUNKS_PER_DOC = 2
#: 问答链路额外把命中片段的**相邻片段**一起给模型：切块是把连续正文切开，
#: 命中点前后一格常是同一句话/同一条目的另一半（英文邮件里赔款金额就在
#: 命中片段的前一块）。检索接口不做扩展——契约要求它恰好返回 top_k 条。
EXPAND_NEIGHBOURS = 1
#: 相邻扩展最多补几条，避免一次塞太多无关正文进模型上下文。
EXPAND_MAX_EXTRA = 6
#: 只给**最相关这几篇**补上下文。全部命中都补会让模型看到太多候选，
#: 实测把「牛肉poke 有哪些过敏原」的引用从 2 份撑到 3 份（cite_max=2 就不满足了）。
EXPAND_TOP_DOCS = 3


@dataclass
class Hit:
    doc_id: str
    chunk_id: str
    score: float
    text: str
    source_text: str
    meta: dict
    kind: str = "text"
    table_header: list[str] = field(default_factory=list)
    dropped_instructions: list[str] = field(default_factory=list)
    padded: bool = False
    """凑数补上的：契约 §4 要求恰好返回 top_k 条，但问答链路不会用它作答。"""
    sibling: bool = False
    """相邻扩展补上的：问答链路额外拿的上下文，检索接口不会产生这种条目。"""

    def as_result(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "score": round(self.score, 4),
            "text": self.text,
        }


@dataclass
class SearchResult:
    hits: list[Hit]
    query: str
    terms: list[str]
    expansions: list[str]
    filtered: list[dict]
    coverage: float = 0.0
    #: 本次检索实际用的约束（面板要看「检索范围」是不是符合预期）。
    as_of: Optional[str] = None
    store_id: Optional[str] = None
    year: Optional[int] = None
    window: Optional[tuple[str, str]] = None
    historical: Optional[bool] = None

    @property
    def ranked(self) -> list[Hit]:
        """真正命中的片段（不含为了凑满 top_k 补上的那些）。"""
        return [hit for hit in self.hits if not hit.padded]

    def as_trace(self) -> dict:
        return {
            "query": self.query,
            "expansions": self.expansions,
            "coverage": round(self.coverage, 3),
            "as_of": self.as_of,
            "store_id": self.store_id,
            "year": self.year,
            "window": list(self.window) if self.window else None,
            "historical": self.historical,
            "hits": [
                {
                    "doc_id": hit.doc_id,
                    "chunk_id": hit.chunk_id,
                    "score": round(hit.score, 4),
                    "padded": hit.padded,
                    "sibling": hit.sibling,
                    "kind": hit.kind,
                    "preview": hit.text[:120],
                    "dropped_instructions": hit.dropped_instructions,
                }
                for hit in self.hits
            ],
            "filtered": self.filtered,
        }


class Retriever:
    def __init__(self, index: BM25Index, today: date) -> None:
        self.index = index
        self.today = today
        self._effective_to: dict[str, Optional[str]] = {}
        self._in_chain: set[str] = set()
        for doc_id, meta in index.docs_meta.items():
            successor = meta.get("superseded_by")
            if successor and successor in index.docs_meta:
                self._effective_to[doc_id] = index.docs_meta[successor].get("effective_from")
                self._in_chain.add(doc_id)
                self._in_chain.add(successor)

    # -- 元数据过滤 -------------------------------------------------------------

    def _eligible(
        self, doc_id: str, as_of: date, store_id: Optional[str], historical: bool = False
    ) -> Optional[str]:
        """返回排除原因；返回 None 表示这篇文档可以进入打分。

        问的就是“以前那一版”时（`historical`），不再按生效时间过滤：
        否则已废止的文档永远取不回来，而它恰恰是答案。
        """
        meta = self.index.docs_meta.get(doc_id, {})
        if store_id and meta.get("stores_explicit") and store_id not in (meta.get("stores") or []):
            return "文档声明只适用于 %s，与问题里的 %s 不符" % (",".join(meta.get("stores") or []), store_id)
        if historical:
            return None
        ends = self._effective_to.get(doc_id)
        # 只有标了“已废止”的才按取代关系挡掉，别的版本照常参与打分。
        if meta.get("status") == "已废止" and ends and as_of.isoformat() >= ends:
            return "该版本自 %s 起已被 %s 取代" % (ends, meta.get("superseded_by"))
        starts = meta.get("effective_from")
        if starts and starts > as_of.isoformat() and doc_id in self._in_chain:
            return "该版本自 %s 起才生效，晚于问题所指的 %s" % (starts, as_of.isoformat())
        return None

    def _multiplier(
        self,
        doc_id: str,
        as_of: date,
        store_id: Optional[str],
        year: Optional[int],
        window: Optional[tuple[str, str]],
        numeric: bool = False,
    ) -> float:
        meta = self.index.docs_meta.get(doc_id, {})
        factor = 1.0
        title_year = meta.get("title_year")
        if year and title_year and int(title_year) != int(year):
            factor *= YEAR_PENALTY
        starts = meta.get("effective_from")
        if starts and starts > as_of.isoformat():
            factor *= FUTURE_PENALTY
        if store_id and store_id in (meta.get("stores") or []):
            factor *= STORE_HINT_BOOST
        if window and starts and window[0] <= starts <= window[1]:
            factor *= WINDOW_BOOST
        if doc_id == self.index.aliases.source_doc:
            factor *= ALIAS_DOC_PENALTY
        if numeric and meta.get("estimates_only"):
            factor *= ESTIMATE_DOC_PENALTY
        return factor

    # -- 检索 -------------------------------------------------------------------

    def _weights(self, query: str) -> dict[str, float]:
        weights: dict[str, float] = {}
        for token in tokenize(query):
            weight = SINGLE_CHAR_WEIGHT if len(token) == 1 else 1.0
            weights[token] = weights.get(token, 0.0) + weight
        return weights

    def _concept_scores(
        self, query: str, allowed: set[int]
    ) -> tuple[dict[int, float], list[str]]:
        """别名按“同一个东西”合并：一个概念只算它最像的那一种写法，不叠加。

        不这么做的话，同时列出全部写法的别名词典自己会永远排第一。
        """
        merged: dict[int, float] = {}
        expansions: list[str] = []
        for canonical in self.index.aliases.mentions(query) + self._store_concepts(query):
            variants = self.index.aliases.variants(canonical)
            best: dict[int, float] = {}
            for variant in variants:
                weights = {token: ALIAS_WEIGHT for token in tokenize(variant)}
                if not weights:
                    continue
                for position, score in self.index.score_terms(weights, allowed).items():
                    if score > best.get(position, 0.0):
                        best[position] = score
            for position, score in best.items():
                merged[position] = merged.get(position, 0.0) + score
            expansions.extend(variants)
        return merged, expansions

    def _history_factor(self, doc_id: str, historical: Optional[bool]) -> float:
        """问旧口径时，已废止的那一版才是答案，给它加权。"""
        if not historical:
            return 1.0
        meta = self.index.docs_meta.get(doc_id, {})
        return 1.6 if meta.get("superseded_by") else 0.8

    def _store_concepts(self, query: str) -> list[str]:
        import re

        found = []
        for code in re.findall(r"\bs\d{2}\b", query.lower()):
            canonical = self.index.aliases.by_store_code(code)
            if canonical:
                found.append(canonical)
        return found

    def _hit(
        self,
        position: int,
        score: float,
        filtered: list[dict],
        padded: bool = False,
        sibling: bool = False,
    ) -> Hit:
        chunk = self.index.chunks[position]
        return Hit(
            doc_id=chunk.doc_id,
            chunk_id=chunk.chunk_id,
            score=score,
            text=chunk.text,
            source_text=chunk.source_text,
            meta=self.index.docs_meta.get(chunk.doc_id, {}),
            kind=chunk.kind,
            table_header=chunk.table_header,
            padded=padded,
            sibling=sibling,
        )

    def _expand_neighbours(
        self,
        hits: list[Hit],
        adjusted: list[tuple[float, int]],
        taken: set[int],
        allowed: set[int],
    ) -> list[Hit]:
        """把命中片段的前后各 ``EXPAND_NEIGHBOURS`` 格补进来（问答链路专用）。

        切块是把连续正文切开，命中点前后一格常常就是同一句话/同一条目的另一半：
        「供应商后来赔了多少」里，赔款金额 `CNY 8,600` 正好落在命中片段的**前一块**。
        只给基础结果时，模型看到的是被截断的半句话，只能答"没查到"。
        """
        score_of = {position: score for score, position in adjusted}
        by_chunk_id: dict[str, int] = {}
        for position in allowed:
            by_chunk_id[self.index.chunks[position].chunk_id] = position

        # 只给最相关的几篇补：全补会让模型手上候选太多，引用容易发散。
        top_docs: list[str] = []
        for hit in hits:
            if hit.doc_id not in top_docs:
                top_docs.append(hit.doc_id)
        top_docs = top_docs[:EXPAND_TOP_DOCS]

        extra: list[Hit] = []
        for hit in hits:
            if hit.doc_id not in top_docs:
                continue
            if len(extra) >= EXPAND_MAX_EXTRA:
                break
            try:
                number = int((hit.chunk_id.split("#") or ["", "0"])[-1])
            except ValueError:
                continue
            for delta in range(-EXPAND_NEIGHBOURS, EXPAND_NEIGHBOURS + 1):
                if delta == 0 or len(extra) >= EXPAND_MAX_EXTRA:
                    continue
                neighbour_id = "%s#%d" % (hit.doc_id, number + delta)
                position = by_chunk_id.get(neighbour_id)
                if position is None or position in taken:
                    continue
                taken.add(position)
                extra.append(
                    self._hit(position, score_of.get(position, 0.0), [], sibling=True)
                )
        return hits + extra

    def search(
        self,
        query: str,
        top_k: int = 5,
        as_of: Optional[date] = None,
        store_id: Optional[str] = None,
        year: Optional[int] = None,
        window: Optional[tuple[str, str]] = None,
        numeric: bool = False,
        historical: Optional[bool] = None,
        expand: bool = False,
    ) -> SearchResult:
        """``expand=True`` 时额外补上命中片段的相邻片段（只在问答链路用）。

        `/api/retrieve` 不能开：契约 §4 要求索引够的时候**恰好**返回 top_k 条。
        """
        as_of = as_of or self.today
        if historical is None:
            # `/api/retrieve` 没有规划器，问句里的“旧口径/以前”只能在这里认。
            historical = wants_historical(query)
        filtered: list[dict] = []
        excluded: set[str] = set()
        for doc_id in self.index.docs_meta:
            reason = self._eligible(doc_id, as_of, store_id, historical)
            if reason:
                excluded.add(doc_id)
                filtered.append({"doc_id": doc_id, "reason": reason})
        # 版本/门店过滤必须在打分之前：被排除的文档根本不该进入候选，
        # 否则它们会占用 top_k 名额、取完再删，导致结果不足 top_k。
        allowed = set(
            position
            for position in range(len(self.index.chunks))
            if self.index.chunks[position].doc_id not in excluded
        )

        scores = self.index.score_terms(self._weights(query), allowed)
        concepts, expansions = self._concept_scores(query, allowed)
        for position, score in concepts.items():
            scores[position] = scores.get(position, 0.0) + score
        best_of_doc: dict[str, float] = {}
        for position, score in scores.items():
            doc_id = self.index.chunks[position].doc_id
            best_of_doc[doc_id] = max(best_of_doc.get(doc_id, 0.0), score)
        adjusted: list[tuple[float, int]] = []
        for position, score in scores.items():
            doc_id = self.index.chunks[position].doc_id
            total = score + DOC_PRIOR * best_of_doc.get(doc_id, 0.0)
            adjusted.append(
                (
                    total
                    * self._multiplier(doc_id, as_of, store_id, year, window, numeric)
                    * self._history_factor(doc_id, historical),
                    position,
                ),
            )
        adjusted.sort(key=lambda item: (-item[0], item[1]))

        per_doc_limit = QA_CHUNKS_PER_DOC if expand else MAX_CHUNKS_PER_DOC
        hits: list[Hit] = []
        taken: set[int] = set()
        per_doc: dict[str, int] = {}
        for score, position in adjusted:
            chunk = self.index.chunks[position]
            if per_doc.get(chunk.doc_id, 0) >= per_doc_limit:
                continue
            per_doc[chunk.doc_id] = per_doc.get(chunk.doc_id, 0) + 1
            taken.add(position)
            # doc_id / chunk_id / text 都来自同一块真实片段，不做任何重写。
            hits.append(self._hit(position, score, filtered))
            if len(hits) >= top_k:
                break

        # 契约 §4：索引里的片段够的时候必须恰好给 top_k 条。
        # 每篇文档只占一格的规则、以及“一个词都没命中”的片段，都可能让结果不足，
        # 这里按分数从高到低补齐；补上的标成 padded，问答链路不会拿它们作答。
        if len(hits) < top_k:
            scored = {position for _, position in adjusted}
            remaining = [(score, position) for score, position in adjusted if position not in taken]
            # 一个词都没命中的片段用来垫最后几格：每篇文档先出一段，
            # 同一篇连着占满几格没什么意义。
            unscored: dict[str, list[int]] = {}
            for position in sorted(allowed):
                if position in taken or position in scored:
                    continue
                unscored.setdefault(self.index.chunks[position].doc_id, []).append(position)
            while any(unscored.values()):
                for positions in unscored.values():
                    if positions:
                        remaining.append((0.0, positions.pop(0)))
            for score, position in remaining:
                if len(hits) >= top_k:
                    break
                taken.add(position)
                hits.append(self._hit(position, score, filtered, padded=True))
            # 契约 §4 还要求“按相关性从高到低”：补齐之后整体再排一次。
            # 每篇文档只占一格是挑片段的规则，不是排序的规则。
            hits.sort(key=lambda hit: -hit.score)

        if expand:
            hits = self._expand_neighbours(hits, adjusted, taken, allowed)

        return SearchResult(
            hits=hits,
            query=query,
            terms=content_tokens(query),
            expansions=expansions,
            filtered=filtered,
            coverage=self._coverage(query, adjusted, top_k),
            as_of=as_of.isoformat(),
            store_id=store_id,
            year=year,
            window=window,
            historical=historical,
        )

    def _coverage(self, query: str, adjusted: list[tuple[float, int]], top_k: int) -> float:
        """问题被最好的那几个片段覆盖了多少。

        只看真正命中的片段：一个词都没命中时（“zzzqqq”），覆盖率就是 0，
        这是定义，不是异常——为了凑满 top_k 补上的片段不参与这个判断。
        """
        candidates = adjusted[: max(1, top_k)]
        if not candidates:
            return 0.0
        terms = content_tokens(query)
        return max(self.index.coverage(terms, position) for _, position in candidates)


def build_retriever(kb_dir: Path, index_path: Path, today: date, rebuild: bool = False) -> Retriever:
    return Retriever(load_index(kb_dir, index_path, rebuild=rebuild), today)
