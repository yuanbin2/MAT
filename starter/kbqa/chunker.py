"""把文档切成检索用的小块：覆盖全文、保留标题/段落上下文、表格按行成块。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .loader import Document

#: 切块参数变了，索引缓存必须失效，所以写进缓存键里。
CHUNKER_VERSION = "chunker-3"

CHUNK_SIZE = 300

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    source_text: str
    heading: str = ""
    kind: str = "text"
    table_header: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_text": self.source_text,
            "heading": self.heading,
            "kind": self.kind,
            "table_header": self.table_header,
        }


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def chunk_document(document: Document) -> list[Chunk]:
    """按标题、段落、表格切块，任何一段正文都不会在切块时丢失。

    - 表格：整张表（表头 + 分隔行 + 数据行）作为一块，``kind="table"``，
      供上层按“表头 + 对应行”继续拆成可引用的最小单位。
    - 普通段落：按 ``CHUNK_SIZE`` 覆盖全文切块，末尾不足一块也保留。
    - 每个块都带上当前章节标题，作为检索时的段落上下文。
    """
    text = document.text
    lines = text.splitlines()
    chunks: list[Chunk] = []
    counter = 0
    heading = document.title
    para: list[str] = []

    def emit_text(piece: str, final: bool) -> None:
        nonlocal counter
        if not piece.strip():
            return
        counter += 1
        chunks.append(
            Chunk(
                doc_id=document.doc_id,
                chunk_id="%s#%d" % (document.doc_id, counter),
                text=piece,
                source_text=piece,
                heading=heading,
            )
        )

    def flush_para() -> None:
        nonlocal para
        if not para:
            return
        block = "\n".join(para).strip()
        para = []
        if not block:
            return
        # 覆盖全文：从 0 开始、步长 CHUNK_SIZE，最后一块不足也保留。
        for start in range(0, len(block), CHUNK_SIZE):
            emit_text(block[start : start + CHUNK_SIZE], final=True)

    def emit_table(header: str, sep: str, rows: list[str]) -> None:
        nonlocal counter
        counter += 1
        source = "\n".join([header, sep] + rows)
        chunks.append(
            Chunk(
                doc_id=document.doc_id,
                chunk_id="%s#%d" % (document.doc_id, counter),
                text=source,
                source_text=source,
                heading=heading,
                kind="table",
                table_header=_cells(header),
            )
        )

    index = 0
    while index < len(lines):
        line = lines[index]
        heading_match = _HEADING.match(line)
        if heading_match:
            flush_para()
            heading = "%s > %s" % (document.title, heading_match.group(2).strip())
            index += 1
            continue
        # 表头 + 分隔行开头的一张表
        if _TABLE_ROW.match(line) and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
            flush_para()
            header = line
            sep = lines[index + 1]
            rows: list[str] = []
            cursor = index + 2
            while cursor < len(lines) and _TABLE_ROW.match(lines[cursor]):
                rows.append(lines[cursor])
                cursor += 1
            emit_table(header, sep, rows)
            index = cursor
            continue
        para.append(line)
        index += 1

    flush_para()

    if not chunks:
        counter += 1
        piece = text.strip() or document.title
        chunks.append(
            Chunk(
                doc_id=document.doc_id,
                chunk_id="%s#%d" % (document.doc_id, counter),
                text=piece,
                source_text=piece,
                heading=document.title,
            )
        )
    return chunks


def chunk_documents(documents: list[Document]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document))
    return chunks
