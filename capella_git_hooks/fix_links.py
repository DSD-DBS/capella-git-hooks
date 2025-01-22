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
import enum
import logging
import os
import pathlib
import subprocess
import textwrap
import typing as t
import urllib.parse

import click
from capellambse import filehandler, helpers, loader
from lxml import etree

LOGGER = logging.getLogger(__name__)


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
@click.option("--fix", is_flag=True, help="Fix the model(s) if possible")
@click.option("--no-commit", is_flag=True, help="Do not commit fixed models")
@click.option(
    "-m",
    "--commit-message",
    # FIXME This isn't conventional-commits compliant, and might fail checks
    default="fix[by-script]: merge tool index-prefix",
    help="Commit message to use when committing fixed models",
)
def main(
    models: cabc.Sequence[str],
    fix: bool,
    no_commit: bool,
    commit_message: str,
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

    any_broken = False
    changes = False
    for modelfile in find_tracked_models(models):
        LOGGER.info("Loading model %s", modelfile)
        model = loader.MelodyLoader(modelfile)
        result = fix_model(model)

        match result:
            case ModelFixResult.NO_CHANGES:
                LOGGER.info("Model is clean, not saving: %s", modelfile)
            case ModelFixResult.FIXED:
                LOGGER.info("Model was fixed: %s", modelfile)
                changes = True
            case ModelFixResult.PARTIALLY_FIXED:
                LOGGER.info("Model was partially fixed: %s", modelfile)
                changes = any_broken = True
            case ModelFixResult.BROKEN:
                LOGGER.info("No fixes available for model: %s", modelfile)
                any_broken = True
            case _:
                raise AssertionError("non-exhaustive match")

        if result in (ModelFixResult.FIXED, ModelFixResult.PARTIALLY_FIXED):
            if fix:
                changes = True
                LOGGER.info("Saving changes to %s", modelfile)
                if not no_commit:
                    model.resources["\0"] = _IndexWriter()
                model.save()
            else:
                LOGGER.info("Not saving model without --fix")

    if changes:
        if not fix:
            LOGGER.info("Not committing changes without --fix")
        elif no_commit:
            LOGGER.info("Not committing changes (--no-commit)")
        else:
            LOGGER.info("Committing changes")
            subprocess.call(
                ["git", "commit", "-m", commit_message],
                env=os.environ | {"SKIP": "fix-capella-fragment-links"},
            )

    if any_broken:
        status = 2
        text = """\
            \x1b[91m********************************************************************************\x1b[m

            The model is broken, in a way we can't fix automatically!
            Please contact your tools team to get assistance in repairing it.

            \x1b[91m********************************************************************************\x1b[m
            """
    elif changes:
        status = 1
        text = """\
            \x1b[93m********************************************************************************\x1b[m

            The model was broken, but some automatic fixes have been applied.
            Please verify that these changes are correct before pushing them.
            Contact your tools team if you need further assistance.

            \x1b[93m********************************************************************************\x1b[m
            """
    else:
        status = 0
        text = """\
            \x1b[92m********************************************************************************\x1b[m

            It looks like your model is fine!

            \x1b[92m********************************************************************************\x1b[m
            """

    click.echo("\n" + textwrap.dedent(text).strip(), err=True)
    raise SystemExit(status)


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


def fix_model(model: loader.MelodyLoader) -> ModelFixResult:
    """Fix the links in the provided model."""
    dirty = False
    broken = False
    marked_for_deletion: list[etree._Element] = []
    for element in model.iterall():
        try:
            sourcefrag = model.find_fragment(element)
        except ValueError:
            continue

        if element.tag == "semanticResources":
            if not element.text:
                marked_for_deletion.append(element)
                continue

            targetfrag = urllib.parse.unquote(element.text.rsplit("/", 1)[-1])
            frags = [i for i in model.trees if i.name == targetfrag]
            if len(frags) != 1:
                raise RuntimeError(
                    f"Ambiguous fragment name: {element.text}"
                    " - please report this as bug at"
                    " https://github.com/DSD-DBS/capella-git-hooks"
                )

            if sourcefrag == frags[0]:
                marked_for_deletion.append(element)
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
                start, _, target_id = link.partition("#")
                try:
                    target = model.follow_link(None, target_id)
                except KeyError:
                    if (
                        element.tag == "ownedRepresentationDescriptors"
                        and start.startswith("cdo://")
                    ):
                        ft = model.trees[sourcefrag].fragment_type
                        if ft == loader.FragmentType.VISUAL:
                            marked_for_deletion.append(element)
                            continue
                    else:
                        LOGGER.error(
                            "Cannot repair dangling link: #%s", target_id
                        )
                        broken = True
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

    for element in marked_for_deletion:
        element.getparent().remove(element)

    match (dirty, broken):
        case (False, False):
            return ModelFixResult.NO_CHANGES
        case (False, True):
            return ModelFixResult.BROKEN
        case (True, False):
            return ModelFixResult.FIXED
        case (True, True):
            return ModelFixResult.PARTIALLY_FIXED
        case _:
            raise AssertionError("invalid match/case")


class ModelFixResult(enum.Enum):
    NO_CHANGES = enum.auto()
    """The model was fine, no changes were made."""
    FIXED = enum.auto()
    """Fixes were applied to the model, and it's fine now."""
    PARTIALLY_FIXED = enum.auto()
    """Some issues were fixed, but the model is still broken."""
    BROKEN = enum.auto()
    """No fixes were applied, and the model is broken."""


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
