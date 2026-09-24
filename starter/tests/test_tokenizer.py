"""分词层的最小测试：中文二元组 + 英文单词 + 数字 + 全半角归一。"""

from __future__ import annotations

from kbqa.tokenizer import content_tokens, normalise, tokenize


def test_chinese_bigram():
    # “三文鱼”切成“三文”“文鱼”，中文问句才和文档有交集。
    assert tokenize("三文鱼") == ["三文", "文鱼"]


def test_chinese_sentence_bigrams():
    tokens = tokenize("外卖订单多久内可以退款")
    assert "退款" in tokens
    assert "外卖" in tokens


def test_english_word_kept_whole():
    assert "salmon" in tokenize("Salmon Poke 供应商邮件")


def test_number_kept():
    assert "618" in tokenize("618 活动")


def test_fullwidth_halfwidth_normalized():
    # 全角字母数字转半角后再分词。
    assert tokenize("ＰＯＫＥ") == tokenize("poke")


def test_mixed_boundary_no_cross_gram():
    # “牛肉poke”里“肉p”这种跨界二元组不该出现。
    tokens = tokenize("牛肉poke")
    assert "牛肉" in tokens
    assert "poke" in tokens
    assert "肉p" not in tokens


def test_content_tokens_drop_stopwords():
    tokens = content_tokens("牛肉poke 是多少钱")
    assert "牛肉" in tokens
    assert "poke" in tokens


def test_normalise_case_and_width():
    assert normalise("ＡＢＣabc") == "abcabc"
