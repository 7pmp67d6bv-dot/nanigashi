"""
GitHub Projects v2 GraphQL API クライアント
カンバン操作・イシューコメント追加・Writingアイテムのポーリングを行う
"""

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"


def _graphql(query: str, variables: dict = None, token: str = None) -> dict[str, Any]:
    """GitHub GraphQL API にリクエストを送り、data フィールドを返す"""
    token = token or os.environ["GH_PAT"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    response = requests.post(GRAPHQL_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    body = response.json()
    if "errors" in body:
        raise RuntimeError(f"GitHub GraphQL エラー: {body['errors']}")

    return body["data"]


def get_writing_items(owner: str, project_number: int, status_field_name: str, writing_column: str) -> list[dict]:
    """
    プロジェクト内で "Writing" カラムにあるIssueアイテムを全件取得する

    Returns:
        [
            {
                "item_node_id": str,
                "content_node_id": str,
                "project_node_id": str,
            },
            ...
        ]
    """
    # まずプロジェクトのNode IDとStatusフィールドのオプションIDを取得
    query = """
    query GetWritingItems($owner: String!, $number: Int!) {
        user(login: $owner) {
            projectV2(number: $number) {
                id
                fields(first: 20) {
                    nodes {
                        ... on ProjectV2SingleSelectField {
                            id
                            name
                            options { id name }
                        }
                    }
                }
                items(first: 50) {
                    nodes {
                        id
                        fieldValues(first: 20) {
                            nodes {
                                ... on ProjectV2ItemFieldSingleSelectValue {
                                    name
                                    field {
                                        ... on ProjectV2SingleSelectField {
                                            name
                                        }
                                    }
                                }
                            }
                        }
                        content {
                            ... on Issue {
                                id
                                title
                            }
                        }
                    }
                }
            }
        }
    }
    """
    data = _graphql(query, {"owner": owner, "number": project_number})
    project = data["user"]["projectV2"]
    project_node_id = project["id"]

    results = []
    for item in project["items"]["nodes"]:
        # contentがIssueでないものはスキップ
        content = item.get("content")
        if not content or "id" not in content:
            continue

        # このアイテムのStatusフィールド値を確認
        for fv in item["fieldValues"]["nodes"]:
            field = fv.get("field", {})
            if field.get("name") == status_field_name and fv.get("name") == writing_column:
                results.append({
                    "item_node_id": item["id"],
                    "content_node_id": content["id"],
                    "project_node_id": project_node_id,
                    "title": content["title"],
                })
                break

    logger.info(f"Writingカラムのアイテム数: {len(results)}")
    return results


def get_issue_details(issue_node_id: str) -> dict:
    """イシューのタイトル・本文・番号・URLを取得する"""
    query = """
    query GetIssue($nodeId: ID!) {
        node(id: $nodeId) {
            ... on Issue {
                title
                body
                number
                url
            }
        }
    }
    """
    data = _graphql(query, {"nodeId": issue_node_id})
    node = data["node"]
    if not node:
        raise ValueError(f"イシューが見つかりません: {issue_node_id}")
    return node


def get_option_id(project_node_id: str, status_field_name: str, option_name: str) -> tuple[str, str]:
    """
    指定した列名（例: "Ready"）の field_id と option_id を返す

    Returns:
        (field_id, option_id)
    """
    query = """
    query GetProjectFields($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                fields(first: 30) {
                    nodes {
                        ... on ProjectV2SingleSelectField {
                            id
                            name
                            options { id name }
                        }
                    }
                }
            }
        }
    }
    """
    data = _graphql(query, {"projectId": project_node_id})
    fields = data["node"]["fields"]["nodes"]

    for field in fields:
        if field.get("name") == status_field_name:
            for option in field.get("options", []):
                if option["name"] == option_name:
                    return field["id"], option["id"]

    available = [
        f"{f.get('name')}: {[o['name'] for o in f.get('options', [])]}"
        for f in fields if f.get("options")
    ]
    raise ValueError(
        f"フィールド '{status_field_name}' またはオプション '{option_name}' が見つかりません\n"
        f"利用可能: {available}"
    )


def move_item_to_column(
    project_node_id: str,
    item_node_id: str,
    field_id: str,
    option_id: str,
) -> None:
    """プロジェクトアイテムを指定のカラムに移動する"""
    mutation = """
    mutation MoveItem(
        $projectId: ID!
        $itemId: ID!
        $fieldId: ID!
        $optionId: String!
    ) {
        updateProjectV2ItemFieldValue(
            input: {
                projectId: $projectId
                itemId: $itemId
                fieldId: $fieldId
                value: { singleSelectOptionId: $optionId }
            }
        ) {
            projectV2Item { id }
        }
    }
    """
    _graphql(
        mutation,
        {
            "projectId": project_node_id,
            "itemId": item_node_id,
            "fieldId": field_id,
            "optionId": option_id,
        },
    )
    logger.info(f"カードを移動しました (item={item_node_id})")


def add_issue_comment(issue_node_id: str, body: str) -> str:
    """イシューにコメントを追加してコメントURLを返す"""
    mutation = """
    mutation AddComment($subjectId: ID!, $body: String!) {
        addComment(
            input: { subjectId: $subjectId, body: $body }
        ) {
            commentEdge {
                node { id url }
            }
        }
    }
    """
    data = _graphql(mutation, {"subjectId": issue_node_id, "body": body})
    comment_url = data["addComment"]["commentEdge"]["node"]["url"]
    logger.info(f"コメントを追加しました: {comment_url}")
    return comment_url
