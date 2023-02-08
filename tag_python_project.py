"""Create a git tag from python project version"""
__version__ = "0.1.0"

from typing import Any

from collections.abc import Iterable

import git
import click
import importlib
import sys
import os
import github
import re


RE_CONVENTIONAL_COMMIT = re.compile(
    '(?:(?P<type>\\w*)\\((?P<scope>\\w*)\\)?(?P<br>!)?:'
    ' (?P<description>.*)(?:\n\n)?(?P<body>.*)?(?:\n\n)?(?P<foot>.*))',
)


def format_commits(commits: Iterable[str]) -> str:
    return "\n".join(map(lambda x: f'* {x}', commits))


def is_breaking_change(match: dict[str, Any]) -> bool:
    return (
        bool(match['br'])
        or (
            match['body'].startswith('BREAKING CHANGE:') and not bool(match['foot'])
        )
        or match['foot'].startswith('BREAKING CHANGE:')
    )


@click.command()
@click.argument('module-name')
@click.option('-f', '--folder', default='.')
@click.option('-r', '--repo', 'repo_name', default='')
@click.option('-d', '--draft', default=False, is_flag=True)
@click.option('-p', '--pre-release', default=False, is_flag=True)
def cli(module_name: str, folder: str, repo_name: str, draft: bool, pre_release: bool):
    if os.path.realpath(folder) not in sys.path:
        sys.path.append(folder)
    module = importlib.import_module(module_name)

    if not hasattr(module, '__version__'):
        raise Exception()

    version = module.__version__
    if not version.startswith('v'):
        version = f'v{version}'

    repo = git.Repo(folder)
    repo.git.fetch(all=True)
    tags = sorted(repo.tags, key=lambda x: x.name, reverse=True)
    if not tags:
        origin_rev, *_ = map(lambda x: x.hexsha, repo.iter_commits(None, max_parents=0))
    elif version in map(lambda tag: tag.name, tags):
        raise click.exceptions.ClickException(f"Tag for version {version} already exist")
    else:
        origin_rev, *_ = map(lambda x: x.commit, tags)

    changelog_dict: dict[str, list[str]] = {}
    global_breaking_change = False
    target_rev = repo.active_branch.commit
    for commit in repo.iter_commits(
        f'{origin_rev}...{target_rev}', no_merges=True,
    ):
        msg = commit.message.strip()
        match = RE_CONVENTIONAL_COMMIT.match(msg)

        if not match:
            message, *_ = msg.split('\n')
            changelog_dict.setdefault('others', []).append(message)
            continue

        parsed_commit = match.groupdict()
        breaking_change = is_breaking_change(parsed_commit)
        breaking = "Breaking " * breaking_change
        over = f' over {parsed_commit["scope"]}' * bool(parsed_commit['scope'])
        changelog_dict.setdefault(
            parsed_commit['type'], [],
        ).append(
            f"{breaking}Changes{over}: {parsed_commit['description']}",
        )
        global_breaking_change |= breaking_change

    br_changes_info = '\n\n> WARNING: BREAKING CHANGES !' * global_breaking_change
    changelog = "\n".join([
        (
            f"Version {version.removeprefix('v')}"
            f"{br_changes_info}"
        ),
        "\n## Change Log",
        *[
            (
                f"### {type_.title()}"
                "\n"
                f"{format_commits(msgs)}"
            )
            for type_, msgs in changelog_dict.items()
        ],
    ])
    gh = github.Github(os.environ['GITHUB_TOKEN'])
    gh_repo = os.environ.get('GITHUB_REPOSITORY', repo_name)
    r = gh.get_repo(gh_repo)

    r.create_git_tag_and_release(
        version,
        f"Tag for version {version}",
        version,
        changelog,
        str(target_rev),
        "commit",
        tagger=github.GithubObject.NotSet,
        draft=draft,
        prerelease=pre_release,
    )
