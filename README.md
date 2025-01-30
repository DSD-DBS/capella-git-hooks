<!--
 ~ Copyright DB InfraGO AG and contributors
 ~ SPDX-License-Identifier: Apache-2.0
 -->

# Capella Git Hooks

![image](https://github.com/DSD-DBS/capella-git-hooks/actions/workflows/build-test-publish.yml/badge.svg)
![image](https://github.com/DSD-DBS/capella-git-hooks/actions/workflows/lint.yml/badge.svg)

In this repository we provide git hooks, which can be useful when using git for
storing Capella models. All hooks are designed to be included using the
[pre-commit framework](https://pre-commit.com/). To include git a git hook from
this repository, you have to add a `.pre-commit-config.yaml` file to the root
of your repository. In this file you have to reference this repository to use
hooks from here:

```yaml
repos:
  - repo: https://github.com/DSD-DBS/capella-git-hooks.git
    rev: 862cf641c298f9666656b46b1bde3639c7592b01
    hooks:
      - id: ...
```

# Available Hooks

In the following we will shortly summarize the available hooks and how to
include them.

## fix-links

This post-commit hook is a workaround, which checks all files for broken links
starting with `index:/`. These can occur after using the merge tool as
described in this [issue](https://github.com/eclipse/capella/issues/2725). The
general process looks as follows:

1. Get all git tracked files not having uncommitted changes (as it is a
   post-commit hook, this includes changes committed in the triggering git
   command)
2. Search and replace `index:/` in all XML attributes - we ensure that the
   XML-structure does not change
3. If files were changed, these are written to disk and committed in a separate
   commit using a predefined commit message ("fix[by-script]: merge tool
   index-prefix")

To use this hook, add `fix-capella-fragment-links` to the list of hooks in your
`.pre-commit-config.yaml`.

```yaml
repos:
  - repo: https://github.com/DSD-DBS/capella-git-hooks.git
    rev: 862cf641c298f9666656b46b1bde3639c7592b01
    hooks:
      - id: fix-capella-fragment-links
```

# Setting up a Development Environment

To set up a development environment, clone the project and install it into a
virtual environment.

```sh
git clone https://github.com/DSD-DBS/capella-git-hooks
cd capella-git-hooks
python -m venv .venv

source .venv/bin/activate.sh  # for Linux / Mac
.venv\Scripts\activate  # for Windows

pip install -U pip pre-commit
pip install -e '.[docs,test]'
pre-commit install
```

# Contributing

We'd love to see your bug reports and improvement suggestions! Please take a
look at our [guidelines for contributors](CONTRIBUTING.md) for details.

# Licenses

This project is compliant with the
[REUSE Specification Version 3.0](https://git.fsfe.org/reuse/docs/src/commit/d173a27231a36e1a2a3af07421f5e557ae0fec46/spec.md).

Copyright DB InfraGO AG, licensed under Apache 2.0 (see full text in
[LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt))

Dot-files are licensed under CC0-1.0 (see full text in
[LICENSES/CC0-1.0.txt](LICENSES/CC0-1.0.txt))
