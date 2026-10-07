# SPDX-License-Identifier: GPL-2.0-or-later

"""Lets the add-on be imported outside Blender.

bpy and bpy_extras are replaced by small fakes; mathutils is the real one, from PyPI. The fake
bpy.data only records the objects and meshes created.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeObject:
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.parent = None
        self.matrix_basis = None
        self.empty_display_type = None
        self.empty_display_size = None


class FakeMeshLoop:
    def __init__(self):
        self.uv = None


class FakeUVLayer:
    def __init__(self, name, loops):
        self.name = name
        self.data = [FakeMeshLoop() for _ in range(loops)]


class FakeUVLayers(list):
    def __init__(self, mesh):
        super().__init__()
        self.mesh = mesh

    def new(self, name):
        layer = FakeUVLayer(name, sum(len(f) for f in self.mesh.faces))
        self.append(layer)
        return layer


class FakeMesh:
    def __init__(self, name):
        self.name = name
        self.vertices = []
        self.faces = []
        self.custom_normals = None
        self.uv_layers = FakeUVLayers(self)

    def from_pydata(self, vertices, edges, faces):
        self.vertices = list(vertices)
        self.faces = [list(f) for f in faces]

    def normals_split_custom_set(self, normals):
        self.custom_normals = list(normals)

    def validate(self):
        pass

    def update(self):
        pass


class FakeCollection:
    def __init__(self, cls):
        self.cls = cls
        self.created = []

    def new(self, name, *args):
        item = self.cls(name, *args)
        self.created.append(item)
        return item


class FakeLinkedObjects(list):
    def link(self, obj):
        self.append(obj)


class FakeSceneCollection:
    def __init__(self):
        self.objects = FakeLinkedObjects()


def _fake_bpy():
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(
        Operator=type("Operator", (), {"__init__": lambda self, *a, **k: None}),
        Mesh=FakeMesh,
    )
    bpy.props = types.SimpleNamespace(
        StringProperty=lambda **k: None,
        BoolProperty=lambda **k: None,
        IntProperty=lambda **k: None,
    )
    bpy.data = types.SimpleNamespace()
    bpy_extras = types.ModuleType("bpy_extras")
    bpy_extras.io_utils = types.SimpleNamespace(
        ImportHelper=type("ImportHelper", (), {})
    )
    return bpy, bpy_extras


sys.modules["bpy"], sys.modules["bpy_extras"] = _fake_bpy()


@pytest.fixture
def bpy_data():
    """The fake bpy.data, with empty object and mesh collections."""
    data = sys.modules["bpy"].data
    data.objects = FakeCollection(FakeObject)
    data.meshes = FakeCollection(FakeMesh)
    return data


@pytest.fixture
def collection():
    return FakeSceneCollection()
