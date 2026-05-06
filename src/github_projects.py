"""
GitHub Projects v2 GraphQL API クライアント
カンバン操作・イシューコメント追加を行う
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


def _get_project_status_field(project_node_id: str) -> dict:
    """
    プロジェクトの Status フィールドとその全オプションを取得する

    Returns:
        {"field_id": str, "options": [{"id": str, "name": str}, ...]}
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
                            options {
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """
    data = _graphql(query, {"projectId": project_node_id})
    fields = data["node"]["fields"]["nodes"]

    # name フィールドを持つものだけフィルタ（SingleSelectField のみ）
    for field in fields:
        if field.get("name") == "Status":
            return {
                "field_id": field["id"],
                "options": field["options"],
            }

    raise ValueError("プロジェクトに 'Status' フィールドが見つかりません")


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
                            options {
                                id
                                name
                            }
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
                    logger.info(
                        f"フィールド '{status_field_name}' / オプション '{option_name}' を取得しました"
                    )
                    return field["id"], option["id"]

    available = [
        f"{f.get('name')}: {[o['name'] for o in f.get('options', [])]}"
        for f in fields
        if f.get("options")
    ]
    raise ValueError(
        f"フィールド '{status_field_name}' またはオプション '{option_name}' が見つかりません\n"
        f"利用可能なフィールドとオプション: {available}"
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
            projectV2Item {
                id
            }
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
            input: {
                subjectId: $subjectId
                body: $body
            }
        ) {
            commentEdge {
                node {
                    id
                    url
                }
            }
        }
    }
    """
    data = _graphql(mutation, {"subjectId": issue_node_id, "body": body})
    comment_url = data["addComment"]["commentEdge"]["node"]["url"]
    logger.info(f"コメントを追加しました: {comment_url}")
    return comment_url


def get_project_node_id(owner: str, project_number: int) -> str:
    """オーナー名とProject番号からProject Node IDを取得する"""
    query = """
    query GetProjectNodeId($owner: String!, $number: Int!) {
        user(login: $owner) {
            projectV2(number: $number) {
                id
            }
        }
    }
    """
    try:
        data = _graphql(query, {"owner": owner, "number": project_number})
        return data["user"]["projectV2"]["id"]
    except Exception:
        # Organization の場合
        query_org = """
        query GetProjectNodeIdOrg($owner: String!, $number: Int!) {
            organization(login: $owner) {
                projectV2(number: $number) {
                    id
                }
            }
        }
        """
        data = _graphql(query_org, {"owner": owner, "number": project_number})
        return data["organization"]["projectV2"]["id"]
