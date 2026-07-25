"""Tests for the lexical retrieval layer (tokenizer, BM25, prose → seeds)."""

import os

import networkx as nx

from pyvisualizer.api import build_graph
from pyvisualizer.retrieval import (
    BM25Index,
    build_bm25,
    derive_seeds,
    extract_identifiers,
    function_source,
    rank_seeds,
    tokenize,
)


class TestTokenizer:
    def test_splits_snake_and_camel_case(self):
        toks = tokenize("get_user_name GetUserName")
        assert "get_user_name" in toks
        assert "getusername" in toks
        # The words hidden inside both spellings are searchable.
        for word in ("get", "user", "name"):
            assert toks.count(word) >= 2

    def test_plain_words_are_lowercased_once(self):
        assert tokenize("Persist THE record") == ["persist", "the", "record"]


class TestBM25:
    def test_deterministic_and_tiebreak_by_id(self):
        docs = {"beta": ["term"], "alpha": ["term"]}
        idx = BM25Index(docs)
        first = idx.search("term")
        second = BM25Index(docs).search("term")
        assert first == second
        # Equal scores break ties on document id, not insertion order.
        assert [d for d, _ in first] == ["alpha", "beta"]

    def test_search_returns_at_most_k(self):
        docs = {f"d{i}": ["term"] for i in range(10)}
        assert len(BM25Index(docs).search("term", k=3)) == 3

    def test_no_match_is_empty_not_error(self):
        assert BM25Index({"a": ["x"]}).search("zzz") == []

    def test_index_covers_function_bodies(self, repo_before_after):
        result = build_graph(repo_before_after)
        idx = build_bm25(result.graph)
        # "stored" appears only inside _write's body — never in a name.
        hits = idx.search("stored")
        assert hits and hits[0][0] == "core._write"


class TestFunctionSource:
    def test_missing_file_degrades_to_empty(self):
        assert function_source("/no/such/file.py", 1, 5) == ""

    def test_bad_range_degrades_to_single_line(self, tmp_path):
        p = tmp_path / "m.py"
        p.write_text("def f():\n    return 1\n")
        assert function_source(str(p), 1, 0) == "def f():\n"
        assert function_source(str(p), 0, 2) == ""

    def test_non_utf8_bytes_do_not_crash(self, tmp_path):
        p = tmp_path / "junk.py"
        p.write_bytes(b"def f():\n    return '\xff\xfe'\n")
        src = function_source(str(p), 1, 2)
        assert "def f" in src


class TestSeeds:
    def test_backticked_names_rank_first(self, repo_before_after):
        result = build_graph(repo_before_after)
        seeds = derive_seeds("the `audit` hook breaks persist somehow", result.graph)
        assert seeds[0] == "service.audit"
        assert "core.persist" in seeds

    def test_prose_without_identifiers_yields_nothing(self, repo_before_after):
        result = build_graph(repo_before_after)
        assert derive_seeds("this should have been the expected result", result.graph) == []

    def test_hopelessly_generic_token_is_skipped(self):
        G = nx.DiGraph()
        G.add_nodes_from(f"mod{i}.duplicated" for i in range(6))
        assert derive_seeds("fix `duplicated` behaviour", G) == []

    def test_extract_identifiers_drops_stopwords_and_short_tokens(self):
        toks = extract_identifiers("the value of `place_order` should return None ok")
        assert toks == ["place_order"]


class TestRankSeeds:
    def test_symbol_seeds_come_first_then_bm25_fills(self, repo_before_after):
        result = build_graph(repo_before_after)
        idx = build_bm25(result.graph)
        seeds = rank_seeds("fix `persist` in the order flow", result.graph, idx, k=3)
        assert seeds[0][0] == "core.persist" and seeds[0][2] == "symbol"
        assert len(seeds) <= 3
        assert len({node for node, _, _ in seeds}) == len(seeds)  # deduped

    def test_deterministic(self, repo_before_after):
        result = build_graph(repo_before_after)
        idx = build_bm25(result.graph)
        a = rank_seeds("audit the persisted record", result.graph, idx)
        b = rank_seeds("audit the persisted record", result.graph, idx)
        assert a == b
