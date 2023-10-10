# Copyright DB Netz AG and contributors
# SPDX-License-Identifier: Apache-2.0
"""A script which fixes wrong links with an index:/ prefix.

See https://github.com/eclipse/capella/issues/2725 for more information.
"""
import os
import re
import subprocess
import sys

from capellambse.loader import exs
from lxml import etree as ET

# pylint: disable=line-too-long
root_pattern = re.compile(
    r"(index:/).*\.(capella|aird)#[0-9a-f]{8}\b-[0-9a-f]{4}\b-[0-9a-f]{4}\b-[0-9a-f]{4}\b-[0-9a-f]{12}"
)
fragment_pattern = re.compile(
    r"(index:/fragments/).*\.(capella|aird)fragment#[0-9a-f]{8}\b-[0-9a-f]{4}\b-[0-9a-f]{4}\b-[0-9a-f]{4}\b-[0-9a-f]{12}"
)
file_name_pattern = re.compile(r".*\.(capella|aird)(fragment)?")


def get_unmodified_tracked_files() -> list[str]:
    """Return a list of git tracked files not having uncommitted changes."""
    repo_path = os.getcwd()
    try:
        modified_files = subprocess.check_output(
            ["git", "diff", "--name-only"], cwd=repo_path, text=True
        ).splitlines()
        all_tracked_files = subprocess.check_output(
            ["git", "ls-files"], cwd=repo_path, text=True
        ).splitlines()
        unmodified_tracked_files = [
            file for file in all_tracked_files if file not in modified_files
        ]

        return unmodified_tracked_files
    except subprocess.CalledProcessError as e:
        # Handle any Git command errors
        print("Git command error:", e)
        return []


def fix_xml(path: str) -> bool:
    """Fix the XML located in the provided path and write changes to disk."""
    is_fragment = path.startswith("fragments/")
    assert is_fragment or "/" not in path
    if path.endswith(".capella") or path.endswith(".capellafragment"):
        line_length = exs.LINE_LENGTH
    else:
        line_length = sys.maxsize

    changed = False

    tree = ET.parse(path)
    root = tree.getroot()

    root_replacement = "../" if is_fragment else ""
    fragment_replacement = "" if is_fragment else "fragments/"

    for elem in root.iter():
        for key, value in list(elem.attrib.items()):
            # Use the regex pattern to find and replace attribute values
            while match := root_pattern.search(value):
                changed = True
                index_match = match.span(1)
                value = (
                    value[: index_match[0]]
                    + root_replacement
                    + value[index_match[1] :]
                )

            while match := fragment_pattern.search(value):
                changed = True
                index_match = match.span(1)
                value = (
                    value[: index_match[0]]
                    + fragment_replacement
                    + value[index_match[1] :]
                )

            elem.attrib[key] = value

    if changed:
        exs.write(tree, path, line_length=line_length, siblings=True)

    return changed


def commit_changes(changed_files_to_be_committed: list[str]):
    """Add and commit the provided list of files using a predefined message."""
    subprocess.call(["git", "add"] + changed_files_to_be_committed)
    subprocess.call(
        ["git", "commit", "-m", "fix[by-script]: merge tool index-prefix"]
    )


def main():
    """Fix links in all tracked, unchanged files and commit the changes."""
    tracked_unmodified_files = get_unmodified_tracked_files()
    changed_files = []
    for file in tracked_unmodified_files:
        if file_name_pattern.match(file):
            if fix_xml(file):
                changed_files.append(file)

    if changed_files:
        commit_changes(changed_files)


if __name__ == "__main__":
    main()
