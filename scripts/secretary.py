"""
AI Secretary - PRチェック & レビュー支援
Claude APIを使ったPR差分の要約とリスク判定機能付き。
"""

import os
import requests
import yaml
from datetime import datetime, timezone

# GitHub & Slack 設定
GH_TOKEN = os.getenv("GH_TOKEN")
SLACK_URL = os.getenv("SLACK_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# リスク判定キーワード
RISK_KEYWORDS = [
    "migration", "migrate", "schema", "alter table", "drop table",
    "add_column", "remove_column", "rename_column",
    "Gemfile.lock", "package-lock.json", "yarn.lock", "poetry.lock",
    "requirements.txt", "Pipfile.lock",
    "Dockerfile", "docker-compose",
    ".env", "secrets", "credentials",
]


def get_my_username():
    """認証ユーザーのGitHubユーザー名を取得"""
    url = "https://api.github.com/user"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    response = requests.get(url, headers=headers)
    data = response.json()
    return data.get("login")


def get_pull_requests(repo, creator=None):
    """オープンなPR一覧を取得（creatorで絞り込み可）"""
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    params = {}
    if creator:
        params["creator"] = creator
    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    # APIエラー時は辞書が返る（例: {"message": "Not Found"}）
    if isinstance(data, dict):
        print(f"⚠️ {repo}: API error - {data.get('message', 'Unknown error')}")
        return []
    return data


def get_pr_diff(repo, pr_number):
    """PRの差分を取得"""
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
    }
    response = requests.get(url, headers=headers)
    return response.text


def detect_risk(diff_text):
    """破壊的変更のリスクを検出"""
    diff_lower = diff_text.lower()
    found_risks = []
    for keyword in RISK_KEYWORDS:
        if keyword.lower() in diff_lower:
            found_risks.append(keyword)
    return found_risks


def summarize_with_claude(diff_text, pr_title):
    """Claude APIでPRの差分を要約"""
    if not ANTHROPIC_API_KEY:
        return None

    # 差分が大きすぎる場合は先頭を切り取る（トークン節約）
    max_diff_chars = 12000
    truncated = diff_text[:max_diff_chars]
    if len(diff_text) > max_diff_chars:
        truncated += "\n... (以下省略)"

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": f"""以下のPR（タイトル: {pr_title}）の差分を分析し、日本語で3行以内に要約してください。
- 1行目: 何を変更したか
- 2行目: なぜ変更したか（推測で可）
- 3行目: 注意点やレビュー時の確認ポイント

差分:
```
{truncated}
```""",
            }
        ],
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
    except Exception as e:
        print(f"⚠️ Claude API エラー: {e}")
        return None


def format_pr_message(pr, repo, summary, risks):
    """PR1件分のSlackメッセージを整形"""
    title = pr["title"]
    url = pr["html_url"]
    is_draft = pr["draft"]

    # レビュー状態の取得
    reviews_url = pr["_links"]["self"]["href"] + "/reviews"
    reviews = requests.get(
        reviews_url, headers={"Authorization": f"token {GH_TOKEN}"}
    ).json()
    is_approved = any(r["state"] == "APPROVED" for r in reviews)

    # ステータスアイコンと次のアクション
    if is_draft:
        status_line = f"  🟡 Draft: <{url}|{title}>"
        action = "→ Readyにしてね"
    elif is_approved:
        status_line = f"  🍏 *Approved!*: <{url}|{title}>"
        action = "→ マージ忘れ？"
    else:
        status_line = f"  🔵 Review中: <{url}|{title}>"
        action = "→ レビュー催促する？"

    # リスク警告
    risk_line = ""
    if risks:
        risk_line = f"\n  ⚠️ *破壊的変更の可能性*: {', '.join(risks)}"

    # AI要約
    summary_line = ""
    if summary:
        summary_line = f"\n  🤖 _{summary}_"

    return f"{status_line}\n  {action}{risk_line}{summary_line}"


def check_all_projects():
    """全プロジェクトのPRをチェック（自分が作ったPRのみ）"""
    with open("config/projects.yml", "r") as f:
        config = yaml.safe_load(f)

    my_username = get_my_username()
    print(f"👤 認証ユーザー: {my_username}")

    messages = ["🌙 *夜のPRチェック報告です*"]

    if ANTHROPIC_API_KEY:
        messages[0] += " (AI要約付き 🧠)"

    for pjt in config["projects"]:
        repo = pjt["repo"]
        name = pjt["name"]
        prs = get_pull_requests(repo, creator=my_username)

        if not prs:
            messages.append(f"✅ *{name}*: オープンPRなし。")
            continue

        messages.append(f"\n📂 *{name}* ({len(prs)}件のPR):")

        for pr in prs:
            pr_number = pr["number"]

            # PR差分を取得して分析
            summary = None
            risks = []
            if ANTHROPIC_API_KEY or True:  # リスク検出はAPI不要
                diff = get_pr_diff(repo, pr_number)
                risks = detect_risk(diff)

                # Claude APIがある場合のみ要約生成
                if ANTHROPIC_API_KEY:
                    summary = summarize_with_claude(diff, pr["title"])

            msg = format_pr_message(pr, repo, summary, risks)
            messages.append(msg)

    # Slack送信
    full_message = "\n".join(messages)
    print(full_message)  # ログ出力

    payload = {"text": full_message}
    requests.post(SLACK_URL, json=payload)


if __name__ == "__main__":
    check_all_projects()
