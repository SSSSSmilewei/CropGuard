# -*- coding: utf-8 -*-
"""评分快照（拍照即存）的纯逻辑测试：落盘、校验、目录穿越防护。

现场流程：标本摆好 → 实时画面里拍一张 → 识别 → 把带框结果图存下来供回看。
所以这条链路必须"拍坏了不崩、名字写坏了也读不出来"，而不是靠调用方小心。
"""
import base64
import os
import shutil

from _registry import test_case

from app import eval_snapshot

# 1x1 透明 PNG（最小的合法图片）
_PNG_1PX = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
_DATA_URL = 'data:image/png;base64,' + _PNG_1PX


def _tmpdir():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'output', '_test_eval_snapshot')
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    return root


@test_case
def test_save_writes_real_image_and_returns_url_parts():
    out = _tmpdir()
    try:
        got = eval_snapshot.save(_DATA_URL, out)
        assert got['name'].startswith('eval_') and got['name'].endswith('.png'), got
        assert os.path.isfile(got['path']), got
        with open(got['path'], 'rb') as f:
            assert f.read() == base64.b64decode(_PNG_1PX)
        # 同一秒内连拍两张不能互相覆盖
        a = eval_snapshot.save(_DATA_URL, out)
        b = eval_snapshot.save(_DATA_URL, out)
        assert a['name'] != b['name'], (a, b)
    finally:
        shutil.rmtree(out, ignore_errors=True)


@test_case
def test_save_rejects_non_image_payloads():
    out = _tmpdir()
    try:
        for bad in ('', None, 'hello', 'data:text/plain;base64,aGk=',
                    'data:image/jpeg;base64,@@@不是base64@@@'):
            try:
                eval_snapshot.save(bad, out)
            except ValueError:
                continue
            raise AssertionError(f'这些输入必须被拒：{bad!r}')
    finally:
        shutil.rmtree(out, ignore_errors=True)


@test_case
def test_save_rejects_oversize():
    out = _tmpdir()
    old = eval_snapshot.MAX_BYTES
    try:
        eval_snapshot.MAX_BYTES = 4            # 临时把上限压到 4 字节
        big = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        try:
            eval_snapshot.save(big, out)
        except ValueError as exc:
            assert '太大' in str(exc), exc
        else:
            raise AssertionError('超过上限的图片必须被拒')
    finally:
        eval_snapshot.MAX_BYTES = old
        shutil.rmtree(out, ignore_errors=True)


@test_case
def test_path_of_stops_traversal_and_non_images():
    out = _tmpdir()
    try:
        got = eval_snapshot.save(_DATA_URL, out)
        assert eval_snapshot.path_of(got['name'], out) == got['path']
        for bad in ('../secret.jpg', 'sub/dir.jpg', r'..\secret.jpg', 'x.txt', '', None):
            try:
                eval_snapshot.path_of(bad, out)
            except ValueError:
                continue
            raise AssertionError(f'非法文件名必须被拒：{bad!r}')
        try:
            eval_snapshot.path_of('nope.jpg', out)
        except ValueError as exc:
            assert '不存在' in str(exc), exc
        else:
            raise AssertionError('不存在的快照要报错')
    finally:
        shutil.rmtree(out, ignore_errors=True)
