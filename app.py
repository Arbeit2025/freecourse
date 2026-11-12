# -*- coding: utf-8 -*-
"""freecourse — 無料講座の横断検索アグリゲーター＋修了証メーカー

厳選した無料オンライン講座の内蔵カタログ（48件）に加え、検索時には
Coursera／Microsoft Learn／Stepik の公開カタログへサーバー側で並行に
問い合わせ、結果を統合・重複除去して返す Flask アプリ。
内蔵カタログはカテゴリ・キーワード・レベル・修了証の有無でも絞り込める。
受講状態（受講中／完了）はブラウザの localStorage に保存され（講座は
内蔵=ID、検索結果=URL＋タイトルで識別）、完了した講座については
本ツール独自の「修了証（学習記録証）」を発行できる。

注意：本ツールが発行する修了証は学習記録証であり、
各講座の提供元が発行する公式修了証ではありません。
カタログの修了証情報は収録時点の公開情報に基づく目安で、
最新の条件は各講座ページで確認してください。
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, abort, render_template_string, request

app = Flask(__name__)

CATEGORIES = [
    "IT・プログラミング",
    "ビジネス",
    "語学",
    "デザイン",
    "教養・学問",
    "資格・キャリア",
    "健康・生活",
    "創作",
]

LEVELS = ["入門", "初級", "中級"]

# 修了証の区分: 無料あり（無料で公式修了証が得られる）／有料（修了証は有料）／
# なし（公式修了証の制度なし）／要確認（情報が不確かなため断定しない）
CERT_TYPES = ["無料あり", "有料", "なし", "要確認"]

# ---------------------------------------------------------------------------
# 講座カタログ（実在の無料オンライン講座）
# certificate は収録時点の公開情報に基づく。条件は変更される場合がある。
# ---------------------------------------------------------------------------
COURSES = [
    # --- IT・プログラミング ---
    dict(id=1, category="IT・プログラミング", level="入門", hours="約300時間",
         title="レスポンシブWebデザイン認定講座", provider="freeCodeCamp",
         url="https://www.freecodecamp.org/learn/2022/responsive-web-design/",
         certificate="無料あり"),
    dict(id=2, category="IT・プログラミング", level="初級", hours="約300時間",
         title="JavaScriptアルゴリズムとデータ構造認定講座", provider="freeCodeCamp",
         url="https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures-v8/",
         certificate="無料あり"),
    dict(id=3, category="IT・プログラミング", level="入門", hours="約12週間",
         title="CS50x コンピュータサイエンス入門", provider="edX（ハーバード大学）",
         url="https://www.edx.org/learn/computer-science/harvard-university-cs50-s-introduction-to-computer-science",
         certificate="有料"),
    dict(id=4, category="IT・プログラミング", level="入門", hours="約2時間",
         title="HTML入門", provider="ドットインストール",
         url="https://dotinstall.com/lessons/basic_html_v5",
         certificate="なし"),
    dict(id=5, category="IT・プログラミング", level="入門", hours="約8時間",
         title="HTML & CSS", provider="Progate",
         url="https://prog-8.com/languages/html",
         certificate="要確認"),
    dict(id=6, category="IT・プログラミング", level="入門", hours="約1時間",
         title="Introduction to GitHub（GitHub入門）", provider="GitHub Skills",
         url="https://github.com/skills/introduction-to-github",
         certificate="なし"),
    # --- ビジネス ---
    dict(id=7, category="ビジネス", level="入門", hours="約40時間",
         title="デジタルマーケティングの基礎", provider="Google（デジタルワークショップ）",
         url="https://learndigital.withgoogle.com/digitalgarage/course/digital-marketing",
         certificate="無料あり"),
    dict(id=8, category="ビジネス", level="初級", hours="約6か月",
         title="Google プロジェクトマネジメント認定講座", provider="Coursera（Google）",
         url="https://www.coursera.org/professional-certificates/google-project-management",
         certificate="有料"),
    dict(id=9, category="ビジネス", level="入門", hours="約17時間",
         title="Successful Negotiation（交渉の必須戦略とスキル）", provider="Coursera（ミシガン大学）",
         url="https://www.coursera.org/learn/negotiation-skills",
         certificate="有料"),
    dict(id=10, category="ビジネス", level="中級", hours="約6週間",
         title="Entrepreneurship in Emerging Economies（新興国経済と起業）", provider="edX（ハーバード大学）",
         url="https://www.edx.org/learn/business-administration/harvard-university-entrepreneurship-in-emerging-economies",
         certificate="有料"),
    dict(id=11, category="ビジネス", level="初級", hours="約20時間",
         title="金融と資本市場（Finance and Capital Markets）", provider="Khan Academy",
         url="https://www.khanacademy.org/economics-finance-domain/core-finance",
         certificate="なし"),
    dict(id=12, category="ビジネス", level="初級", hours="約10時間",
         title="Diploma in Modern Project Management（プロジェクトマネジメント）", provider="Alison",
         url="https://alison.com/course/diploma-in-modern-project-management-revised",
         certificate="有料"),
    # --- 語学 ---
    dict(id=13, category="語学", level="入門", hours="1日5分〜の継続学習",
         title="英語コース（日本語話者向け）", provider="Duolingo",
         url="https://www.duolingo.com/course/en/ja",
         certificate="なし"),
    dict(id=14, category="語学", level="入門", hours="継続学習",
         title="NHKゴガクル", provider="NHK",
         url="https://gogakuru.com/",
         certificate="なし"),
    dict(id=15, category="語学", level="初級", hours="継続学習",
         title="BBC Learning English", provider="BBC",
         url="https://www.bbc.co.uk/learningenglish",
         certificate="なし"),
    dict(id=16, category="語学", level="初級", hours="約8週間",
         title="English Grammar and Style", provider="edX（クイーンズランド大学）",
         url="https://www.edx.org/learn/english/the-university-of-queensland-english-grammar-and-style",
         certificate="有料"),
    dict(id=17, category="語学", level="初級", hours="約40時間",
         title="English for Career Development", provider="Coursera（ペンシルベニア大学）",
         url="https://www.coursera.org/learn/career-development",
         certificate="有料"),
    dict(id=18, category="語学", level="中級", hours="約6週間",
         title="TOEFL iBT Test Preparation", provider="edX（ETS）",
         url="https://www.edx.org/learn/test-prep/educational-testing-service-toefl-ibt-test-preparation-the-insider-s-guide",
         certificate="有料"),
    # --- デザイン ---
    dict(id=19, category="デザイン", level="初級", hours="約6か月",
         title="Google UXデザイン認定講座", provider="Coursera（Google）",
         url="https://www.coursera.org/professional-certificates/google-ux-design",
         certificate="有料"),
    dict(id=20, category="デザイン", level="入門", hours="約6か月",
         title="Graphic Design スペシャリゼーション", provider="Coursera（カリフォルニア芸術大学）",
         url="https://www.coursera.org/specializations/graphic-design",
         certificate="有料"),
    dict(id=21, category="デザイン", level="初級", hours="約4か月",
         title="UI / UX Design スペシャリゼーション", provider="Coursera（カリフォルニア芸術大学）",
         url="https://www.coursera.org/specializations/ui-ux-design",
         certificate="有料"),
    dict(id=22, category="デザイン", level="入門", hours="約3時間",
         title="Canva Design School（デザイン講座）", provider="Canva",
         url="https://www.canva.com/designschool/",
         certificate="要確認"),
    dict(id=23, category="デザイン", level="初級", hours="約8時間",
         title="Learn CSS", provider="web.dev（Google）",
         url="https://web.dev/learn/css",
         certificate="なし"),
    dict(id=24, category="デザイン", level="入門", hours="約3時間",
         title="Tinkercad レッスン（3Dモデリング入門）", provider="Autodesk",
         url="https://www.tinkercad.com/learning",
         certificate="なし"),
    # --- 教養・学問 ---
    dict(id=25, category="教養・学問", level="入門", hours="約30時間",
         title="世界史（World History）", provider="Khan Academy",
         url="https://www.khanacademy.org/humanities/world-history",
         certificate="なし"),
    dict(id=26, category="教養・学問", level="入門", hours="約12週間",
         title="Justice（正義）", provider="edX（ハーバード大学）",
         url="https://www.edx.org/learn/law/harvard-university-justice",
         certificate="有料"),
    dict(id=27, category="教養・学問", level="入門", hours="約19時間",
         title="The Science of Well-Being", provider="Coursera（イェール大学）",
         url="https://www.coursera.org/learn/the-science-of-well-being",
         certificate="有料"),
    dict(id=28, category="教養・学問", level="入門", hours="継続学習",
         title="NHK高校講座", provider="NHK",
         url="https://www.nhk.or.jp/kokokoza/",
         certificate="なし"),
    dict(id=29, category="教養・学問", level="中級", hours="約14週間",
         title="線形代数（18.06 Linear Algebra）", provider="MIT OpenCourseWare",
         url="https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/",
         certificate="なし"),
    dict(id=30, category="教養・学問", level="入門", hours="約15時間",
         title="Learning How to Learn（学び方を学ぶ）", provider="Coursera",
         url="https://www.coursera.org/learn/learning-how-to-learn",
         certificate="有料"),
    # --- 資格・キャリア ---
    dict(id=31, category="資格・キャリア", level="初級", hours="約6か月",
         title="Google ITサポート認定講座", provider="Coursera（Google）",
         url="https://www.coursera.org/professional-certificates/google-it-support",
         certificate="有料"),
    dict(id=32, category="資格・キャリア", level="初級", hours="約6か月",
         title="Google データアナリティクス認定講座", provider="Coursera（Google）",
         url="https://www.coursera.org/professional-certificates/google-data-analytics",
         certificate="有料"),
    dict(id=33, category="資格・キャリア", level="初級", hours="約6か月",
         title="Google サイバーセキュリティ認定講座", provider="Coursera（Google）",
         url="https://www.coursera.org/professional-certificates/google-cybersecurity",
         certificate="有料"),
    dict(id=34, category="資格・キャリア", level="入門", hours="約1〜10時間（コースによる）",
         title="AWS デジタルトレーニング", provider="AWS",
         url="https://aws.amazon.com/jp/training/digital/",
         certificate="要確認"),
    dict(id=35, category="資格・キャリア", level="入門", hours="継続学習",
         title="Trailhead（Salesforce学習プラットフォーム）", provider="Salesforce",
         url="https://trailhead.salesforce.com/",
         certificate="なし"),
    dict(id=36, category="資格・キャリア", level="初級", hours="約6時間",
         title="コンテンツマーケティング認定講座", provider="HubSpot Academy",
         url="https://academy.hubspot.com/courses/content-marketing",
         certificate="無料あり"),
    # --- 健康・生活 ---
    dict(id=37, category="健康・生活", level="入門", hours="約7時間",
         title="Introduction to Food and Health", provider="Coursera（スタンフォード大学）",
         url="https://www.coursera.org/learn/food-and-health",
         certificate="有料"),
    dict(id=38, category="健康・生活", level="入門", hours="約11週間",
         title="The Science of Happiness", provider="edX（カリフォルニア大学バークレー校）",
         url="https://www.edx.org/learn/happiness/university-of-california-berkeley-the-science-of-happiness",
         certificate="有料"),
    dict(id=39, category="健康・生活", level="初級", hours="約20時間",
         title="Health and Medicine（健康と医学）", provider="Khan Academy",
         url="https://www.khanacademy.org/science/health-and-medicine",
         certificate="なし"),
    dict(id=40, category="健康・生活", level="入門", hours="約29時間",
         title="Introduction to Psychology", provider="Coursera（イェール大学）",
         url="https://www.coursera.org/learn/introduction-psychology",
         certificate="有料"),
    dict(id=41, category="健康・生活", level="入門", hours="約3〜24時間（コースによる）",
         title="Health, Sports & Psychology 無料コース", provider="OpenLearn（オープン大学）",
         url="https://www.open.edu/openlearn/health-sports-psychology",
         certificate="無料あり"),
    dict(id=42, category="健康・生活", level="入門", hours="約15時間",
         title="Understanding Anxiety, Depression and CBT", provider="FutureLearn（レディング大学）",
         url="https://www.futurelearn.com/courses/understanding-anxiety-depression-cbt",
         certificate="有料"),
    # --- 創作 ---
    dict(id=43, category="創作", level="入門", hours="継続学習",
         title="Blender 公式チュートリアル", provider="Blender",
         url="https://www.blender.org/support/tutorials/",
         certificate="なし"),
    dict(id=44, category="創作", level="入門", hours="継続学習",
         title="pixiv SENSEI（イラスト講座）", provider="pixiv",
         url="https://sensei.pixiv.net/",
         certificate="なし"),
    dict(id=45, category="創作", level="初級", hours="約6か月",
         title="Creative Writing スペシャリゼーション", provider="Coursera（ウェズリアン大学）",
         url="https://www.coursera.org/specializations/creative-writing",
         certificate="有料"),
    dict(id=46, category="創作", level="初級", hours="約15時間",
         title="Songwriting: Writing the Lyric", provider="Coursera（バークリー音楽大学）",
         url="https://www.coursera.org/learn/songwriting-lyrics",
         certificate="有料"),
    dict(id=47, category="創作", level="入門", hours="約15時間",
         title="Pixar in a Box", provider="Khan Academy",
         url="https://www.khanacademy.org/computing/pixar",
         certificate="なし"),
    dict(id=48, category="創作", level="入門", hours="継続学習",
         title="CLIP STUDIO PAINT 使い方講座（TIPS）", provider="セルシス",
         url="https://tips.clip-studio.com/",
         certificate="なし"),
]

COURSES_BY_ID = {c["id"]: c for c in COURSES}

DISCLAIMER = (
    "この修了証は、本ツール（freecourse）が発行する学習記録証であり、"
    "提供元の公式修了証ではありません。"
)


def filter_courses(q="", category="", level="", certificate=""):
    """キーワード・カテゴリ・レベル・修了証区分で講座を絞り込む。"""
    q = (q or "").strip().lower()
    result = []
    for c in COURSES:
        if q and q not in c["title"].lower() and q not in c["provider"].lower():
            continue
        if category and c["category"] != category:
            continue
        if level and c["level"] != level:
            continue
        if certificate and c["certificate"] != certificate:
            continue
        result.append(c)
    return result


# ---------------------------------------------------------------------------
# テンプレート
# ---------------------------------------------------------------------------
BASE_CSS = """
:root{
  --bg:#f6f7f9; --card:#ffffff; --text:#1c2330; --sub:#5a6474;
  --line:#d8dde6; --accent:#2563eb; --accent-text:#ffffff;
  --badge:#e8edf5; --done:#15803d; --doing:#b45309;
}
[data-theme="dark"]{
  --bg:#14181f; --card:#1e242f; --text:#e8ecf2; --sub:#9aa5b5;
  --line:#39424f; --accent:#5b93ff; --accent-text:#0d1526;
  --badge:#2a3242; --done:#4ade80; --doing:#fbbf24;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--text);
  font-family:"Hiragino Sans","Noto Sans JP",system-ui,sans-serif;
  line-height:1.6;overflow-x:hidden}
.wrap{max-width:980px;margin:0 auto;padding:16px}
header.site{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
h1{font-size:1.5rem;margin:8px 0}
h1 .logo{color:var(--accent)}
.lead{color:var(--sub);margin:4px 0 12px}
button,input,select{font:inherit;color:inherit}
.btn{background:var(--card);border:1px solid var(--line);border-radius:8px;
  padding:6px 12px;cursor:pointer}
.btn.primary{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}
.btn.small{padding:2px 10px;font-size:.9rem}
form.filters{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:end}
form.filters label{display:flex;flex-direction:column;font-size:.85rem;color:var(--sub);gap:4px}
form.filters input[type="text"],form.filters select{
  background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 8px;max-width:100%}
.summary{margin:12px 2px;color:var(--sub);font-size:.95rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(290px,100%),1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;
  display:flex;flex-direction:column;gap:8px}
.card h2{font-size:1.05rem;margin:0;line-height:1.4}
.provider{color:var(--sub);font-size:.9rem}
.badges{display:flex;gap:6px;flex-wrap:wrap}
.badge{background:var(--badge);border-radius:999px;padding:1px 10px;font-size:.8rem}
.badge.cert-free{color:var(--done);font-weight:600}
.meta{font-size:.9rem;color:var(--sub)}
.card a.open{color:var(--accent);font-weight:600;text-decoration:none}
.status-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:auto}
.status-label{font-size:.9rem;font-weight:600}
.status-label.doing{color:var(--doing)}
.status-label.done{color:var(--done)}
.cert-form{display:none;border-top:1px dashed var(--line);padding-top:10px}
.cert-form.visible{display:block}
.cert-form input[type="text"]{width:100%;background:var(--bg);border:1px solid var(--line);
  border-radius:8px;padding:6px 8px;margin:4px 0 8px}
footer.site{color:var(--sub);font-size:.85rem;margin:24px 0 8px}
/* 修了証 */
.cert-sheet{background:var(--card);border:3px double var(--accent);border-radius:8px;
  padding:36px 28px;text-align:center;margin:20px auto;max-width:760px}
.cert-sheet h2{font-size:2rem;letter-spacing:.4em;margin:0 0 8px;text-indent:.4em}
.cert-name{font-size:1.7rem;font-weight:700;margin:18px 0 4px}
.cert-course{font-size:1.25rem;font-weight:600;margin:14px 0 4px}
.cert-meta{color:var(--sub)}
.disclaimer{font-size:.85rem;color:var(--sub);border-top:1px solid var(--line);
  margin-top:24px;padding-top:12px}
@media print{
  .no-print{display:none !important}
  body{background:#ffffff}
  .cert-sheet{border-color:#333333}
}
"""

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>freecourse｜無料オンライン講座カタログ＋修了証メーカー</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
  <header class="site">
    <h1><span class="logo">freecourse</span> 無料講座カタログ</h1>
    <button type="button" class="btn" id="theme-toggle">🌙 ダーク切替</button>
  </header>
  <p class="lead">実在する無料オンライン講座を集めたカタログです。気になる講座を「受講中／完了」で管理でき、完了した講座には修了証（学習記録証）を作れます。</p>

  <form class="filters" method="get" action="/search" style="margin-bottom:12px">
    <label>あらゆる無料講座を横断検索（Coursera／Microsoft Learn／Stepik 等と連携）
      <input type="text" name="q" placeholder="例：python、excel、english、data">
    </label>
    <button type="submit" class="btn primary">横断検索する</button>
  </form>

  <form class="filters" method="get" action="/">
    <label>内蔵カタログ内を検索
      <input type="text" name="q" value="{{ q | e }}" placeholder="例：JavaScript、英語、デザイン">
    </label>
    <label>カテゴリ
      <select name="category">
        <option value="">すべて</option>
        {% for cat in categories %}
        <option value="{{ cat | e }}" {% if cat == category %}selected{% endif %}>{{ cat | e }}</option>
        {% endfor %}
      </select>
    </label>
    <label>レベル
      <select name="level">
        <option value="">すべて</option>
        {% for lv in levels %}
        <option value="{{ lv | e }}" {% if lv == level %}selected{% endif %}>{{ lv | e }}</option>
        {% endfor %}
      </select>
    </label>
    <label>修了証
      <select name="certificate">
        <option value="">すべて</option>
        {% for ct in cert_types %}
        <option value="{{ ct | e }}" {% if ct == certificate %}selected{% endif %}>{{ ct | e }}</option>
        {% endfor %}
      </select>
    </label>
    <button type="submit" class="btn primary">絞り込む</button>
    <a class="btn" href="/" style="text-decoration:none">リセット</a>
  </form>

  <p class="summary">{{ courses|length }} 件の講座
    （全 {{ total }} 件中）｜あなたの進捗：受講中 <span id="count-doing">0</span> 件・完了 <span id="count-done">0</span> 件</p>

  <div class="grid">
  {% for c in courses %}
    <article class="card" data-progress-key="b:{{ c.id }}">
      <h2>{{ c.title | e }}</h2>
      <div class="provider">提供元：{{ c.provider | e }}</div>
      <div class="badges">
        <span class="badge">{{ c.category | e }}</span>
        <span class="badge">{{ c.level | e }}</span>
        <span class="badge {% if c.certificate == '無料あり' %}cert-free{% endif %}">修了証：{{ c.certificate | e }}</span>
      </div>
      <div class="meta">目安時間：{{ c.hours | e }}</div>
      <a class="open" href="{{ c.url | e }}" target="_blank" rel="noopener">講座ページを開く →</a>
      <div class="status-row">
        <span class="status-label">未登録</span>
        <button type="button" class="btn small" onclick="setStatus('b:{{ c.id }}', 'doing')">受講中にする</button>
        <button type="button" class="btn small" onclick="setStatus('b:{{ c.id }}', 'done')">完了にする</button>
        <button type="button" class="btn small" onclick="setStatus('b:{{ c.id }}', '')">リセット</button>
      </div>
      <form class="cert-form" method="get" action="/certificate/{{ c.id }}">
        <label>修了証を作る（氏名を入力）
          <input type="text" name="name" placeholder="例：山田 太郎" required>
        </label>
        <button type="submit" class="btn primary small">修了証を表示する</button>
      </form>
    </article>
  {% else %}
    <p>条件に合う講座が見つかりませんでした。条件を変えてお試しください。</p>
  {% endfor %}
  </div>

  <footer class="site">
    <p>※ 修了証の有無は収録時点の公開情報に基づく目安です。受講料・修了証の条件は変わることがあるため、最新の情報は各講座ページでご確認ください。</p>
    <p>※ 本ツールの修了証は学習記録証であり、各提供元の公式修了証ではありません。</p>
  </footer>
</div>
<script>
(function(){
  var root = document.documentElement;
  var savedTheme = localStorage.getItem('freecourse-theme');
  if (savedTheme) { root.setAttribute('data-theme', savedTheme); }
  else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    root.setAttribute('data-theme', 'dark');
  }
  document.getElementById('theme-toggle').addEventListener('click', function(){
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('freecourse-theme', next);
  });
})();

var PROGRESS_KEY = 'freecourse-progress';
function loadProgress(){
  try { return JSON.parse(localStorage.getItem(PROGRESS_KEY)) || {}; }
  catch (e) { return {}; }
}
function saveProgress(p){ localStorage.setItem(PROGRESS_KEY, JSON.stringify(p)); }
function setStatus(key, status){
  var p = loadProgress();
  if (status) { p[key] = status; } else { delete p[key]; }
  saveProgress(p);
  applyProgress();
}
function applyProgress(){
  var p = loadProgress();
  var doing = 0, done = 0;
  document.querySelectorAll('.card[data-progress-key]').forEach(function(card){
    var id = card.getAttribute('data-progress-key');
    var st = p[id] || '';
    var label = card.querySelector('.status-label');
    var form = card.querySelector('.cert-form');
    label.className = 'status-label' + (st ? ' ' + st : '');
    label.textContent = st === 'done' ? '✅ 完了' : (st === 'doing' ? '📖 受講中' : '未登録');
    if (form) { form.classList.toggle('visible', st === 'done'); }
    if (st === 'doing') { doing++; }
    if (st === 'done') { done++; }
  });
  document.getElementById('count-doing').textContent = doing;
  document.getElementById('count-done').textContent = done;
}
applyProgress();
</script>
</body>
</html>
"""

CERT_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>修了証｜{{ course.title | e }}｜freecourse</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
  <p class="no-print"><a href="/">← 講座カタログに戻る</a></p>

  {% if not name %}
  <h1>修了証メーカー</h1>
  <p class="lead">講座「{{ course.title | e }}」（提供元：{{ course.provider | e }}）の修了証を作ります。氏名を入力してください。</p>
  <form method="get" action="{{ cert_action }}" style="max-width:420px">
    <label>氏名
      <input type="text" name="name" placeholder="例：山田 太郎" required
        style="width:100%;padding:8px;border:1px solid #999;border-radius:8px;margin:6px 0 10px">
    </label>
    <button type="submit" class="btn primary">修了証を表示する</button>
  </form>
  {% else %}
  <div class="cert-sheet">
    <h2>修了証</h2>
    <p class="cert-meta">Certificate of Completion</p>
    <p class="cert-name">{{ name | e }} 様</p>
    <p>以下の講座の学習を完了したことを記録します。</p>
    <p class="cert-course">{{ course.title | e }}</p>
    <p class="cert-meta">提供元：{{ course.provider | e }}／カテゴリ：{{ course.category | e }}／レベル：{{ course.level | e }}</p>
    <p class="cert-meta">完了日：{{ date_str | e }}</p>
    <p class="cert-meta">発行：freecourse（無料講座カタログ）</p>
    <p class="disclaimer">{{ disclaimer | e }}</p>
  </div>
  <p class="no-print" style="text-align:center">
    <button type="button" class="btn primary" onclick="window.print()">印刷する</button>
  </p>
  {% endif %}
</div>
<script>
(function(){
  var savedTheme = localStorage.getItem('freecourse-theme');
  if (savedTheme) { document.documentElement.setAttribute('data-theme', savedTheme); }
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# ルート
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    q = request.args.get("q", "")
    category = request.args.get("category", "")
    level = request.args.get("level", "")
    certificate = request.args.get("certificate", "")
    courses = filter_courses(q, category, level, certificate)
    return render_template_string(
        INDEX_TEMPLATE,
        css=BASE_CSS,
        courses=courses,
        total=len(COURSES),
        q=q,
        category=category,
        level=level,
        certificate=certificate,
        categories=CATEGORIES,
        levels=LEVELS,
        cert_types=CERT_TYPES,
    )


@app.route("/certificate/<int:course_id>")
def certificate(course_id):
    course = COURSES_BY_ID.get(course_id)
    if course is None:
        abort(404)
    name = (request.args.get("name") or "").strip()
    today = datetime.now(ZoneInfo("Asia/Tokyo"))
    date_str = f"{today.year}年{today.month}月{today.day}日"
    return render_template_string(
        CERT_TEMPLATE,
        css=BASE_CSS,
        course=course,
        name=name,
        date_str=date_str,
        disclaimer=DISCLAIMER,
        cert_action=f"/certificate/{course_id}",
    )


@app.route("/healthz")
def healthz():
    return "ok", 200


# ---------------------------------------------------------------------------
# 横断検索アグリゲーター
#
# 採用ソース（いずれもAPIキー不要・この環境から実応答を確認済み）：
#   - 内蔵カタログ（本ファイルの COURSES。外部全滅時のフォールバック）
#   - Coursera 公開カタログAPI（検索ファインダは廃止されているため、
#     カタログ先頭スライスを取得しキーワード一致をローカルで抽出する）
#   - Microsoft Learn Catalog API（全編無料。terms で絞り込み）
#   - Stepik 公開API（is_paid=False の無料講座のみ採用）
# 不採用：MIT OpenCourseWare（公開APIが無く検索ページはJS描画のみ）、
#   OpenLearn（この環境から接続失敗→403）、Class Central（403でbot遮断）、
#   edX（カタログAPIが404＝キーなし取得不可）、SWAYAM（公開API未確認）
# ---------------------------------------------------------------------------
SOURCE_TIMEOUT = 8        # 通常ソースのHTTPタイムアウト（秒）
MSLEARN_TIMEOUT = 30      # Microsoft Learn は応答が大きいため長め
CACHE_TTL = 300           # 外部取得結果のキャッシュ（秒）
MSLEARN_CACHE_TTL = 3600  # Microsoft Learn のキャッシュ（秒）
LEVEL_MAP_EN = {"beginner": "入門", "intermediate": "初級", "advanced": "中級"}

_cache = {}


def _fetch_json(url, timeout):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "freecourse-aggregator/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cached(key, ttl, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = fn()
    _cache[key] = (now + ttl, value)
    return value


def _tokens(q):
    return [t for t in re.split(r"\s+", (q or "").strip().lower()) if t]


def _matches(text, tokens):
    text = (text or "").lower()
    return bool(tokens) and all(t in text for t in tokens)


def normalize_url(u):
    """重複判定用にURLを正規化する（スキーム/ホスト小文字化、クエリ除去、末尾/除去）。"""
    parts = urllib.parse.urlsplit((u or "").strip())
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, "", "")
    )


def _clean_url(u):
    """表示用URLからトラッキング用クエリパラメータを取り除く。"""
    parts = urllib.parse.urlsplit(u or "")
    qs = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query)
        if k != "WT.mc_id" and not k.startswith("utm_")
    ]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(qs), "")
    )


def _fmt_minutes(minutes):
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return ""
    h, mm = divmod(m, 60)
    if h and mm:
        return f"約{h}時間{mm}分"
    if h:
        return f"約{h}時間"
    return f"約{mm}分"


def _unified(title, provider, source, url, level="", hours="",
             free_label="", cert_label="", builtin_id=None):
    return {
        "key": "",
        "title": title,
        "provider": provider,
        "source": source,
        "url": url,
        "level": level,
        "hours": hours,
        "free_label": free_label,
        "cert_label": cert_label,
        "builtin_id": builtin_id,
    }


def builtin_results(q):
    """内蔵カタログを統一形式で返す。"""
    out = []
    for c in filter_courses(q):
        r = _unified(
            c["title"], c["provider"], "内蔵カタログ", c["url"],
            level=c["level"], hours=c["hours"], cert_label=c["certificate"],
            builtin_id=c["id"],
        )
        r["key"] = f"b:{c['id']}"
        out.append(r)
    return out


# --- Coursera ---------------------------------------------------------------
def parse_coursera(data):
    partners = {}
    for p in (data.get("linked") or {}).get("partners.v1", []):
        partners[str(p.get("id"))] = p.get("name") or ""
    out = []
    for e in data.get("elements", []):
        slug, name = e.get("slug"), e.get("name")
        if not slug or not name:
            continue
        provider = ""
        for pid in e.get("partnerIds") or []:
            if partners.get(str(pid)):
                provider = partners[str(pid)]
                break
        out.append(
            _unified(name, provider or "Coursera", "Coursera",
                     f"https://www.coursera.org/learn/{slug}")
        )
    return out


def fetch_coursera(q):
    """公開カタログの先頭スライス（300件）を取得し、タイトル/スラッグで照合する。

    Coursera の公開APIは検索ファインダが廃止されているため、網羅性は限定的。
    料金はAPIから判定できないので「無料」とは表示しない。
    """
    tokens = _tokens(q)
    if not tokens:
        return []

    def _load():
        items = []
        for start in (0, 100, 200):
            url = (
                "https://api.coursera.org/api/courses.v1?start=%d&limit=100"
                "&fields=name,slug,partnerIds&includes=partnerIds" % start
            )
            items.extend(parse_coursera(_fetch_json(url, SOURCE_TIMEOUT)))
        return items

    catalog = _cached("coursera:slice", CACHE_TTL, _load)
    return [
        r for r in catalog
        if _matches(r["title"] + " " + r["url"].replace("-", " "), tokens)
    ][:20]


# --- Microsoft Learn ----------------------------------------------------------
def parse_mslearn(data, q):
    tokens = _tokens(q)
    out = []
    for coll in ("learningPaths", "modules"):
        for e in data.get(coll, []) or []:
            title = e.get("title") or ""
            if not _matches(title + " " + (e.get("summary") or ""), tokens):
                continue
            url = _clean_url(e.get("url") or "")
            if not url:
                continue
            level = ""
            for lv in e.get("levels") or []:
                if lv in LEVEL_MAP_EN:
                    level = LEVEL_MAP_EN[lv]
                    break
            out.append(
                _unified(title, "Microsoft Learn", "Microsoft Learn", url,
                         level=level,
                         hours=_fmt_minutes(e.get("duration_in_minutes")),
                         free_label="無料")
            )
    return out[:15]


def fetch_mslearn(q):
    if not _tokens(q):
        return []

    def _load():
        url = ("https://learn.microsoft.com/api/catalog/?terms="
               + urllib.parse.quote(q))
        return _fetch_json(url, MSLEARN_TIMEOUT)

    data = _cached("mslearn:" + q.lower(), MSLEARN_CACHE_TTL, _load)
    return parse_mslearn(data, q)


# --- Stepik -------------------------------------------------------------------
def parse_stepik(data):
    """is_paid が False の講座だけを無料として取り込む。"""
    out = []
    for e in data.get("courses", []):
        if e.get("is_paid"):
            continue
        title = e.get("title") or ""
        slug = e.get("slug") or (str(e["id"]) if e.get("id") else "")
        if not title or not slug:
            continue
        out.append(
            _unified(title, "Stepik", "Stepik",
                     f"https://stepik.org/course/{slug}", free_label="無料")
        )
    return out[:20]


def fetch_stepik(q):
    if not _tokens(q):
        return []
    url = ("https://stepik.org/api/courses?language=en&search="
           + urllib.parse.quote(q))
    return parse_stepik(_fetch_json(url, SOURCE_TIMEOUT))


EXTERNAL_SOURCES = [
    ("Coursera", fetch_coursera),
    ("Microsoft Learn", fetch_mslearn),
    ("Stepik", fetch_stepik),
]


def collect_results(q, fetchers=None):
    """内蔵＋外部ソースを並行取得し、統合・重複除去して返す。

    1ソースが落ちても他は返す（障害分離）。外部が全滅しても内蔵分は返る。
    戻り値: (結果リスト, ソース別ステータスリスト)
    """
    results = builtin_results(q)
    statuses = [{"source": "内蔵カタログ", "ok": True, "count": len(results)}]
    if fetchers is None:
        fetchers = EXTERNAL_SOURCES
    if _tokens(q) and fetchers:
        with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
            futures = {pool.submit(fn, q): name for name, fn in fetchers}
            for fut, name in futures.items():
                try:
                    items = fut.result(timeout=45)
                    statuses.append(
                        {"source": name, "ok": True, "count": len(items)})
                    results.extend(items)
                except Exception:
                    statuses.append({"source": name, "ok": False, "count": 0})
    seen_url, seen_tp, merged = set(), set(), []
    for r in results:
        nu = normalize_url(r["url"])
        tp = (r["title"].strip().lower(), r["provider"].strip().lower())
        if nu in seen_url or tp in seen_tp:
            continue
        seen_url.add(nu)
        seen_tp.add(tp)
        if not r["key"]:
            r["key"] = "u:" + nu
        merged.append(r)
    return merged, statuses


SEARCH_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>横断検索｜freecourse（無料講座カタログ）</title>
<style>{{ css|safe }}</style>
</head>
<body>
<div class="wrap">
  <header class="site">
    <div>
      <h1>🔎 横断検索</h1>
      <p class="tagline">複数の無料講座プラットフォームをまとめて検索します</p>
    </div>
    <button type="button" class="btn" id="theme-toggle" onclick="toggleTheme()">🌙 ダーク</button>
  </header>

  <p class="no-print"><a href="/">← 内蔵カタログに戻る</a></p>

  <form class="filters" method="get" action="/search">
    <label>キーワード
      <input type="text" name="q" value="{{ q | e }}" placeholder="例：python、excel、english">
    </label>
    <label>レベル
      <select name="level">
        <option value="">すべて</option>
        {% for lv in levels %}
        <option value="{{ lv }}" {% if level == lv %}selected{% endif %}>{{ lv }}</option>
        {% endfor %}
      </select>
    </label>
    <button type="submit" class="btn primary">検索</button>
  </form>

  <p class="summary">
    ソース別の結果：
    {% for s in statuses %}
      {{ s.source }}：{% if s.ok %}{{ s.count }} 件{% else %}取得失敗{% endif %}{% if not loop.last %}／{% endif %}
    {% endfor %}
  </p>
  {% if external_failed %}
  <p class="summary">※ 外部ソースに接続できなかったため、内蔵カタログの結果のみ表示しています。</p>
  {% endif %}
  <p class="summary">{{ results|length }} 件の講座｜あなたの進捗：受講中 <span id="count-doing">0</span> 件・完了 <span id="count-done">0</span> 件</p>
  <p class="summary">※ 外部ソースの講座は英語タイトルが中心です。「無料」バッジはソース側で無料と確認できたものにだけ付けています。料金・聴講条件は各講座ページでご確認ください。</p>

  <div class="grid">
  {% for r in results %}
    <article class="card" data-progress-key="{{ r.key }}">
      <h2>{{ r.title | e }}</h2>
      <div class="provider">提供元：{{ r.provider | e }}</div>
      <div class="badges">
        <span class="badge">{{ r.source | e }}</span>
        {% if r.level %}<span class="badge">{{ r.level | e }}</span>{% endif %}
        {% if r.free_label %}<span class="badge cert-free">{{ r.free_label | e }}</span>{% endif %}
        {% if r.cert_label %}<span class="badge">修了証：{{ r.cert_label | e }}</span>{% endif %}
      </div>
      {% if r.hours %}<div class="meta">目安時間：{{ r.hours | e }}</div>{% endif %}
      <a class="open" href="{{ r.url | e }}" target="_blank" rel="noopener">講座ページを開く →</a>
      <div class="status-row">
        <span class="status-label">未登録</span>
        <button type="button" class="btn small" onclick="setStatus('{{ r.key }}', 'doing')">受講中にする</button>
        <button type="button" class="btn small" onclick="setStatus('{{ r.key }}', 'done')">完了にする</button>
        <button type="button" class="btn small" onclick="setStatus('{{ r.key }}', '')">リセット</button>
      </div>
      {% if r.builtin_id %}
      <form class="cert-form" method="get" action="/certificate/{{ r.builtin_id }}">
      {% else %}
      <form class="cert-form" method="get" action="/certificate/custom">
        <input type="hidden" name="title" value="{{ r.title | e }}">
        <input type="hidden" name="provider" value="{{ r.provider | e }}">
      {% endif %}
        <label>修了証を作る（氏名を入力）
          <input type="text" name="name" placeholder="例：山田 太郎" required>
        </label>
        <button type="submit" class="btn primary small">修了証を表示する</button>
      </form>
    </article>
  {% else %}
    <p>条件に合う講座が見つかりませんでした。キーワードを変えてお試しください（外部ソースは英語キーワードがヒットしやすいです）。</p>
  {% endfor %}
  </div>

  <footer class="site">
    <p>※ 本ツールの修了証は学習記録証であり、各提供元の公式修了証ではありません。</p>
  </footer>
</div>
<script>
(function(){
  var root = document.documentElement;
  var savedTheme = localStorage.getItem('freecourse-theme');
  if (savedTheme) { root.setAttribute('data-theme', savedTheme); }
  updateThemeLabel();
  function updateThemeLabel(){
    var btn = document.getElementById('theme-toggle');
    if (btn) { btn.textContent = root.getAttribute('data-theme') === 'dark' ? '☀️ ライト' : '🌙 ダーク'; }
  }
  window.toggleTheme = function(){
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('freecourse-theme', next);
    updateThemeLabel();
  };
})();
var PROGRESS_KEY = 'freecourse-progress';
function loadProgress(){
  try { return JSON.parse(localStorage.getItem(PROGRESS_KEY) || '{}'); }
  catch (e) { return {}; }
}
function saveProgress(p){ localStorage.setItem(PROGRESS_KEY, JSON.stringify(p)); }
function setStatus(key, status){
  var p = loadProgress();
  if (status) { p[key] = status; } else { delete p[key]; }
  saveProgress(p);
  applyProgress();
}
function applyProgress(){
  var p = loadProgress();
  var doing = 0, done = 0;
  document.querySelectorAll('.card[data-progress-key]').forEach(function(card){
    var id = card.getAttribute('data-progress-key');
    var st = p[id] || '';
    var label = card.querySelector('.status-label');
    var form = card.querySelector('.cert-form');
    label.className = 'status-label' + (st ? ' ' + st : '');
    label.textContent = st === 'done' ? '✅ 完了' : (st === 'doing' ? '📖 受講中' : '未登録');
    if (form) { form.classList.toggle('visible', st === 'done'); }
    if (st === 'doing') { doing++; }
    if (st === 'done') { done++; }
  });
  document.getElementById('count-doing').textContent = doing;
  document.getElementById('count-done').textContent = done;
}
applyProgress();
</script>
</body>
</html>
"""


@app.route("/search")
def search():
    q = request.args.get("q", "")
    level = request.args.get("level", "")
    results, statuses = collect_results(q)
    if level:
        # レベル不明の講座は除外しない（情報が無いだけで対象外とは限らないため）
        results = [r for r in results if r["level"] in ("", level)]
    external = [s for s in statuses if s["source"] != "内蔵カタログ"]
    external_failed = bool(external) and not any(s["ok"] for s in external)
    return render_template_string(
        SEARCH_TEMPLATE,
        css=BASE_CSS,
        results=results,
        statuses=statuses,
        external_failed=external_failed,
        q=q,
        level=level,
        levels=LEVELS,
    )


@app.route("/certificate/custom")
def certificate_custom():
    """検索結果（外部ソース）の講座向け修了証。タイトル＋提供元で識別する。"""
    title = (request.args.get("title") or "").strip()
    provider = (request.args.get("provider") or "").strip()
    if not title:
        abort(404)
    name = (request.args.get("name") or "").strip()
    today = datetime.now(ZoneInfo("Asia/Tokyo"))
    date_str = f"{today.year}年{today.month}月{today.day}日"
    course = {
        "title": title,
        "provider": provider or "（提供元不明）",
        "category": "横断検索の講座",
        "level": "―",
    }
    cert_action = "/certificate/custom?" + urllib.parse.urlencode(
        {"title": title, "provider": provider}
    )
    return render_template_string(
        CERT_TEMPLATE,
        css=BASE_CSS,
        course=course,
        name=name,
        date_str=date_str,
        disclaimer=DISCLAIMER,
        cert_action=cert_action,
    )


if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
