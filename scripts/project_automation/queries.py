"""GraphQL document construction with injection-safe variable inlining.

Templates are static code WITHOUT GraphQL variable declarations: build_query()
substitutes $name tokens with json.dumps() literals in a single pass over the
template, so value content is never re-scanned and cannot alter the document.
"""
from __future__ import annotations

import json
import re

from .errors import ConfigError

_VAR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def build_query(template: str, **variables) -> str:
    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in variables:
            raise ConfigError(f"no value provided for GraphQL variable ${name}")
        return json.dumps(variables[name])

    return _VAR.sub(substitute, template)


PROJECT_CONTEXT = """
query {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      status: field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
      priority: field(name: "Priority") { ... on ProjectV2SingleSelectField { id options { id name } } }
      iteration: field(name: "Iteration") {
        ... on ProjectV2IterationField { id configuration { duration startDay iterations { id title startDate duration } } }
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
