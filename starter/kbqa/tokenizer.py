"""分词。中文字符二元组 + 英文单词 + 数字，全半角大小写归一。"""

from __future__ import annotations

import re
import unicodedata

#: 分词规则变了，索引缓存必须失效。
TOKENIZER_VERSION = "tokenizer-3"

#: 中文里几乎不携带信息的字。只用在“查询覆盖率”上，索引照常保留全部词。
STOP_CHARS = frozenset("的了吗呢是在有和与及或就都也还把被给对从向于个些这那哪什么怎样如何多少几请帮我你他它可以能要想会一下少吧啊呀们么样过得着为所")
STOP_WORDS = frozenset("the a an of to in is are and or for on at it this that how what".split())

#: 英文单词 / 数字（含全角转半角后的）。
_WORD = re.compile(r"[a-z0-9]+")
#: 连续中文字符串。
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def normalise(text: str) -> str:
    """全角转半角、统一大小写，比较与分词都走这一层。"""
    return unicodedata.normalize("NFKC", text or "").lower()


def tokenize(text: str) -> list[str]:
    """把一段文本切成可检索的词元。

    - 英文单词、数字：整体作为一个词元（``salmon``、``618``）。
    - 连续中文：切成相邻两字组成的二元组（``三文鱼`` → ``三文``、``文鱼``），
      这样中文问句和中文文档之间才有交集；单个孤立的汉字保留原样。
    - 全角转半角、统一小写，``全角１`` 与 ``半角1`` 是同一个词元。
    """
    text = normalise(text)
    tokens = _WORD.findall(text)
    for run in _CJK_RUN.findall(text):
        if len(run) >= 2:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        else:
            tokens.append(run)
    return tokens


def content_tokens(text: str) -> list[str]:
    """去掉虚词之后的查询词，用来算“这个问题被文档覆盖了多少”。"""
    kept = []
    for token in tokenize(text):
        if token in STOP_WORDS:
            continue
        if all(char in STOP_CHARS for char in token):
            continue
        kept.append(token)
    return kept
