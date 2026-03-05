"""
Task Delegator - AI秘書の作業委任担当
指定されたIssueに @claude コメントを投稿し、
Claude Codeに実装を自動で任せる。
"""

import os
import re
import yaml
import requests

GH_TOKEN = os.getenv("GH_TOKEN")
SLACK_URL = os.getenv("SLACK_URL")
ISSUE_INPUT = os.getenv("ISSUE_INPUT", "")  # "#12 #15" or "jreast#12 inak#15"


def load_config():
    with open("config/projects.yml", "r") as f:
        return yaml.safe_load(f)


def parse_issue_input(text, config):
    """
    入力テキストからIssue情報をパース
    対応フォーマット:
      - "#12 #15"                → 全PJTから探す
      - "jreast#12 inak#15"     → PJT指定
      - "#12やって #15お願い"    → 日本語混じりOK
    """
    # プロジェクト名→repoのマッピング
    name_to_repo = {pjt["name"]: pjt["repo"] for pjt in config["projects"]}

    issues = []

    # "pjt名#番号" パターン
    named_pattern = re.findall(r'(\w+)#(\d+)', text)
    for name, number in named_pattern:
        if name in name_to_repo:
            issues.append({
                "project": name,
                "repo": name_to_repo[name],
                "number": int(number),
            })

    # マッチしなかったら、"#番号" パターンで全PJTから探す
    if not issues:
        bare_numbers = re.findall(r'#(\d+)', text)
        for number in bare_numbers:
            issue_info = find_issue_in_projects(int(number), config)
            if issue_info:
                issues.append(issue_info)

    return issues


def find_issue_in_projects(number, config):
    """Issue番号から該当するPJTを探す"""
    headers = {"Authorization": f"token {GH_TOKEN}"}
    for pjt in config["projects"]:
        repo = pjt["repo"]
        url = f"https://api.github.com/repos/{repo}/issues/{number}"
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if "pull_request" not in data:  # PRを除外
                return {
                    "project": pjt["name"],
                    "repo": repo,
                    "number": number,
                }
    return None


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
        print(f"❌ {repo}#{issue_number} コメント失敗: {resp.status_code} {resp.text}")
        return False


def get_issue_title(repo, number):
    """Issue タイトルを取得"""
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    headers = {"Authorization": f"token {GH_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json().get("title", "")
    return ""


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
    if not ISSUE_INPUT.strip():
        print("❌ ISSUE_INPUT が空です。例: '#12 #15' or 'jreast#12'")
        return

    config = load_config()
    issues = parse_issue_input(ISSUE_INPUT, config)

    if not issues:
        print(f"❌ Issueが見つかりません: {ISSUE_INPUT}")
        return

    print(f"📋 {len(issues)}件のIssueに @claude で実装依頼します")

    results = []
    for issue in issues:
        title = get_issue_title(issue["repo"], issue["number"])
        success = comment_claude(issue["repo"], issue["number"], title)
        results.append({
            "project": issue["project"],
            "repo": issue["repo"],
            "number": issue["number"],
            "title": title,
            "success": success,
        })

    notify_slack(results)


if __name__ == "__main__":
    main()
