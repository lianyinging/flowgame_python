"""解析 Q&A 格式文本（与前端上传模板一致）。"""
from __future__ import annotations

import re
from typing import List, Tuple


def parse_qa_pairs(text: str) -> List[Tuple[str, str]]:
    """解析 ``Q: ... / A: ...`` 块，返回 (question, answer) 列表。"""
    if not text or not str(text).strip():
        return []

    pairs: List[Tuple[str, str]] = []
    current_q: str | None = None

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        q_match = re.match(r"^Q[:：]\s*(.*)$", line, re.IGNORECASE)
        if q_match:
            current_q = (q_match.group(1) or "").strip()
            continue

        a_match = re.match(r"^A[:：]\s*(.*)$", line, re.IGNORECASE)
        if a_match and current_q:
            answer = (a_match.group(1) or "").strip()
            if current_q and answer:
                pairs.append((current_q, answer))
            current_q = None
            continue

        if current_q:
            current_q = f"{current_q}\n{line}"

    return pairs


def build_qa_payload(question: str, answer: str) -> dict:
    return {
        "page_content": f"问题：{question}\n回答：{answer}",
        "metadata": {
            "source_type": "qa",
            "question": question,
            "answer": answer,
        },
    }


def build_qa_embed_text(question: str, answer: str) -> str:
    return f"{question}\n{answer}"
