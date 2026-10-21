# -*- coding: utf-8 -*-
"""RAG 检索层测试：召回准确性 + 库外问题不应被"硬凑"。

这些断言就是"防幻觉"的第一道可验证证据：
* 库内问题（蚜虫/玉米螟/…）必须召回对应害虫的片段；
* 库外问题（天气、股票…）最高分必须低于拒答阈值；
* 俗称（腻虫、钻心虫）要能映射到正式名。

运行：`python tests/run_tests.py retriever`（或装了 pytest 就 `pytest tests`）。
"""
from _registry import fixture, test_case

from llm.retriever import Retriever

R = Retriever()


@test_case
def test_chunks_and_stats_shape():
    st = R.stats()
    assert st['chunks'] > 100, st
    assert st['pests'] == 27, st
    assert st['vectorizer'] in ('tfidf', 'keyword'), st


@test_case('蚜虫怎么防治', 'aphids')
@test_case('腻虫怎么治', 'aphids')                 # 俗称
@test_case('玉米钻心虫打什么药', 'corn_borer')      # 俗称
@test_case('水稻卷叶螟的危害', 'rice_leaf_roller')
@test_case('蝗虫怎么防', 'Locustoidea')
@test_case('蛴螬咬根怎么办', 'grub')
def test_in_domain_recall(question, expect_pest):
    res = R.search(question)
    assert res, f'库内问题必须召回到片段: {question}'
    assert res[0]['score'] >= 0.18, f'库内问题分数应达标: {question} score={res[0]["score"]}'
    assert any(c['pest'] == expect_pest for c in res), \
        f'{question} 应召回 {expect_pest}，实际 {[c["id"] for c in res]}'


@test_case('今天天气怎么样')
@test_case('股票会涨吗')
@test_case('帮我写一首诗')
@test_case('怎么申请农业补贴')
@test_case('你好')
def test_out_of_domain_below_threshold(question):
    res = R.search(question)
    top = res[0]['score'] if res else 0.0
    assert top < 0.18, f'库外问题不该被硬凑: {question} top={top}'


@test_case
def test_alias_detection():
    assert 'aphids' in R.detect_pests('腻虫太多了')
    assert 'corn_borer' in R.detect_pests('钻心虫')
    assert R.detect_pests('今天天气') == []


@test_case
def test_context_filter_keeps_pest_only():
    """带检测上下文提问：答案范围只能落在"检测到的害虫 + 通用片段"。"""
    res = R.search('它需要打什么药', context_pests=['aphids'])
    assert res
    assert all(c['pest'] in ('aphids', '') for c in res), [c['id'] for c in res]


@test_case
def test_rewrite_expands_alias():
    rewritten, hits = R.rewrite('腻虫怎么治')
    assert 'aphids' in hits
    assert '蚜虫' in rewritten or '腻虫' in rewritten


@test_case
def test_intent_boost_prefers_control_for_treatment_question():
    """问"怎么治"时，防治片段应排在寄主片段前面。"""
    res = R.search('蚜虫怎么防治')
    assert res[0]['type'] in ('control', 'monitor'), [c['id'] for c in res]


# ==================== 拒答闸门（gate_score）====================
from llm.retriever import gate_score  # noqa: E402

_CTX = ['aphids']


@test_case('今天股票怎么样')
@test_case('你好')
@test_case('推荐一部电影')
@test_case('怎么申请农业补贴')
def test_gate_rejects_out_of_domain_even_with_context(question):
    """带检测上下文时库外问题也必须过不了闸（旧实现用加权分，上下文一加就过）。"""
    res = R.search(question, context_pests=_CTX)
    assert gate_score(res) < 0.18, f'{question} gate={gate_score(res)}'


@test_case('这个虫怎么防治')
@test_case('现在检测到的虫怎么处理')
@test_case('检测到的害虫有什么危害')
def test_gate_allows_deictic_questions_about_detection(question):
    """指代当前检测结果的提问是正常用法，不能被误拒。"""
    res = R.search(question, context_pests=_CTX)
    assert gate_score(res) >= 0.18, f'{question} gate={gate_score(res)}'


@test_case('蚜虫怎么防治')
@test_case('粘虫怎么防治')
def test_gate_allows_short_named_questions(question):
    """原始 TF-IDF 分偏低的短问题，点名了害虫就该过闸。"""
    res = R.search(question)
    assert gate_score(res) >= 0.18, f'{question} gate={gate_score(res)}'
