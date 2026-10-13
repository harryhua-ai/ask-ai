#!/usr/bin/env python3
"""Publish the bound Runtime's exact-SHA review predicate as a GitHub Check."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


CHECK_NAME = "ght-canonical-exact-sha-review"
SNAPSHOT_START = "<!-- ght:candidate-snapshot:v1 -->"
SNAPSHOT_END = "<!-- /ght:candidate-snapshot:v1 -->"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _full_sha(value: Any, length: int = 40) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _snapshot_block(body: Any) -> str | None:
    if not isinstance(body, str) or body.count(SNAPSHOT_START) != 1 \
            or body.count(SNAPSHOT_END) != 1:
        return None
    start = body.index(SNAPSHOT_START)
    end = body.index(SNAPSHOT_END)
    if end <= start:
        return None
    return body[start:end + len(SNAPSHOT_END)]


def _partial_result(observation: dict[str, Any], verdict: str,
                    reason: str) -> dict[str, Any]:
    pr_obj = observation.get("pr") if isinstance(observation, dict) else None
    pr_obj = pr_obj if isinstance(pr_obj, dict) else {}
    head = pr_obj.get("head") if isinstance(pr_obj.get("head"), dict) else {}
    claim = observation.get("claim") if isinstance(observation, dict) else None
    claim = claim if isinstance(claim, dict) else {}
    delivery = claim.get("delivery") if isinstance(claim.get("delivery"), dict) else {}
    candidate = claim.get("candidate") if isinstance(claim.get("candidate"), dict) else {}
    runtime = observation.get("runtime")
    evidence = {
        "issue": observation.get("issue"),
        "pr": pr_obj.get("number"),
        "pr_head_sha": head.get("sha"),
        "claim_ref_sha": observation.get("claim_sha"),
        "claim_id": claim.get("claim_id"),
        "delivery": delivery,
        "runtime": runtime,
        "attempt_runtime_binding": claim.get("runtime"),
        "runtime_ref_sha": observation.get("runtime_ref_sha"),
        "snapshot_sha256": None,
        "reviews_sha256": _sha256(observation.get("reviews"))
        if observation.get("reviews") is not None else None,
        "comments_sha256": _sha256(observation.get("comments"))
        if observation.get("comments") is not None else None,
    }
    block = _snapshot_block(pr_obj.get("body"))
    if block is not None:
        evidence["snapshot_sha256"] = hashlib.sha256(block.encode("utf-8")).hexdigest()
    return {
        "verdict": verdict,
        "reason": reason,
        "issue": observation.get("issue"),
        "pr": pr_obj.get("number"),
        "pr_head_sha": head.get("sha"),
        "candidate_sha": delivery.get("sha") or candidate.get("sha"),
        "runtime": runtime,
        "attempt_runtime_binding": claim.get("runtime"),
        "evidence": evidence,
        "evidence_id": _sha256(evidence),
        "checked_at": _now(),
    }


def _validate_binding(observation: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    pr_obj = observation.get("pr")
    claim = observation.get("claim")
    runtime = observation.get("runtime")
    if not isinstance(pr_obj, dict) or not isinstance(claim, dict):
        return None, "PR or durable claim is unavailable"
    if observation.get("read_error"):
        return None, str(observation["read_error"])
    head = pr_obj.get("head")
    if not isinstance(head, dict):
        return None, "current PR head is unreadable"
    issue = observation.get("issue")
    pr_number = pr_obj.get("number")
    branch = head.get("ref")
    head_sha = head.get("sha")
    if not isinstance(issue, int) or not isinstance(pr_number, int):
        return None, "Issue or PR identity is unreadable"
    if observation.get("requested_pr") not in (None, pr_number):
        return None, "GitHub returned a different PR than the requested event"
    if pr_obj.get("state") != "open":
        return None, "PR is not open for pre-merge review"
    if not _full_sha(head_sha):
        return None, "current PR head SHA is not a full commit SHA"
    if not isinstance(branch, str):
        return None, "current PR branch is unreadable"
    branch_match = re.fullmatch(r"agent/([1-9][0-9]*)/([^/]+)", branch)
    if branch_match is None or int(branch_match.group(1)) != issue:
        return None, "PR branch is not the canonical attempt branch for its Issue"
    head_repo = (head.get("repo") or {}).get("full_name") \
        if isinstance(head.get("repo"), dict) else None
    repository = observation.get("repository")
    if not isinstance(repository, str) or head_repo != repository:
        return None, "PR head repository does not match the target repository"
    if claim.get("task") != issue or claim.get("status") != "active":
        return None, "durable claim is not the current active attempt for this Issue"
    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id:
        return None, "durable claim has no attempt identity"
    claim_branch = claim.get("branch")
    execution_base = claim.get("execution_base")
    if claim_branch != branch or not _full_sha(execution_base):
        return None, "PR branch or execution base does not match the durable claim"
    claim_sha = observation.get("claim_sha")
    if not _full_sha(claim_sha):
        return None, "durable claim ref identity is unavailable"
    candidate = claim.get("candidate")
    delivery = claim.get("delivery")
    if not isinstance(candidate, dict) or not isinstance(delivery, dict):
        return None, "durable Candidate delivery is unavailable"
    candidate_sha = candidate.get("sha")
    if not _full_sha(candidate_sha) or delivery.get("sha") != candidate_sha \
            or delivery.get("pr") != pr_number or not delivery.get("delivered_at"):
        return None, "latest delivery does not bind this PR and Candidate SHA"
    if candidate_sha != head_sha:
        return None, "PR HEAD changed after the latest exact-SHA delivery"
    if observation.get("runtime_error"):
        return None, str(observation["runtime_error"])
    if not isinstance(runtime, dict):
        return None, "attempt-bound Runtime identity is unavailable"
    claim_runtime = claim.get("runtime")
    if not isinstance(claim_runtime, dict):
        return None, "attempt has no durable Runtime binding"
    runtime_digest = runtime.get("digest")
    runtime_release = runtime.get("release")
    runtime_source = runtime.get("source_sha")
    if (not _full_sha(runtime_digest, 64)
            or not isinstance(runtime_release, str)
            or re.fullmatch(r"v\d+(?:\.\d+)*", runtime_release) is None
            or not _full_sha(runtime_source)):
        return None, "Runtime capsule identity is incomplete or non-canonical"
    if any(claim_runtime.get(key) != runtime.get(key)
           for key in ("digest", "release", "source_sha")):
        return None, "Runtime capsule identity differs from the attempt binding"
    if not _full_sha(observation.get("runtime_ref_sha")):
        return None, "Runtime capsule ref identity is unavailable"
    block = _snapshot_block(pr_obj.get("body"))
    if block is None:
        return None, "current Candidate Snapshot is absent or ambiguous"
    snapshot_facts = (
        f"## Current Candidate Snapshot — #{issue} / PR #{pr_number}",
        f"- exact Candidate: `{candidate_sha}`",
        f"- claim: `{claim_id}` · branch: `{branch}` · execution_base: `{execution_base}`",
        f"delivered: {delivery['delivered_at']}",
    )
    if any(block.count(fact) != 1 for fact in snapshot_facts):
        return None, "current Candidate Snapshot does not match the latest delivery"
    return {
        "issue": issue,
        "pr": pr_number,
        "pr_head_sha": head_sha,
        "candidate_sha": candidate_sha,
        "branch": branch,
        "claim_id": claim_id,
        "claim_ref_sha": claim_sha,
        "delivery": delivery,
        "runtime": runtime,
        "runtime_ref_sha": observation["runtime_ref_sha"],
        "snapshot_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
        "reviews_sha256": _sha256(observation.get("reviews"))
        if observation.get("reviews") is not None else None,
        "comments_sha256": _sha256(observation.get("comments"))
        if observation.get("comments") is not None else None,
    }, None


def _evaluate(observation: dict[str, Any],
              predicate: Callable[..., dict[str, Any]] | None) -> dict[str, Any]:
    binding, error = _validate_binding(observation)
    if error:
        return _partial_result(observation, "UNKNOWN", error)
    if predicate is None:
        return _partial_result(observation, "UNKNOWN",
                               observation.get("runtime_error")
                               or "attempt-bound canonical predicate is unavailable")
    reviews = observation.get("reviews")
    comments = observation.get("comments")
    verdict = predicate(reviews=reviews, comments=comments,
                        candidate_sha=binding["candidate_sha"])
    unreadable = verdict.get("unreadable") if isinstance(verdict, dict) else None
    if unreadable:
        return _partial_result(observation, "UNKNOWN",
                               "canonical predicate could not read: " + ", ".join(unreadable))
    if not isinstance(verdict, dict) or not isinstance(verdict.get("accepted"), bool):
        return _partial_result(observation, "UNKNOWN",
                               "attempt-bound canonical predicate returned an invalid result")
    reason = ("canonical exact-SHA predicate accepted the current A review"
              if verdict["accepted"] else
              "canonical exact-SHA predicate did not recognize an acceptance for this Candidate")
    result = _partial_result(observation, "PASS" if verdict["accepted"] else "FAIL", reason)
    result["evidence"] = binding
    result["evidence_id"] = _sha256(binding)
    return result


def evaluate_and_bind(before: dict[str, Any], after: dict[str, Any],
                      predicate: Callable[..., dict[str, Any]] | None) -> dict[str, Any]:
    result = _evaluate(before, predicate)
    if _sha256(before) != _sha256(after):
        return _partial_result(after, "UNKNOWN",
                               "GitHub review or Candidate evidence changed during verification")
    return result


def verify_and_publish(before: dict[str, Any], after: dict[str, Any],
                       predicate: Callable[..., dict[str, Any]] | None,
                       create_check_run: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    result = evaluate_and_bind(before, after, predicate)
    try:
        check = create_check_run(result)
        if not isinstance(check, dict) or not isinstance(check.get("id"), int):
            raise RuntimeError("GitHub did not return a Check Run identity")
        result["check_run_id"] = check["id"]
    except Exception as exc:  # noqa: BLE001 - publication failure cannot retain PASS
        result["verdict"] = "UNKNOWN"
        result["reason"] = f"GitHub Check Run publication failed: {exc}"
        result.pop("check_run_id", None)
    return result


def _run(command: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(command, input=input_text, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(detail)
    return result.stdout


def _gh_api(path: str, *, payload: dict[str, Any] | None = None,
            paginate: bool = False) -> Any:
    binary = os.environ.get("GHT_REVIEW_GH_BIN", "gh")
    command = [binary, "api"]
    if payload is not None:
        command.extend(["--method", "POST", "--input", "-"])
    elif paginate:
        command.extend(["--paginate", "--slurp"])
    command.append(path)
    raw = _run(command, input_text=json.dumps(payload) if payload is not None else None)
    parsed = json.loads(raw)
    if paginate:
        if not isinstance(parsed, list):
            raise RuntimeError("GitHub pagination returned a non-list response")
        flattened: list[Any] = []
        for page in parsed:
            if not isinstance(page, list):
                raise RuntimeError("GitHub pagination returned an invalid page")
            flattened.extend(page)
        return flattened
    return parsed


def _git(command: list[str], *, binary: bool = False) -> str | bytes:
    remote = os.environ.get("GHT_REVIEW_REMOTE", "origin")
    full_command = ["git", *command]
    if full_command[1] == "ls-remote":
        full_command[2] = remote
    if binary:
        result = subprocess.run(full_command, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace").strip()
                               or "git command failed")
        return result.stdout
    return _run(full_command)


def _read_ref_files(ref: str, paths: tuple[str, ...]) -> tuple[dict[str, bytes], str]:
    remote = os.environ.get("GHT_REVIEW_REMOTE", "origin")
    before = str(_git(["ls-remote", remote, ref])).splitlines()
    matches = [line.split("\t", 1)[0] for line in before
               if "\t" in line and line.split("\t", 1)[1] == ref]
    if len(matches) != 1 or not _full_sha(matches[0]):
        raise RuntimeError(f"remote ref is absent or ambiguous: {ref}")
    wanted = matches[0]
    temp_ref = f"refs/ght/tmp/gha-review-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        _git(["fetch", "--force", remote, f"+{ref}:{temp_ref}"])
        fetched = str(_git(["rev-parse", f"{temp_ref}^{{commit}}"]).strip())
        if fetched != wanted:
            raise RuntimeError(f"remote ref changed while being read: {ref}")
        documents = {
            path: bytes(_git(["show", f"{temp_ref}:{path}"], binary=True))
            for path in paths
        }
        after = str(_git(["ls-remote", remote, ref])).splitlines()
        latest = [line.split("\t", 1)[0] for line in after
                  if "\t" in line and line.split("\t", 1)[1] == ref]
        if latest != [wanted]:
            raise RuntimeError(f"remote ref moved while being read: {ref}")
        return documents, wanted
    finally:
        subprocess.run(["git", "update-ref", "-d", temp_ref],
                       capture_output=True, text=True)


def _read_claim(issue: int) -> tuple[dict[str, Any], str]:
    ref = f"refs/ght/claims/{issue}"
    documents, ref_sha = _read_ref_files(ref, ("CLAIM.json",))
    claim = json.loads(documents["CLAIM.json"])
    if not isinstance(claim, dict):
        raise RuntimeError("durable claim is not a JSON object")
    return claim, ref_sha


def _extract_capsule(payload: bytes, destination: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        core_paths = [PurePosixPath(info.filename) for info in archive.infolist()
                      if PurePosixPath(info.filename).as_posix().endswith("github_task/core.py")]
        if len(core_paths) != 1:
            raise RuntimeError("Runtime capsule does not contain one canonical github_task/core.py")
        package_parts = core_paths[0].parts[:-2]
        package_root = destination.joinpath(*package_parts)
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts \
                    or stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError("Runtime capsule contains an unsafe archive path")
            target = destination.joinpath(*path.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        if not (package_root / "github_task" / "core.py").is_file():
            raise RuntimeError("Runtime capsule package root is invalid")
    return package_root


def _load_runtime(claim: dict[str, Any]) -> tuple[tempfile.TemporaryDirectory[str],
                                                   dict[str, str], str,
                                                   Callable[..., dict[str, Any]]]:
    binding = claim.get("runtime")
    if not isinstance(binding, dict) or not _full_sha(binding.get("digest"), 64):
        raise RuntimeError("attempt-bound Runtime capsule is not proven")
    digest = binding["digest"]
    ref = f"refs/ght/runtime/{digest}"
    files, ref_sha = _read_ref_files(ref, ("runtime.zip", "MANIFEST.json"))
    payload = files["runtime.zip"]
    if hashlib.sha256(payload).hexdigest() != digest:
        raise RuntimeError("Runtime capsule payload digest does not match its attempt binding")
    manifest = json.loads(files["MANIFEST.json"])
    if not isinstance(manifest, dict) or manifest.get("digest") != digest:
        raise RuntimeError("Runtime manifest does not match its attempt binding")
    identity = {key: manifest.get(key) for key in ("digest", "release", "source_sha")}
    if (not isinstance(identity["release"], str)
            or re.fullmatch(r"v\d+(?:\.\d+)*", identity["release"]) is None
            or not _full_sha(identity["source_sha"])):
        raise RuntimeError("Runtime manifest identity is incomplete or non-canonical")
    if any(binding.get(key) != identity[key] for key in identity):
        raise RuntimeError("Runtime manifest identity differs from the attempt binding")
    temporary = tempfile.TemporaryDirectory(prefix="ght-review-runtime-")
    root = Path(temporary.name)
    package_root = _extract_capsule(payload, root)
    saved_modules = {name: module for name, module in sys.modules.items()
                     if name == "github_task" or name.startswith("github_task.")}
    for name in saved_modules:
        del sys.modules[name]
    original_path = list(sys.path)
    sys.path.insert(0, str(package_root))
    try:
        core = importlib.import_module("github_task.core")
        core_path = Path(core.__file__).resolve()
        if not core_path.is_relative_to(package_root.resolve()):
            raise RuntimeError("canonical predicate was not loaded from the bound Runtime")
        predicate = getattr(core, "evaluate_exact_sha_acceptance", None)
        if not callable(predicate):
            raise RuntimeError("bound Runtime has no canonical exact-SHA predicate")
    except Exception:
        temporary.cleanup()
        raise
    finally:
        sys.path[:] = original_path
        for name in list(sys.modules):
            if name == "github_task" or name.startswith("github_task."):
                del sys.modules[name]
        sys.modules.update(saved_modules)
    return temporary, identity, ref_sha, predicate


def _read_surface(repo: str, path: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        result = _gh_api(path, paginate=True)
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise RuntimeError("GitHub returned an invalid review surface")
        return result, None
    except Exception as exc:  # noqa: BLE001 - unreadable surfaces are UNKNOWN
        return None, str(exc)


def _read_observation(repo: str, pr_number: int,
                      *, runtime: tuple[Any, dict[str, str], str, Callable[..., dict[str, Any]]] | None = None,
                      known_issue: int | None = None) -> tuple[dict[str, Any], int | None]:
    pr_obj = _gh_api(f"repos/{repo}/pulls/{pr_number}")
    head = pr_obj.get("head") if isinstance(pr_obj, dict) else None
    branch = head.get("ref") if isinstance(head, dict) else None
    match = re.fullmatch(r"agent/([1-9][0-9]*)/([^/]+)", branch or "")
    issue = int(match.group(1)) if match else known_issue
    observation: dict[str, Any] = {"repository": repo, "requested_pr": pr_number,
                                   "pr": pr_obj, "issue": issue}
    if not isinstance(head, dict) or not _full_sha(head.get("sha")):
        observation["read_error"] = "current PR head is unavailable"
        return observation, issue
    if match is None and isinstance(branch, str) and branch.startswith("agent/"):
        observation["read_error"] = "PR attempt branch is non-canonical"
        return observation, issue
    if issue is None:
        observation["read_error"] = "PR attempt branch has no Issue identity"
        return observation, issue
    try:
        claim, claim_sha = _read_claim(issue)
        observation["claim"] = claim
        observation["claim_sha"] = claim_sha
    except Exception as exc:  # noqa: BLE001 - durable truth failure is UNKNOWN
        observation["read_error"] = f"durable claim is unreadable: {exc}"
        claim = None
    runtime_identity = None
    runtime_ref_sha = None
    predicate = None
    if runtime is not None:
        temporary, runtime_identity, runtime_ref_sha, predicate = runtime
        bound = (claim or {}).get("runtime") if isinstance(claim, dict) else None
        if not isinstance(bound, dict) or any(bound.get(key) != runtime_identity.get(key)
                                               for key in runtime_identity):
            observation["runtime_error"] = "attempt Runtime binding changed during verification"
            predicate = None
        else:
            try:
                runtime_ref = f"refs/ght/runtime/{runtime_identity['digest']}"
                remote = os.environ.get("GHT_REVIEW_REMOTE", "origin")
                current = str(_git(["ls-remote", remote, runtime_ref]))
                refs = [line.split("\t", 1)[0] for line in current.splitlines()
                        if "\t" in line and line.split("\t", 1)[1]
                        == runtime_ref]
                if refs != [runtime_ref_sha]:
                    observation["runtime_error"] = "attempt-bound Runtime capsule ref changed"
                    predicate = None
            except Exception as exc:  # noqa: BLE001 - ref read failure is UNKNOWN
                observation["runtime_error"] = f"Runtime capsule ref is unreadable: {exc}"
                predicate = None
    else:
        observation["runtime_error"] = None
    observation["runtime"] = runtime_identity
    observation["runtime_ref_sha"] = runtime_ref_sha
    observation["runtime_error"] = observation.get("runtime_error")
    review_path = f"repos/{repo}/pulls/{pr_number}/reviews"
    comment_path = f"repos/{repo}/issues/{pr_number}/comments"
    reviews, reviews_error = _read_surface(repo, review_path)
    comments, comments_error = _read_surface(repo, comment_path)
    observation["reviews"] = reviews
    observation["comments"] = comments
    observation["reviews_error"] = reviews_error
    observation["comments_error"] = comments_error
    return observation, issue


def _check_summary(result: dict[str, Any]) -> str:
    runtime = result.get("runtime") or {}
    runtime_binding = result.get("attempt_runtime_binding") or {}
    evidence = result.get("evidence") or {}
    return "\n".join([
        f"Verdict: **{result['verdict']}**",
        f"Reason: {result['reason']}",
        f"PR: #{result.get('pr')}",
        f"PR head SHA: `{result.get('pr_head_sha')}`",
        f"Candidate SHA: `{result.get('candidate_sha')}`",
        "Runtime: " + (f"`{runtime.get('release')}` / `{runtime.get('source_sha')}` "
                        f"/ `{runtime.get('digest')}`" if runtime else "UNKNOWN"),
        "Attempt Runtime binding: " +
        (f"`{runtime_binding.get('release')}` / `{runtime_binding.get('source_sha')}` "
         f"/ `{runtime_binding.get('digest')}`" if runtime_binding else "UNKNOWN"),
        f"Evidence identity: `{result.get('evidence_id')}`",
        f"Claim ref: `{evidence.get('claim_ref_sha')}`",
        f"Snapshot SHA-256: `{evidence.get('snapshot_sha256')}`",
        f"Reviews SHA-256: `{evidence.get('reviews_sha256')}`",
        f"Comments SHA-256: `{evidence.get('comments_sha256')}`",
        f"Checked at: `{result.get('checked_at')}`",
    ])


def _create_check_run(repo: str, result: dict[str, Any]) -> dict[str, Any]:
    head_sha = result.get("pr_head_sha")
    if not _full_sha(head_sha):
        raise RuntimeError("current PR head SHA is unavailable")
    conclusion = "success" if result["verdict"] == "PASS" else "failure"
    payload: dict[str, Any] = {
        "name": CHECK_NAME,
        "head_sha": head_sha,
        "external_id": result["evidence_id"],
        "status": "completed",
        "conclusion": conclusion,
        "completed_at": result["checked_at"],
        "output": {
            "title": f"Canonical exact-SHA review: {result['verdict']}",
            "summary": _check_summary(result),
            "text": json.dumps(result, sort_keys=True, indent=2),
        },
    }
    server = os.environ.get("GITHUB_SERVER_URL")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server and run_id:
        payload["details_url"] = f"{server}/{repo}/actions/runs/{run_id}"
    return _gh_api(f"repos/{repo}/check-runs", payload=payload)


def _write_step_summary(result: dict[str, Any]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(_check_summary(result) + "\n")


def _main(pr_number: int) -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[^/]+/[^/]+", repo):
        raise RuntimeError("GITHUB_REPOSITORY is unavailable")
    first, issue = _read_observation(repo, pr_number)
    pr_obj = first.get("pr")
    if not isinstance(pr_obj, dict):
        print(json.dumps({"verdict": "UNKNOWN", "pr": pr_number,
                          "reason": first.get("read_error") or "PR is unreadable"}))
        return 2
    head = pr_obj.get("head") if isinstance(pr_obj.get("head"), dict) else {}
    branch = head.get("ref")
    if isinstance(branch, str) and not branch.startswith("agent/"):
        print(json.dumps({"applicable": False, "pr": pr_number}))
        return 0
    if issue is None:
        first["read_error"] = first.get("read_error") or "PR attempt branch has no Issue identity"
        predicate = None
        runtime = None
    else:
        claim = first.get("claim")
        runtime = None
        predicate = None
        if isinstance(claim, dict):
            try:
                runtime = _load_runtime(claim)
                first, _issue = _read_observation(repo, pr_number, runtime=runtime,
                                                  known_issue=issue)
                predicate = runtime[3]
            except Exception as exc:  # noqa: BLE001 - later evidence remains UNKNOWN
                first["runtime_error"] = f"attempt-bound Runtime is unavailable: {exc}"
    try:
        after, _issue = _read_observation(repo, pr_number, runtime=runtime,
                                          known_issue=issue)
    except Exception as exc:  # noqa: BLE001 - final reread failure is UNKNOWN
        after = dict(first)
        after["read_error"] = f"final GitHub evidence reread failed: {exc}"
    if runtime is None and first.get("runtime_error"):
        after["runtime_error"] = first["runtime_error"]
    result = verify_and_publish(
        first, after, predicate,
        lambda current: _create_check_run(repo, current),
    )
    _write_step_summary(result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("check_run_id") else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", type=int, help="Pull Request number from the GitHub event")
    args = parser.parse_args(argv)
    if args.pr < 1:
        parser.error("PR number must be positive")
    try:
        return _main(args.pr)
    except Exception as exc:  # noqa: BLE001 - no infrastructure failure can pass
        result = {"verdict": "UNKNOWN", "pr": args.pr, "pr_head_sha": None,
                  "candidate_sha": None, "runtime": None, "evidence_id": None,
                  "reason": str(exc), "checked_at": _now()}
        _write_step_summary(result)
        print(json.dumps(result), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
