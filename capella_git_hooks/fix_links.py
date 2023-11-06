# Copyright DB Netz AG and contributors
# SPDX-License-Identifier: Apache-2.0
"""A script which fixes broken links within Capella models.

This is intended to fix the issue where the merge tool adds an
``index:/`` or similar prefix to links within Capella models. See
`eclipse/capella#2725`__ for more information.

__ https://github.com/eclipse/capella/issues/2725
"""

from __future__ import annotations

import collections.abc as cabc
import logging
import os
import pathlib
import subprocess
import typing as t
import urllib.parse

import click
from capellambse import filehandler, helpers, loader

LOGGER = logging.getLogger(__name__)
# FIXME This isn't conventional-commits compliant, and might fail checks
COMMIT_MSG = "fix[by-script]: merge tool index-prefix"


@click.command()
@click.option(
    "-m",
    "--model",
    "models",
    help=(
        "Path to a Capella model to fix."
        " If not given, run on all tracked models."
        " Can be specified multiple times."
    ),
    multiple=True,
)
@click.option("--no-commit", is_flag=True, help="Do not commit changes.")
def main(
    models: cabc.Sequence[str],
    no_commit: bool,
):
    """Fix links in all tracked Capella models."""
    logging.basicConfig(level="INFO")

    dirty_files = (
        subprocess.check_output(
            ["git", "diff", "--name-only", "-z"], text=True
        )
        .rstrip("\0")
        .split("\0")
    )
    if dirty_files != [""]:
        LOGGER.error(
            "Worktree is dirty, commit or stash changes and try again: %s",
            dirty_files,
        )
        raise SystemExit(1)

    changes = False
    for modelfile in find_tracked_models(models):
        LOGGER.info("Loading model %s", modelfile)
        model = loader.MelodyLoader(modelfile)
        dirty = fix_model(model)
        if dirty:
            LOGGER.info("Saving changes to %s", modelfile)
            model.resources["\0"] = _IndexWriter()
            model.save()
            changes = True
        else:
            LOGGER.info("Model is clean, not saving: %s", modelfile)

    if changes:
        if no_commit:
            LOGGER.info("Not committing changes (--no-commit)")
        else:
            LOGGER.info("Committing changes")
            subprocess.call(
                ["git", "commit", "-m", COMMIT_MSG],
                env=os.environ | {"SKIP": "fix-capella-fragment-links"},
            )


def find_tracked_models(models: cabc.Sequence[str]) -> cabc.Iterable[str]:
    """Find all tracked models in the current Git repository.

    If a list of models is provided, filter the result to only include
    those models.

    This function always returns paths relative to the current working
    directory. Any provided models that live outside of the CWD are
    ignored.
    """
    if not models:
        filter: cabc.Container = EverythingContainer()
    else:
        filter = [os.path.relpath(m) for m in models]

    for file in subprocess.check_output(
        ["git", "ls-files", "-cz"], text=True
    ).split("\0"):
        if file.endswith(".aird") and file in filter:
            yield file


def is_file_dirty(path: pathlib.PurePosixPath) -> bool:
    """Check if the given file is dirty (worktree != index)."""
    p = subprocess.run(
        ["git", "diff-index", "--quiet", "--", path],
        check=False,
    )
    return p.returncode != 0


def fix_model(model: loader.MelodyLoader) -> bool:
    """Fix the links in the provided model.

    Returns
    -------
    bool
        True if the model was modified, False otherwise.
    """
    dirty = False
    for element in model.iterall():
        if element.tag == "semanticResources":
            if element.text == "":
                element.getparent().remove(element)
                continue

            targetfrag = urllib.parse.unquote(element.text.rsplit("/", 1)[-1])
            frags = [i for i in model.trees if i.name == targetfrag]
            if len(frags) != 1:
                raise RuntimeError(
                    f"Ambiguous fragment name: {element.text}"
                    " - please report this as bug at"
                    " https://github.com/DSD-DBS/capella-git-hooks"
                )

            sourcefrag = model.find_fragment(element)
            if sourcefrag == frags[0]:
                element.getparent().remove(element)
                continue

            link = os.path.relpath(frags[0], sourcefrag.parent)
            link = urllib.parse.quote(link)
            if link != element.text:
                element.text = link
                dirty = True

        for attr, value in element.attrib.items():
            if attr == "href":
                include_target_type = False
            else:
                include_target_type = None

            try:
                links = tuple(helpers.split_links(value))
            except ValueError:
                continue

            new_links: list[str] = []
            for link in links:
                _, _, target_id = link.partition("#")
                try:
                    target = model.follow_link(None, target_id)
                except KeyError:
                    LOGGER.error("Cannot repair dangling link: #%s", target_id)
                else:
                    link = model.create_link(
                        element,
                        target,
                        include_target_type=include_target_type,
                    )
                new_links.append(link)

            new_value = " ".join(new_links)
            if new_value != value.strip():
                element.attrib[attr] = new_value
                dirty = True

    return dirty


class EverythingContainer(cabc.Container):
    """A container that returns True for any key."""

    def __contains__(self, key: object) -> bool:
        """Return True."""
        return True


class _IndexWriter(filehandler.abc.FileHandler):
    """A file handler that writes to the worktree and the git index."""

    def __init__(self) -> None:
        super().__init__("index:")

    def open(
        self,
        filename: str | pathlib.PurePosixPath,
        mode: t.Literal["r", "rb", "w", "wb"] = "rb",
    ) -> t.BinaryIO:
        if "w" not in mode:
            raise ValueError("IndexWriter can only be used for writing")

        path = helpers.normalize_pure_path(filename, base=self.subdir)
        return _IndexFile(path)  # type: ignore[abstract]


class _IndexFile(t.BinaryIO):
    def __init__(self, path: pathlib.PurePosixPath) -> None:
        # pylint: disable=consider-using-with
        self.__path = path
        self.__file = open(path, "wb")
        self.__is_open = True

    @property
    def closed(self) -> bool:
        return not self.__is_open

    def __enter__(self) -> _IndexFile:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        if self.__is_open:
            import warnings

            warnings.warn(
                "IndexFile should be closed explicitly", ResourceWarning
            )
            self.close()

    def close(self) -> None:
        self.__file.close()
        self.__is_open = False
        subprocess.check_call(["git", "add", self.__path])

    def write(self, s: bytes) -> int:  # type: ignore[override]
        return self.__file.write(s)


if __name__ == "__main__":
    main()
