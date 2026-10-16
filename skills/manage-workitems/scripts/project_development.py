"""Prepare one recoverable code worktree and verify Git delivery against its review.

This module never commits code, changes the main checkout's branch, or replaces a
remote branch. The workflow publishes exclusive ownership before calling prepare.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import os
import re

try:
    import project_store as store
except ImportError:  # pragma: no cover
    from . import project_store as store

try:
    import project_runtime as runtime
except ImportError:  # pragma: no cover
    from . import project_runtime as runtime

ProjectError = runtime.ProjectError
_git = runtime._git
_text = runtime._git_text


def _repository(item, project):
    matches = [repo for repo in project.get("repositories", []) if repo.get("id") == item.get("repository")]
    if len(matches) != 1 or not matches[0].get("url"):
        raise ProjectError("development requires one configured project repository")
    return matches[0]


def worktree_location(root, item, project):
    """Resolve the recorded portable location with runtime's binding checks."""
    root = Path(root).resolve()
    development = item.get("development") or {}
    base, container = runtime._layout(root, project)
    relative = runtime._worktree_relative(development.get("worktree"), container)
    return runtime._resolve_worktree(root, project, base, relative)


def _main_workspace(root, project):
    """Resolve the explicit local trust anchor; relative routes cannot leave it."""
    if "main_workspace" not in project:
        return None
    runtime._no_links(root, ".project/main-workspace.md")
    if not (root / ".project/main-workspace.md").is_file():
        raise ProjectError("associated project requires its main-workspace navigation document")
    runtime._no_links(root, ".project-local/main-workspace.json")
    path = root / ".project-local/main-workspace.json"
    if not path.is_file():
        raise ProjectError("main workspace is not bound; original AGENTS.md cannot be read")
    binding = runtime.read_json(path)
    if not isinstance(binding, dict) or binding.get("id") != project["main_workspace"]["id"]:
        raise ProjectError("main workspace binding id does not match project.main_workspace.id")
    value = binding.get("root")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ProjectError("main workspace binding root must be an absolute directory")
    selected = Path(value)
    if selected.is_symlink() or not selected.is_dir():
        raise ProjectError("main workspace binding root must be an existing regular directory")
    # The explicitly bound root is the trust anchor. Canonicalize platform aliases
    # such as macOS /var before checking paths beneath that anchor.
    main = selected.resolve()
    if main == root or root in main.parents:
        raise ProjectError("main workspace root cannot equal or be inside the project")
    repository = project["main_workspace"].get("repository")
    if repository is not None:
        if Path(_text(main, "rev-parse", "--show-toplevel")).resolve() != main:
            raise ProjectError("main workspace repository must be rooted at its binding")
        urls = set()
        for remote in _text(main, "remote").splitlines():
            for push in (False, True):
                args = ["remote", "get-url"] + (["--push"] if push else []) + ["--all", remote]
                urls.update(_text(main, *args).splitlines())
        if repository["url"] not in urls:
            raise ProjectError("main workspace binding does not match its configured repository URL")
    _instruction_chain(main, required=True)
    return main


def _instruction_chain(directory, *, required=False):
    """Return original applicable AGENTS files from canonical ancestors to root."""
    directory = Path(directory).resolve()
    if not directory.is_dir():
        raise ProjectError("instruction root is not an existing directory: " + str(directory))
    paths = []
    for ancestor in reversed((directory, *directory.parents)):
        path = ancestor / "AGENTS.md"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ProjectError("original instruction must be a regular file: " + str(path))
        if path.is_file():
            try:
                path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise ProjectError("cannot read original instruction: " + str(path)) from exc
            paths.append(path)
    if required and directory / "AGENTS.md" not in paths:
        raise ProjectError("main workspace root requires its original AGENTS.md: " + str(directory))
    return paths


def instruction_files(root, item, project, *, allow_missing_development=False):
    """Return verified original main/code instructions without provisioning code.

    Associated main instructions apply to every operation. Code instructions are
    included when a fixed worktree or program-maintained checkout binding exists;
    abstract management reads never clone a repository to discover instructions.
    Cleanup metadata may explicitly allow an absent recorded worktree after its
    normalized path has been checked; this option does not verify cleanup itself.
    """
    root = Path(root).resolve()
    main = _main_workspace(root, project)
    result = _instruction_chain(main, required=True) if main is not None else []
    if not item.get("repository"):
        return result
    repo = _repository(item, project)
    recorded = item.get("development")
    if recorded:
        base, container = runtime._layout(root, project)
        relative = runtime._worktree_relative(recorded.get("worktree"), container)
        anchor = main if base == "main_workspace" else root
        checkout = runtime._worktree_components(anchor, relative)
        if checkout == root or root in checkout.parents and base == "main_workspace":
            raise ProjectError("code instruction root cannot enter project management paths")
        if allow_missing_development and not checkout.exists():
            recorded = None
    if not recorded:
        value = _bindings(root).get(repo["id"])
        if value is None:
            return result
        selected = Path(value)
        if not selected.is_absolute() or selected.is_symlink() or not selected.is_dir():
            raise ProjectError("local repository instruction binding requires an existing absolute regular directory")
        checkout = selected.resolve()
    if not checkout.is_dir() or Path(_text(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
        raise ProjectError("code instruction root must be the actual checkout root")
    configuration = _configuration(checkout, repo)
    if recorded:
        _existing_record(root, item, project, checkout, configuration)
    for path in _instruction_chain(checkout):
        if path not in result:
            result.append(path)
    return result


def snapshot(worktree):
    """Bind a review to HEAD, index state, and the entire nonignored working tree."""
    worktree = Path(worktree)
    head = _text(worktree, "rev-parse", "--verify", "HEAD^{commit}")
    status = _git(worktree, "status", "--porcelain=v2", "-z", "--untracked-files=all").stdout
    for entry in status.split(b"\0"):
        fields = entry.split(b" ")
        if fields[0] == b"u":
            raise ProjectError("review snapshot requires resolved index conflicts")
        if fields[0] in (b"1", b"2") and fields[2].startswith(b"S") and fields[2][2:] != b"..":
            # known-limit: Git trees bind gitlinks, not uncommitted submodule
            # content; commit/clean those repositories before taking a snapshot.
            raise ProjectError("review snapshot cannot bind uncommitted submodule content")
    # A private index leaves the user's staging area intact, including partial staging.
    with tempfile.TemporaryDirectory(prefix="project-review-index-") as directory:
        env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
        _git(worktree, "read-tree", head, env=env)
        _git(worktree, "add", "-A", "--", ".", env=env)
        tree = _text(worktree, "write-tree", env=env)
    staged = _git(worktree, "diff", "--cached", "--binary", "--no-ext-diff", head).stdout
    digest = hashlib.sha256(status + b"\0" + staged + b"\0" + tree.encode()).hexdigest()
    return {"head": head, "tree": tree, "dirty_digest": digest, "clean": not bool(status)}


def _config(checkout, name):
    result = _git(checkout, "config", "--get", name, check=False)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def _url(checkout, remote, *, push=False):
    args = ["remote", "get-url"] + (["--push"] if push else []) + ["--all", remote]
    result = _git(checkout, *args)
    values = result.stdout.decode().splitlines()
    if len(values) != 1 or not values[0]:
        raise ProjectError(f"remote {remote} requires one unambiguous effective URL; found {len(values)}")
    return values[0]


def _ref(checkout, value):
    if not isinstance(value, str) or not value.startswith("refs/heads/") or _git(checkout, "check-ref-format", value, check=False).returncode:
        raise ProjectError("code repository requires an explicit full refs/heads/ base ref")
    return value


def _publish_url(repo, remote):
    remotes = repo.get("remotes") or {}
    if not isinstance(remotes, dict):
        raise ProjectError("repository.remotes must map remote names to explicit URLs")
    return repo.get("publish_url") or remotes.get(remote)


def _configuration(checkout, repo):
    base_remote = repo.get("base_remote") or _config(checkout, "branch.master.remote")
    base_ref = repo.get("base_ref") or _config(checkout, "branch.master.merge")
    if not base_remote or base_remote == ".":
        raise ProjectError("configure repository.base_remote or branch.master.remote; remote guessing is forbidden")
    base_ref = _ref(checkout, base_ref)
    if _url(checkout, base_remote) != repo["url"]:
        raise ProjectError("base remote URL does not match the configured repository URL")
    publish_remote = repo.get("publish_remote") or base_remote
    publish_url = _publish_url(repo, publish_remote) or repo["url"]
    if _url(checkout, publish_remote, push=True) != publish_url:
        raise ProjectError("publish remote URL does not match the configured publish URL")
    return {"base_remote": base_remote, "base_ref": base_ref, "base_url": repo["url"],
            "publish_remote": publish_remote, "publish_url": publish_url}


def _base(checkout, configuration, identity):
    name = hashlib.sha256(identity.encode()).hexdigest()
    destination = "refs/project-development/" + name + "/base"
    _git(checkout, "fetch", "--no-tags", configuration["base_remote"],
         "+" + configuration["base_ref"] + ":" + destination)
    return _text(checkout, "rev-parse", "--verify", destination + "^{commit}")


def _bindings(root):
    path = root / ".project-local/repositories.yaml"
    runtime._no_links(root, ".project-local/repositories.yaml")
    if not path.exists():
        return {}
    try:
        value = store.load_yaml(path.read_bytes(), str(path))
    except (OSError, store.StoreError) as exc:
        raise ProjectError(str(exc)) from exc
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
        raise ProjectError("local repository bindings must map repository ids to absolute paths")
    return value


def _save_binding(root, repo, checkout):
    bindings = _bindings(root)
    bindings[repo["id"]] = str(checkout.resolve())
    path = root / ".project-local/repositories.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(store.dump_yaml(bindings))
    os.replace(temporary, path)


def _checkout(root, item, project, repo, options):
    recorded = item.get("development")
    if recorded:
        return worktree_location(root, item, project)
    path = options.get("repository_path") or _bindings(root).get(repo["id"])
    managed = not path
    if path:
        checkout = Path(path).expanduser()
        if not checkout.is_absolute():
            raise ProjectError("repository_path must be absolute")
        runtime._worktree_components(Path(checkout.anchor), PurePosixPath(*checkout.parts[1:]))
        if not checkout.is_dir():
            raise ProjectError("repository_path must be an existing Git checkout")
    else:
        runtime._no_links(root, ".project-local/repos/" + repo["id"])
        checkout = root / ".project-local/repos" / repo["id"]
        if not checkout.exists():
            checkout.parent.mkdir(parents=True, exist_ok=True)
            remote = repo.get("base_remote") or repo.get("publish_remote") or "origin"
            _git(root, "clone", "--no-checkout", "--origin", remote, "--", repo["url"], str(checkout))
            # Cloning explicitly selected this remote; no existing checkout is modified.
            if not repo.get("base_remote"):
                _git(checkout, "config", "branch.master.remote", remote)
    top = _text(checkout, "rev-parse", "--show-toplevel")
    if Path(top).resolve() != checkout.resolve():
        raise ProjectError("repository_path must be the code repository root")
    if checkout.resolve() == root:
        raise ProjectError("project management checkout cannot be the code repository")
    if managed:
        # Only program-maintained clones may gain missing declared remotes. An
        # interrupted clone is validated against its base before local repair.
        base_remote = repo.get("base_remote") or _config(checkout, "branch.master.remote")
        if not base_remote or _url(checkout, base_remote) != repo["url"]:
            raise ProjectError("managed clone base remote URL does not match the configured repository URL")
        publish_remote = repo.get("publish_remote") or base_remote
        if publish_remote not in _text(checkout, "remote").splitlines():
            publish_url = _publish_url(repo, publish_remote)
            if not isinstance(publish_url, str) or not publish_url.strip():
                raise ProjectError("missing publish remote requires an explicit repository.publish_url or repository.remotes URL")
            _git(checkout, "remote", "add", "--", publish_remote, publish_url)
    return checkout


def _published_ref(checkout, remote, branch, repo):
    if repo.get("publish_ref_pattern"):
        value = repo["publish_ref_pattern"].format(branch=branch)
        return _ref(checkout, value)
    source = "refs/heads/" + branch
    specs = _text(checkout, "config", "--get-all", "remote." + remote + ".push", check=False).splitlines()
    if not specs:
        return source
    matches = []
    for spec in specs:
        left, separator, right = spec.lstrip("+").partition(":")
        if not separator:
            continue
        if "*" in left and left.count("*") == right.count("*") == 1:
            before, after = left.split("*")
            if source.startswith(before) and source.endswith(after):
                middle = source[len(before):len(source) - len(after) if after else None]
                matches.append(right.replace("*", middle))
        elif source == left:
            matches.append(right)
    if len(matches) != 1:
        raise ProjectError("publish branch must match exactly one configured push refspec")
    return _ref(checkout, matches[0])


def _remote_head(checkout, url, ref):
    rows = _text(checkout, "ls-remote", "--refs", "--", url, ref).splitlines()
    if not rows:
        return None
    if len(rows) != 1 or rows[0].split()[1] != ref:
        raise ProjectError("remote branch identity is ambiguous")
    return rows[0].split()[0]


def _identity(project, item):
    return project["id"] + "/" + item["id"] + "/" + item["repository"]


def _check_identity(checkout, branch, identity):
    if _config(checkout, "branch." + branch + ".project-identity") != identity:
        raise ProjectError("existing branch/worktree has no matching project/item identity; manual recovery required")


def _legacy_original(root, item):
    """Authenticate the observed v1 worktree shape against migration source facts."""
    recorded = item["development"]
    digest = recorded.get("legacy_source_hash")
    if digest is None:
        return None
    name = ".project/migration.yaml"
    runtime._no_links(root, name)
    path = root / name
    if not path.is_file():
        raise ProjectError("legacy development requires its original migration provenance")
    try:
        marker = store.load_yaml(path.read_bytes(), name)
    except (OSError, store.StoreError) as exc:
        raise ProjectError(str(exc)) from exc
    source = f"workitems/{item['id']}/item.json"
    entries = marker.get("legacy_developments") if isinstance(marker, dict) else None
    sources = marker.get("source_sha256") if isinstance(marker, dict) else None
    entry = entries.get(item["id"]) if isinstance(entries, dict) else None
    if (not isinstance(marker, dict) or marker.get("from_schema") != 1 or marker.get("to_schema") != 2 or
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or
            not isinstance(sources, dict) or sources.get(source) != digest or
            not isinstance(entry, dict) or entry.get("source_sha256") != digest or
            not isinstance(entry.get("development"), dict)):
        raise ProjectError("legacy development source hash does not match its v1 migration provenance")
    return entry["development"]


def _existing_record(root, item, project, checkout, configuration):
    """Validate one actual worktree; only authenticated v1 records may omit v2 facts."""
    recorded = item["development"]
    original = _legacy_original(root, item)
    normalized = dict(recorded)
    if original is not None:
        # The migrated multi-infra v1 source stored remote/full-ref in base_ref.
        # This translation is restricted to that authenticated original record.
        legacy_base = configuration["base_remote"] + "/" + configuration["base_ref"]
        for key, value in original.items():
            current = recorded.get(key)
            if key == "base_ref" and value == legacy_base and current == configuration["base_ref"]:
                continue
            if current != value:
                raise ProjectError("legacy development differs from its original migration source: " + key)
    for key, value in configuration.items():
        current = recorded.get(key)
        legacy_ref = key == "base_ref" and current == configuration["base_remote"] + "/" + value
        if current != value and not (original is not None and (key not in recorded or legacy_ref)):
            raise ProjectError("recorded development configuration differs from the actual project repository: " + key)
        normalized[key] = value
    if recorded.get("repository", item["repository"]) != item["repository"]:
        raise ProjectError("recorded development repository identity differs from its work item")
    normalized["repository"] = item["repository"]
    branch = recorded["branch"]
    local_identity = _config(checkout, "branch." + branch + ".project-identity")
    if local_identity != _identity(project, item) and not (original is not None and local_identity is None):
        raise ProjectError("existing branch/worktree has no matching project/item identity; manual recovery required")
    if _text(checkout, "symbolic-ref", "--short", "HEAD") != branch:
        raise ProjectError("recorded development worktree has changed branches")
    base = recorded.get("base_commit")
    if (not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base) or
            _git(checkout, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode):
        raise ProjectError("recorded base_commit is unavailable or no longer an ancestor of the development")
    expected_ref = _published_ref(checkout, configuration["publish_remote"], branch, _repository(item, project))
    if recorded.get("publish_ref") != expected_ref:
        raise ProjectError("recorded publish ref differs from actual remote mapping")
    for key, value in {"remote": configuration["publish_remote"], "merge": expected_ref}.items():
        current = _config(checkout, "branch." + branch + "." + key)
        if current != value and not (original is not None and current is None):
            raise ProjectError("recorded development branch upstream no longer matches its publish mapping")
    return normalized, original is not None


def _reservation(root, identity, branch, relative, configuration):
    name = hashlib.sha256(identity.encode()).hexdigest()
    relative_path = ".project-local/development/" + name + ".yaml"
    runtime._no_links(root, relative_path)
    path = root / relative_path
    if path.exists():
        try:
            record = store.load_yaml(path.read_bytes(), str(path))
        except (OSError, store.StoreError) as exc:
            raise ProjectError(str(exc)) from exc
        if not isinstance(record, dict) or record.get("identity") != identity or record.get("configuration") != configuration:
            raise ProjectError("development reservation identity/configuration differs; manual recovery required")
        return record
    record = {"identity": identity, "branch": branch, "worktree": relative, "configuration": configuration}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation ensures a competing local caller cannot replace the reservation.
    try:
        with path.open("x") as stream:
            stream.write(store.dump_yaml(record))
    except FileExistsError as exc:
        raise ProjectError("development reservation changed concurrently; retry from published ownership") from exc
    return record


def prepare(root, item, project, *, options=None):
    """Create or reuse one worktree after the workflow has published ownership."""
    root, options = Path(root).resolve(), options or {}
    _main_workspace(root, project)
    repo = _repository(item, project)
    if not runtime._identifier(repo["id"]):
        raise ProjectError("repository id must be a safe identifier")
    identity = _identity(project, item)
    checkout = _checkout(root, item, project, repo, options)
    configuration = _configuration(checkout, repo)
    if not item.get("development"):
        _save_binding(root, repo, checkout)
    if options.get("base_ref", configuration["base_ref"]) != configuration["base_ref"]:
        raise ProjectError("requested base_ref differs from project repository configuration")
    existing = item.get("development")
    if existing:
        branch = existing["branch"]
        normalized, legacy = _existing_record(root, item, project, checkout, configuration)
        expected_ref = normalized["publish_ref"]
        remote_head = _remote_head(checkout, configuration["publish_url"], expected_ref)
        if not remote_head:
            raise ProjectError("recorded published development branch is missing")
        _git(checkout, "fetch", "--no-tags", configuration["publish_url"], expected_ref)
        if _git(checkout, "merge-base", "--is-ancestor", remote_head, "HEAD", check=False).returncode:
            raise ProjectError("recorded published development branch has diverged")
        if legacy:
            # Ownership has already been published by the caller. These are local
            # coordination facts only; code/index and existing remote refs stay intact.
            values = {"project-identity": identity, "project-base-commit": existing["base_commit"],
                      "project-configuration": json.dumps(configuration, sort_keys=True),
                      "remote": configuration["publish_remote"], "merge": expected_ref}
            for key, value in values.items():
                if _config(checkout, "branch." + branch + "." + key) != value:
                    _git(checkout, "config", "branch." + branch + "." + key, value)
        return normalized
    owner = item.get("owner") or {}
    suffix = hashlib.sha256((owner.get("token") or owner.get("session") or identity).encode()).hexdigest()[:12]
    branch = options.get("branch") or repo.get("branch_pattern", "feature/{project}/{item}-{session}").format(
        project=project["id"], item=item["id"], session=suffix)
    _ref(checkout, "refs/heads/" + branch)
    base_name, container = runtime._layout(root, project)
    relative = options.get("worktree") or (container / item["id"]).as_posix()
    reserved = _reservation(root, identity, branch, str(relative), configuration)
    if (options.get("branch") and options["branch"] != reserved["branch"]) or (options.get("worktree") and options["worktree"] != reserved["worktree"]):
        raise ProjectError("requested branch/worktree differs from existing development reservation")
    branch = reserved["branch"]
    _ref(checkout, "refs/heads/" + branch)
    relative = runtime._worktree_relative(reserved["worktree"], container)
    location = runtime._resolve_worktree(root, project, base_name, relative)
    if location.resolve() == checkout.resolve():
        raise ProjectError("development worktree must be separate from the existing checkout")
    published_ref = _published_ref(checkout, configuration["publish_remote"], branch, repo)
    remote_head = _remote_head(checkout, configuration["publish_url"], published_ref)
    local = _git(checkout, "show-ref", "--verify", "refs/heads/" + branch, check=False).returncode == 0
    if local or location.exists() or remote_head:
        _check_identity(checkout, branch, identity)
        saved_base = _config(checkout, "branch." + branch + ".project-base-commit")
        saved_configuration = _config(checkout, "branch." + branch + ".project-configuration")
        if saved_configuration != json.dumps(configuration, sort_keys=True) or not saved_base:
            raise ProjectError("interrupted development configuration requires manual recovery")
        base_commit = saved_base
        if not local:
            raise ProjectError("remote branch exists without its original local branch; manual recovery required")
        if not location.exists() or _text(location, "symbolic-ref", "--short", "HEAD") != branch:
            raise ProjectError("existing branch is not at the deterministic worktree; manual recovery required")
        if _text(location, "rev-parse", "--path-format=absolute", "--git-common-dir") != _text(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ProjectError("existing worktree belongs to a different repository")
    else:
        base_commit = _base(checkout, configuration, identity)
        location.parent.mkdir(parents=True, exist_ok=True)
        _git(checkout, "worktree", "add", "-b", branch, str(location), base_commit)
        for key, value in {"project-identity": identity, "project-base-commit": base_commit,
                           "project-configuration": json.dumps(configuration, sort_keys=True)}.items():
            _git(checkout, "config", "branch." + branch + "." + key, value)
    if _git(checkout, "merge-base", "--is-ancestor", base_commit, branch, check=False).returncode:
        raise ProjectError("reserved base_commit is no longer an ancestor of the development branch")
    if remote_head:
        _git(checkout, "fetch", "--no-tags", configuration["publish_url"], published_ref)
        if _git(checkout, "merge-base", "--is-ancestor", remote_head, branch, check=False).returncode:
            raise ProjectError("published branch has diverged; remote updates are forbidden")
    else:
        # known-limit: published item ownership plus a session-derived reservation
        # excludes protocol participants. Direct Git writers require server-side
        # create-only policy for strict CAS; post-push verification detects divergence.
        _git(checkout, "push", "--set-upstream", configuration["publish_remote"], "refs/heads/" + branch + ":" + published_ref)
        if _remote_head(checkout, configuration["publish_url"], published_ref) != _text(checkout, "rev-parse", branch):
            raise ProjectError("published branch changed concurrently; reservation retained for recovery")
    _git(checkout, "config", "branch." + branch + ".remote", configuration["publish_remote"])
    _git(checkout, "config", "branch." + branch + ".merge", published_ref)
    return {"repository": repo["id"], "worktree": relative.as_posix(), "branch": branch,
            "base_commit": base_commit, "publish_ref": published_ref, **configuration}


def verify_merged(root, item, project, *, evidence=None):
    """Verify reviewed source content is committed and reachable from the live target."""
    evidence = evidence or {}
    if not isinstance(evidence, dict):
        raise ProjectError("merge evidence must be an object")
    repo = _repository(item, project)
    development = item.get("development") or {}
    checkout = worktree_location(root, item, project)
    configuration = _configuration(checkout, repo)
    _existing_record(Path(root).resolve(), item, project, checkout, configuration)
    reviewed = development.get("reviewed_snapshot")
    if not isinstance(reviewed, dict) or not all(reviewed.get(key) for key in ("head", "tree", "dirty_digest")):
        raise ProjectError("merge verification requires the implementation's independently reviewed snapshot")
    source = evidence.get("source_commit") or evidence.get("commit") or reviewed["head"]
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source):
        raise ProjectError("delivery requires a full source commit id")
    target = _base(checkout, configuration, _identity(project, item))
    source = _text(checkout, "rev-parse", "--verify", source + "^{commit}")
    if _text(checkout, "rev-parse", source + "^{tree}") != reviewed["tree"]:
        raise ProjectError("source commit does not contain the reviewed implementation tree; supply its committed snapshot mapping")
    if source == development.get("base_commit"):
        raise ProjectError("baseline HEAD alone cannot establish implementation delivery")
    if _git(checkout, "merge-base", "--is-ancestor", source, target, check=False).returncode:
        raise ProjectError("reviewed source is not an ancestor of the current target; squash/cherry-pick needs explicit reviewed commit mapping")
    return {"verified": True, "kind": "merged", "reference": target, "source_commit": source,
            "reviewed_snapshot": dict(reviewed), **configuration}
