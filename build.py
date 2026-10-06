# Copyright (C) 2023 Wildfire Games.
# This file is part of 0 A.D.
# SPDX-License-Identifier: GPL-2.0-or-later

import glob
import os

try:
    import tomllib
except ModuleNotFoundError:
    import pip._vendor.tomli as tomllib

import zipfile

PACKAGE = "io_import_0ad_actor"


def get_version():
    with open(PACKAGE + "/blender_manifest.toml", "rb") as f:
        manifest = tomllib.load(f)
        return manifest["version"]


def build_archive():
    os.makedirs("dist", exist_ok=True)
    with zipfile.ZipFile(
        os.path.join("dist", PACKAGE + "-" + get_version() + ".zip"), mode="w"
    ) as archive:
        for path in sorted(glob.glob(PACKAGE + "/*.py")):
            archive.write(path)
        archive.write(PACKAGE + "/blender_manifest.toml")
        archive.write("LICENSE", arcname=PACKAGE + "/LICENSE")


if __name__ == "__main__":
    build_archive()
