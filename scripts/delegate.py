"""
Task Delegator - AI秘書の作業委任担当
「claude」ラベルがついたIssueを検知し、
@claude コメントで実装を自動依頼する。
"""

import os
import yaml
import requests

GH_TOKEN = os.getenv("GH_TOKEN")
SLACK_URL = os.getenv("SLACK_URL")

TRIGGER_LABEL = "claude"


def load_config():
    with open("config/projects.yml", "r") as f:
        return yaml.safe_load(f)


def fetch_labeled_issues(repo):
    """リポジトリから「claude」ラベルのオープンIssueを取得"""
    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    params = {"labels": TRIGGER_LABEL, "state": "open", "per_page": 100}
    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()

    if isinstance(data, dict):
        print(f"⚠️ {repo}: API error - {data.get('message', 'Unknown error')}")
        return []

    # PRを除外
    return [issue for issue in data if "pull_request" not in issue]


def has_claude_comment(repo, issue_number):
    """既に @claude コメントが投稿済みか確認"""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return False

    for comment in resp.json():
        if "@claude" in comment.get("body", ""):
            return True
    return False


def comment_claude(repo, issue_number, issue_title):
    """Issueに @claude コメントを投稿して実装を依頼"""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    body = (
        f"@claude このIssueの内容を実装してください。\n\n"
        f"- ブランチを作成し、必要な変更を実装してPRを作成してください\n"
        f"- 既存のコードスタイルとプロジェクトの規約に従ってください\n"
        f"- テストがあれば追加・更新してください"
    )

    resp = requests.post(url, headers=headers, json={"body": body})
    if resp.status_code == 201:
        print(f"✅ {repo}#{issue_number} ({issue_title}) に @claude で実装依頼しました")
        return True
    else:
        print(f"❌ {repo}#{issue_number} コメント失敗: {resp.status_code}")
        return False


def remove_label(repo, issue_number):
    """処理済みのclaudeラベルを除去（再トリガー防止）"""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels/{TRIGGER_LABEL}"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    requests.delete(url, headers=headers)


def notify_slack(results):
    """結果をSlack通知"""
    if not SLACK_URL or not results:
        return

    messages = ["🤖 *Claude Codeに作業を委任しました*"]
    for r in results:
        status = "✅" if r["success"] else "❌"
        messages.append(f"  {status} [{r['project']}] #{r['number']} {r['title']}")

    requests.post(SLACK_URL, json={"text": "\n".join(messages)})


def main():
    config = load_config()
    print("🔍 claudeラベルのIssueを検索中...")

    results = []

    for pjt in config["projects"]:
        repo = pjt["repo"]
        name = pjt["name"]
        issues = fetch_labeled_issues(repo)

        for issue in issues:
            number = issue["number"]
            title = issue["title"]

            # 既に @claude コメント済みならスキップ
            if has_claude_comment(repo, number):
                print(f"⏭️ {repo}#{number} は既に依頼済み。スキップ。")
                continue

            success = comment_claude(repo, number, title)
            if success:
                remove_label(repo, number)

            results.append({
                "project": name,
                "repo": repo,
                "number": number,
                "title": title,
                "success": success,
            })

    if not results:
        print("📭 claudeラベルのIssueはありません。")
        return

    notify_slack(results)


if __name__ == "__main__":
    main()
