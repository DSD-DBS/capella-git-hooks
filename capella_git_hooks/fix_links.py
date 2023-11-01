# Copyright DB Netz AG and contributors
# SPDX-License-Identifier: Apache-2.0
"""A script which fixes wrong links with an index:/ prefix.

See https://github.com/eclipse/capella/issues/2725 for more information.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from capellambse.loader import exs
from lxml import etree as ET

DIAGRAM_OVERVIEW_TAG = "{http://www.eclipse.org/sirius/1.1.0}DAnalysis"

# pylint: disable=line-too-long
prefix_pattern = r"(commit:/|index:/)"
reference_pattern = re.compile(
    r"(#[0-9a-f]{8}\b-[0-9a-f]{4}\b-[0-9a-f]{4}\b-[0-9a-f]{4}\b-[0-9a-f]{12}|#_[0-9a-zA-Z_-]{22})"
)
root_pattern = re.compile(rf"{prefix_pattern}.*\.(capella|aird)")
root_reference_pattern = re.compile(
    f"{root_pattern.pattern}{reference_pattern.pattern}"
)

fragment_pattern = re.compile(
    rf"{prefix_pattern}fragments/.*\.(capella|aird)fragment"
)
fragment_reference_pattern = re.compile(
    f"{fragment_pattern.pattern}{reference_pattern.pattern}"
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


def search_and_replace(
    pattern: re.Pattern, value: str, replacement: str
) -> str | None:
    """Return the patched value or the unpatched value."""
    while match := pattern.search(value):
        index_match = match.span(1)
        value = value[: index_match[0]] + replacement + value[index_match[1] :]
    return value


def fix_semantic_resources(
    root: ET._Element, root_repl: str, fragment_repl: str
) -> bool:
    """Patch the semantic resource file paths and return a bool."""
    changed = False
    danalysis = next(root.iterchildren(DIAGRAM_OVERVIEW_TAG))
    for resource in danalysis.iterchildren("semanticResources"):
        if resource.text is None:
            continue

        text = search_and_replace(
            fragment_pattern, resource.text, fragment_repl
        )
        text = search_and_replace(root_pattern, resource.text, root_repl)
        if resource.text != text:
            resource.text = text
            changed = True
    return changed


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

    try:
        changed = fix_semantic_resources(
            root, root_replacement, fragment_replacement
        )
    except StopIteration:
        pass

    for elem in root.iter():
        for key, value in list(elem.attrib.items()):
            if value is None:
                continue

            new_value = search_and_replace(
                root_reference_pattern, value, root_replacement
            )
            new_value = search_and_replace(
                fragment_reference_pattern, value, fragment_replacement
            )
            if value != new_value:
                elem.attrib[key] = new_value
                changed = True

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

    # if changed_files:
    #     commit_changes(changed_files)


if __name__ == "__main__":
    main()
