#!/usr/bin/env python3
# Copyright 2019 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the 'License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Python packaging for repo."""

import os

import setuptools


TOPDIR = os.path.dirname(os.path.abspath(__file__))


# Rip out the first intro paragraph.
with open(os.path.join(TOPDIR, "README.md")) as fp:
    lines = fp.read().splitlines()[2:]
    end = lines.index("")
    long_description = " ".join(lines[0:end])


# https://packaging.python.org/tutorials/packaging-projects/
setuptools.setup(
    name="repo",
    version="2",
    maintainer="Various",
    maintainer_email="repo-discuss@googlegroups.com",
    description="Repo helps manage many Git repositories",
    long_description=long_description,
    long_description_content_type="text/plain",
    url="https://gerrit.googlesource.com/git-repo/",
    project_urls={
        "Bug Tracker": "https://issues.gerritcodereview.com/issues?q=is:open%20componentid:1370071",  # noqa: E501
    },
    # https://pypi.org/classifiers/
    classifiers=[
        "Development Status :: 6 - Mature",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows :: Windows 10",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Software Development :: Version Control :: Git",
    ],
    python_requires=">=3.6",
    packages=["subcmds"],
)
