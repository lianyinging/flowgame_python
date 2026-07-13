"""HACR 分块与检索单元测试。"""
from __future__ import annotations

import os
import unittest

from src.flowgame.qdrant.hacr_config import CHUNKING_VERSION_LLM_HACR
from src.flowgame.qdrant.hacr_llm_chunker import (
    _parse_llm_themes,
    process_document,
)
from src.flowgame.qdrant.hacr_section_parser import parse_md_sections
from src.flowgame.tinyflow_config import (
    _dedupe_hacr_document_hits,
    _qdrant_hit_to_document,
)


class HacrThemeParserTest(unittest.TestCase):
    def test_parse_llm_themes_one_theme_one_child(self) -> None:
        document = "## 返现规则\n自己买卡激活后可申请返现。\n\n## 配送说明\n全国包邮。"
        data = {
            "themes": [
                {
                    "theme_title": "返现规则",
                    "retrieval_text": "自己买卡有返现吗？购卡返现条件",
                    "original_content": "自己买卡激活后可申请返现。",
                },
                {
                    "theme_title": "配送说明",
                    "retrieval_text": "是否包邮？配送范围",
                    "original_content": "全国包邮。",
                },
            ]
        }
        chunks = _parse_llm_themes(data, document_text=document)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].child_index, 0)
        self.assertIn("返现", chunks[0].snippet)
        self.assertIn("自己买卡激活", chunks[0].parent_text)
        self.assertIn("全国包邮", chunks[1].parent_text)

    def test_reject_theme_when_original_not_in_document(self) -> None:
        data = {
            "themes": [
                {
                    "theme_title": "编造主题",
                    "retrieval_text": "test",
                    "original_content": "这段文字不在原文中",
                }
            ]
        }
        with self.assertRaises(ValueError):
            _parse_llm_themes(data, document_text="完全无关的原文")


class HacrSectionParserTest(unittest.TestCase):
    def test_parse_md_sections_by_heading(self) -> None:
        content = b"""# \xe4\xba\xa7\xe5\x93\x81\xe5\xba\x93

## [\xe7\xa1\xac\xe4\xbb\xb6] \xe4\xbc\x98\xe5\x8d\x9a\xe8\xae\xaf i6310
- \xe5\x93\x81\xe7\x89\x8c: \xe4\xbc\x98\xe5\x8d\x9a\xe8\xae\xaf
- \xe4\xbb\xb7\xe6\xa0\xbc: 3800

## [\xe8\xbd\xaf\xe4\xbb\xb6] XX ERP
- \xe9\x83\xa8\xe7\xbd\xb2: SaaS
"""
        sections = parse_md_sections(content)
        self.assertGreaterEqual(len(sections), 2)


class HacrRulesChunkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_key = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = ""

    def tearDown(self) -> None:
        if self._old_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = self._old_key

    def test_fallback_themes_from_sections(self) -> None:
        content = b"""## \xe4\xba\xa7\xe5\x93\x81A\n- \xe4\xbb\xb7\xe6\xa0\xbc: 100\n\n## \xe4\xba\xa7\xe5\x93\x81B\n- \xe4\xbb\xb7\xe6\xa0\xbc: 200\n"""
        result = process_document(content, file_name="products.md")
        self.assertEqual(result.parent_count, 2)
        self.assertEqual(len(result.chunks), 2)
        self.assertFalse(result.used_llm)
        self.assertIn("100", result.chunks[0].parent_text)
        self.assertIn("200", result.chunks[1].parent_text)
        self.assertNotEqual(result.chunks[0].parent_text, result.chunks[1].parent_text)


class HacrRetrievalTest(unittest.TestCase):
    def test_hit_uses_parent_text_for_hacr(self) -> None:
        hit = {
            "id": "p1",
            "score": 0.9,
            "payload": {
                "page_content": "【products.md】\n小块检索文本",
                "metadata": {
                    "source_type": "document",
                    "chunking_version": CHUNKING_VERSION_LLM_HACR,
                    "parent_text": "【返现规则】完整章节说明",
                    "child_snippet": "自己买卡有返现吗？",
                    "section_title": "返现规则",
                    "doc_id": "doc-1",
                    "parent_index": 0,
                    "file_name": "products.md",
                    "chunk_index": 0,
                },
            },
        }
        doc = _qdrant_hit_to_document(hit, knowledge_id="测试")
        self.assertEqual(doc["content"], "【返现规则】完整章节说明")

    def test_dedupe_same_parent(self) -> None:
        docs = [
            {
                "score": 0.9,
                "chunkingVersion": CHUNKING_VERSION_LLM_HACR,
                "docId": "doc-1",
                "parentIndex": 0,
                "sectionTitle": "A",
                "content": "parent A",
            },
            {
                "score": 0.85,
                "chunkingVersion": CHUNKING_VERSION_LLM_HACR,
                "docId": "doc-1",
                "parentIndex": 0,
                "sectionTitle": "A",
                "content": "parent A duplicate",
            },
            {
                "score": 0.7,
                "chunkingVersion": CHUNKING_VERSION_LLM_HACR,
                "docId": "doc-1",
                "parentIndex": 1,
                "sectionTitle": "B",
                "content": "parent B",
            },
        ]
        deduped = _dedupe_hacr_document_hits(docs)
        self.assertEqual(len(deduped), 2)


if __name__ == "__main__":
    unittest.main()
