"""GraphQL document construction with injection-safe variable inlining.

Templates are static code WITHOUT GraphQL variable declarations: build_query()
substitutes $name tokens with GraphQL literals in a single pass over the
template, so value content is never re-scanned and cannot alter the document.
Scalar values serialize as JSON strings/numbers; dicts/lists serialize as
GraphQL object/array literals (BARE keys — JSON's quoted keys are invalid
GraphQL input-object syntax).
"""
from __future__ import annotations

import json
import re

from .errors import ConfigError

_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def to_graphql_literal(value) -> str:
    if isinstance(value, dict):
        inner = ", ".join(f"{k}: {to_graphql_literal(v)}" for k, v in value.items())
        return "{ " + inner + " }"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(to_graphql_literal(v) for v in value) + "]"
    return json.dumps(value)  # str / int / bool / None


def build_query(template: str, **variables) -> str:
    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in variables:
            raise ConfigError(f"no value provided for GraphQL variable ${name}")
        return to_graphql_literal(variables[name])

    return _VAR.sub(substitute, template)


PROJECT_CONTEXT = """
query {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      status: field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
      priority: field(name: "Priority") { ... on ProjectV2SingleSelectField { id options { id name } } }
      iteration: field(name: "Iteration") {
        ... on ProjectV2IterationField { id configuration { duration startDay
          iterations { id title startDate duration }
          completedIterations { id title startDate duration } } }
      }
      sprint: field(name: "Sprint") {
        ... on ProjectV2IterationField { id configuration {
          iterations { id title startDate duration }
          completedIterations { id title startDate } } }
      }
    }
    repository(name: $repo) { id }
  }
}"""

PROJECT_ITEMS = """
query {
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            __typename
            ... on Issue { number state }
            ... on DraftIssue { title }
          }
          iteration: fieldValueByName(name: "Iteration") {
            ... on ProjectV2ItemFieldIterationValue { iterationId title }
          }
          sprint: fieldValueByName(name: "Sprint") {
            ... on ProjectV2ItemFieldIterationValue { iterationId title }
          }
          priority: fieldValueByName(name: "Priority") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
          status: fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}"""

ISSUE = """
query {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      id
      number
      state
      labels(first: 100) { nodes { name } }
      projectItems(first: 20) { nodes { id project { id number } } }
    }
  }
}"""

ADD_ITEM = """
mutation {
  addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
    item { id }
  }
}"""

SET_STATUS = """
mutation {
  updateProjectV2ItemFieldValue(input: { projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
    value: { singleSelectOptionId: $optionId } }) { projectV2Item { id } }
}"""

SET_ITERATION = """
mutation {
  updateProjectV2ItemFieldValue(input: { projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
    value: { iterationId: $iterationId } }) { projectV2Item { id } }
}"""

CLEAR_FIELD = """
mutation {
  clearProjectV2ItemFieldValue(input: { projectId: $projectId, itemId: $itemId, fieldId: $fieldId }) {
    projectV2Item { id }
  }
}"""

UPDATE_ITERATION_CONFIG = """
mutation {
  updateProjectV2Field(input: { fieldId: $fieldId, iterationConfiguration: {
    startDate: $startDate, duration: $duration, iterations: $iterations } }) {
    projectV2Field { ... on ProjectV2IterationField {
      configuration { duration startDay iterations { id title startDate duration } } } }
  }
}"""
