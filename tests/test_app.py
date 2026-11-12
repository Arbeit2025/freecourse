# -*- coding: utf-8 -*-
"""freecourse のテスト。

外部APIへの実アクセスは行わない。各ソースのパース処理はフィクスチャJSONで、
統合・重複除去・障害分離はフェイクのフェッチャで検証する。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


# ---------------------------------------------------------------------------
# 内蔵カタログの整合性
# ---------------------------------------------------------------------------
def test_catalog_integrity():
    courses = app_module.COURSES
    assert len(courses) == 48
    ids = [c["id"] for c in courses]
    assert len(set(ids)) == 48
    for c in courses:
        for key in ("title", "provider", "url", "level", "hours",
                    "certificate", "category"):
            assert c[key], f"id={c['id']} の {key} が空"
        assert c["url"].startswith("https://"), c["url"]
        assert c["level"] in app_module.LEVELS
        assert c["certificate"] in app_module.CERT_TYPES
        assert c["category"] in app_module.CATEGORIES
    counts = {}
    for c in courses:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    assert counts == {cat: 6 for cat in app_module.CATEGORIES}


def test_top_page(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "freecourse" in body
    assert "JavaScriptアルゴリズムとデータ構造認定講座" in body


def test_filter_category(client):
    resp = client.get("/", query_string={"category": "語学"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "英語コース（日本語話者向け）" in body
    assert "JavaScriptアルゴリズムとデータ構造認定講座" not in body


def test_filter_keyword(client):
    resp = client.get("/", query_string={"q": "JavaScript"})
    body = resp.get_data(as_text=True)
    assert "JavaScriptアルゴリズムとデータ構造認定講座" in body
    assert "線形代数" not in body


def test_filter_level(client):
    resp = client.get("/", query_string={"level": "中級"})
    body = resp.get_data(as_text=True)
    assert "線形代数（18.06 Linear Algebra）" in body
    assert "HTML入門" not in body


def test_filter_courses_function():
    assert all(c["category"] == "語学"
               for c in app_module.filter_courses("", "語学"))
    assert app_module.filter_courses("存在しないキーワード") == []


# ---------------------------------------------------------------------------
# 修了証（内蔵講座）
# ---------------------------------------------------------------------------
def test_certificate_builtin(client):
    course = app_module.COURSES_BY_ID[1]
    resp = client.get("/certificate/1", query_string={"name": "山田太郎"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "山田太郎" in body
    assert course["title"] in body
    assert "学習記録証" in body
    assert "公式修了証ではありません" in body


def test_certificate_builtin_name_form(client):
    resp = client.get("/certificate/1")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'action="/certificate/1"' in body


def test_certificate_builtin_unknown_id(client):
    assert client.get("/certificate/9999").status_code == 404


# ---------------------------------------------------------------------------
# 各ソースのパース処理（フィクスチャJSON）
# ---------------------------------------------------------------------------
COURSERA_FIXTURE = {
    "elements": [
        {"name": "Python for Everybody", "slug": "python",
         "partnerIds": ["10"]},
        {"name": "No Partner Course", "slug": "no-partner",
         "partnerIds": []},
        {"name": "", "slug": "broken", "partnerIds": []},
    ],
    "linked": {"partners.v1": [{"id": "10", "name": "University of Michigan"}]},
    "paging": {"total": 3},
}


def test_parse_coursera():
    results = app_module.parse_coursera(COURSERA_FIXTURE)
    assert len(results) == 2  # タイトル空の要素は除外
    first = results[0]
    assert first["title"] == "Python for Everybody"
    assert first["url"] == "https://www.coursera.org/learn/python"
    assert first["provider"] == "University of Michigan"
    assert first["source"] == "Coursera"
    # 料金はAPIから判定できないので「無料」とは断定しない
    assert first["free_label"] == ""
    assert results[1]["provider"] == "Coursera"  # パートナー不明時の既定値


MSLEARN_FIXTURE = {
    "learningPaths": [
        {
            "title": "Get started with Python",
            "url": "https://learn.microsoft.com/en-us/training/paths/python-first-steps/?WT.mc_id=api_CatalogApi",
            "levels": ["beginner"],
            "duration_in_minutes": 74,
            "summary": "Learn the Python language",
        }
    ],
    "modules": [
        {
            "title": "Introduction to Python",
            "url": "https://learn.microsoft.com/en-us/training/modules/intro-to-python/",
            "levels": ["beginner"],
            "duration_in_minutes": 30,
            "summary": "Write your first Python code",
        },
        {
            "title": "Azure Fundamentals",
            "url": "https://learn.microsoft.com/en-us/training/modules/azure-fundamentals/",
            "levels": ["beginner"],
            "duration_in_minutes": 60,
            "summary": "Cloud concepts only",
        },
    ],
}


def test_parse_mslearn():
    results = app_module.parse_mslearn(MSLEARN_FIXTURE, "python")
    titles = [r["title"] for r in results]
    assert "Get started with Python" in titles
    assert "Introduction to Python" in titles
    assert "Azure Fundamentals" not in titles  # キーワード不一致は除外
    first = results[0]
    assert "WT.mc_id" not in first["url"]  # トラッキング参数を除去
    assert first["level"] == "入門"
    assert first["free_label"] == "無料"  # Microsoft Learn は全編無料
    assert first["hours"] == "約1時間14分"


STEPIK_FIXTURE = {
    "courses": [
        {"id": 1, "title": "Free Python Course", "slug": "free-python-1",
         "is_paid": False},
        {"id": 2, "title": "Paid Python Course", "slug": "paid-python-2",
         "is_paid": True},
    ]
}


def test_parse_stepik_free_only():
    results = app_module.parse_stepik(STEPIK_FIXTURE)
    assert len(results) == 1  # 有料講座は取り込まない
    assert results[0]["title"] == "Free Python Course"
    assert results[0]["url"] == "https://stepik.org/course/free-python-1"
    assert results[0]["free_label"] == "無料"


def test_normalize_and_clean_url():
    assert (app_module.normalize_url("HTTPS://Example.COM/py/?utm_source=x")
            == "https://example.com/py")
    assert "WT.mc_id" not in app_module._clean_url(
        "https://learn.microsoft.com/x/?WT.mc_id=api")


# ---------------------------------------------------------------------------
# 統合・重複除去・障害分離
# ---------------------------------------------------------------------------
def _fake_ok(q):
    return [app_module._unified("Python入門", "Example", "Fake",
                                "https://example.com/py/")]


def _fake_dup(q):
    # 末尾スラッシュ無し＝正規化すると _fake_ok と同一URL
    return [app_module._unified("Python入門・別ソース版", "Other", "Fake2",
                                "https://example.com/py")]


def _fake_boom(q):
    raise RuntimeError("source down")


def test_collect_dedup_and_failure_isolation():
    results, statuses = app_module.collect_results(
        "python",
        fetchers=[("Fake", _fake_ok), ("Fake2", _fake_dup),
                  ("Boom", _fake_boom)],
    )
    example_urls = [r["url"] for r in results
                    if r["url"].startswith("https://example.com")]
    assert len(example_urls) == 1  # URL正規化で重複除去
    ok_map = {s["source"]: s["ok"] for s in statuses}
    assert ok_map["内蔵カタログ"] is True
    assert ok_map["Fake"] is True
    assert ok_map["Fake2"] is True
    assert ok_map["Boom"] is False  # 落ちたソースだけ失敗扱い


def test_collect_keys():
    results, _ = app_module.collect_results(
        "python", fetchers=[("Fake", _fake_ok)])
    keys = {r["key"] for r in results}
    assert any(k.startswith("u:https://example.com") for k in keys)


def test_builtin_keys_present():
    results, statuses = app_module.collect_results("HTML", fetchers=[])
    assert statuses[0]["source"] == "内蔵カタログ"
    assert any(r["key"].startswith("b:") for r in results)


# ---------------------------------------------------------------------------
# 横断検索ルート（外部はモックに差し替え）
# ---------------------------------------------------------------------------
def test_search_no_query_shows_builtin(client):
    resp = client.get("/search")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "HTML入門" in body  # 内蔵カタログ全件が並ぶ


def test_search_merges_external(client, monkeypatch):
    monkeypatch.setattr(app_module, "EXTERNAL_SOURCES",
                        [("Fake", _fake_ok)])
    resp = client.get("/search", query_string={"q": "python"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Python入門" in body
    assert "Fake" in body
    assert "/certificate/custom" in body  # 外部講座向け修了証導線


def test_search_fallback_when_all_external_down(client, monkeypatch):
    monkeypatch.setattr(app_module, "EXTERNAL_SOURCES",
                        [("Boom", _fake_boom)])
    resp = client.get("/search", query_string={"q": "HTML"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "HTML入門" in body  # 内蔵カタログの結果は返る
    assert "取得失敗" in body
    assert "内蔵カタログの結果のみ表示しています" in body


# ---------------------------------------------------------------------------
# 修了証（検索結果の講座）
# ---------------------------------------------------------------------------
def test_certificate_custom(client):
    resp = client.get(
        "/certificate/custom",
        query_string={"title": "Python入門", "provider": "Example",
                      "name": "佐藤花子"},
    )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "佐藤花子" in body
    assert "Python入門" in body
    assert "学習記録証" in body
    assert "公式修了証ではありません" in body


def test_certificate_custom_name_form_keeps_params(client):
    resp = client.get(
        "/certificate/custom",
        query_string={"title": "Python入門", "provider": "Example"},
    )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "title=Python" in body  # 氏名送信後も講座が引き継がれる


def test_certificate_custom_requires_title(client):
    resp = client.get("/certificate/custom",
                      query_string={"name": "佐藤花子"})
    assert resp.status_code == 404


def test_healthz(client):
    assert client.get("/healthz").status_code == 200


def test_style_block_not_escaped(client):
    """テーマ切替の回帰テスト: <style> 内の属性セレクタの引用符が
    HTMLエスケープ（&#34;）されてダークテーマ規則が無効化されないこと。"""
    for path in ["/", "/certificate/1?name=%E5%B1%B1%E7%94%B0%E5%A4%AA%E9%83%8E"]:
        rv = client.get(path)
        html = rv.get_data(as_text=True)
        style = html.split("<style>", 1)[1].split("</style>", 1)[0]
        assert 'data-theme="dark"' in style, path
        assert "&#34;" not in style, path
