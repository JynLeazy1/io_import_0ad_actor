# Copyright (C) 2026 Wildfire Games.
# This file is part of 0 A.D.
# SPDX-License-Identifier: GPL-2.0-or-later

"""Minimal COLLADA (.dae) reader for Pyrogenesis meshes.

Blender 5.0 removed the built-in COLLADA importer, so the .dae files are read by hand. Only what
the game's converter (source/collada/PMDConvert.cpp) uses is supported:
- Static meshes: <triangles>, <polylist> or <polygons> with VERTEX/NORMAL/TEXCOORD, with the
  world matrix of their node applied. Y_UP becomes Blender's Z_UP: (x, y, z) -> (x, -z, y).
- Skinned meshes: the <skin> is deformed on the CPU into its rest pose (or one frame of an
  animation .dae with full 4x4 matrix channels); no armature is created.
- Prop points: nodes named "prop-<name>" or "prop_<name>".
Like the game, <unit> is ignored and only the first set of polygons and UVs is read.
"""

import math
import os
import xml.etree.ElementTree as ET

import bpy
from mathutils import Matrix, Vector

NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}
C = "{http://www.collada.org/2005/11/COLLADASchema}"
Y_UP_TO_Z_UP = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def _mat16(vals):
    v = list(map(float, vals))
    return Matrix([v[0:4], v[4:8], v[8:12], v[12:16]])


def _source(root, sid):
    src = root.find(f".//c:source[@id='{sid.lstrip('#')}']", NS)
    arr = src.find("c:float_array", NS)
    if arr is not None:
        return list(map(float, arr.text.split()))
    names = src.find("c:Name_array", NS)
    if names is None:
        names = src.find("c:IDREF_array", NS)
    return names.text.split()


def _up_matrix(root):
    up = root.find("c:asset/c:up_axis", NS)
    return (
        Y_UP_TO_Z_UP
        if (up is None or up.text.strip() == "Y_UP")
        else Matrix.Identity(4)
    )


def _local_matrix(node):
    """Composes the node's <matrix>, <translate>, <rotate> and <scale> in document order."""
    m = Matrix.Identity(4)
    for t in node:
        if t.tag not in (C + "matrix", C + "translate", C + "rotate", C + "scale"):
            continue
        v = list(map(float, t.text.split()))
        if t.tag == C + "matrix":
            m = m @ _mat16(v)
        elif t.tag == C + "translate":
            m = m @ Matrix.Translation(v)
        elif t.tag == C + "rotate":
            m = m @ Matrix.Rotation(math.radians(v[3]), 4, Vector(v[:3]))
        else:
            m = m @ Matrix.Diagonal(Vector((*v, 1)))
    return m


def _nodes(root):
    """{key: (parent key, local matrix, id, sid, element)} of the visual scene.

    The key is the node name; nodes without one use their id, and repeated names get a suffix
    (a node keyed like its own ancestor would make _world recurse forever).
    """
    out = {}

    def walk(el, parent):
        for n in el.findall("c:node", NS):
            name = n.get("name") or n.get("id") or f"node.{len(out)}"
            if name in out:
                name = f"{name}.{len(out)}"
            out[name] = (parent, _local_matrix(n), n.get("id"), n.get("sid"), n)
            walk(n, name)

    walk(root.find(".//c:visual_scene", NS), None)
    return out


def _is_prop(name):
    """Prop points start with "prop-" (people) or "prop_" (horses, camels), like PMDConvert.cpp."""
    return name.startswith(("prop-", "prop_"))


def _world(nodes, name, locals_, cache):
    if name not in cache:
        parent = nodes[name][0]
        m = locals_.get(name, nodes[name][1])
        cache[name] = (_world(nodes, parent, locals_, cache) @ m) if parent else m
    return cache[name]


def _triangles(root, geom):
    mesh = geom.find("c:mesh", NS)
    prim = mesh.find("c:triangles", NS)
    if prim is None:
        prim = mesh.find("c:polylist", NS)
    if prim is None:
        prim = mesh.find("c:polygons", NS)  # one <p> per polygon
    inputs = prim.findall("c:input", NS)
    stride = max(int(i.get("offset")) for i in inputs) + 1
    off, srcs = {}, {}
    for i in inputs:
        sem = i.get("semantic")
        if sem in off:
            continue  # first UV set only
        off[sem] = int(i.get("offset"))
        srcs[sem] = i.get("source")
    vsrc = mesh.find(
        f"c:vertices[@id='{srcs['VERTEX'].lstrip('#')}']/c:input[@semantic='POSITION']",
        NS,
    ).get("source")
    P = _source(root, vsrc)
    N = _source(root, srcs["NORMAL"]) if "NORMAL" in srcs else None
    T = _source(root, srcs["TEXCOORD"]) if "TEXCOORD" in srcs else None
    if prim.tag == C + "polygons":
        tris = []
        for el in prim.findall("c:p", NS):
            p = list(map(int, el.text.split()))
            poly = [p[k : k + stride] for k in range(0, len(p), stride)]
            tris += [(poly[0], poly[j], poly[j + 1]) for j in range(1, len(poly) - 1)]
        return tris, off, P, N, T
    p = list(map(int, prim.find("c:p", NS).text.split()))
    corners = [p[k : k + stride] for k in range(0, len(p), stride)]
    tris = []
    if prim.tag == C + "polylist":
        k = 0
        for n in map(int, prim.find("c:vcount", NS).text.split()):
            poly = corners[k : k + n]
            k += n
            tris += [(poly[0], poly[j], poly[j + 1]) for j in range(1, n - 1)]
    else:
        tris = [tuple(corners[k : k + 3]) for k in range(0, len(corners), 3)]
    return tris, off, P, N, T


def _build_mesh(name, tris, off, positions, normals, T):
    verts, faces, uvs, nors, vmap = [], [], [], [], {}
    for tri in tris:
        if len({c[off["VERTEX"]] for c in tri}) < 3:
            continue  # degenerate: makes normals_split_custom_set crash Blender
        f = []
        for c in tri:
            vi = c[off["VERTEX"]]
            if vi not in vmap:
                vmap[vi] = len(verts)
                verts.append(positions[vi])
            f.append(vmap[vi])
            if T is not None:
                ti = c[off["TEXCOORD"]]
                uvs.append((T[2 * ti], T[2 * ti + 1]))
            if normals is not None:
                nors.append(normals[c[off["NORMAL"]]])
        faces.append(f)
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    if uvs:
        layer = me.uv_layers.new(name="UVMap")
        for i, t in enumerate(uvs):
            layer.data[i].uv = t
    if nors:
        me.normals_split_custom_set([tuple(n.normalized()) for n in nors])
    me.validate()
    me.update()
    return me


def import_static(path, name, collection):
    """Imports a static mesh. Returns (object, {prop point: world matrix})."""
    root = ET.parse(path).getroot()
    nodes, cache = _nodes(root), {}
    up = _up_matrix(root)
    geom_node = next(
        (
            n
            for n, v in nodes.items()
            if v[4].find("c:instance_geometry", NS) is not None
        ),
        None,
    )
    if geom_node is None:
        raise ValueError(f"{path} has no <instance_geometry>")
    gid = nodes[geom_node][4].find("c:instance_geometry", NS).get("url").lstrip("#")
    tris, off, P, N, T = _triangles(root, root.find(f".//c:geometry[@id='{gid}']", NS))
    M = up @ _world(nodes, geom_node, {}, cache)
    R = M.to_3x3()
    pos = [M @ Vector(P[3 * i : 3 * i + 3]) for i in range(len(P) // 3)]
    nor = [R @ Vector(N[3 * i : 3 * i + 3]) for i in range(len(N) // 3)] if N else None
    ob = bpy.data.objects.new(name, _build_mesh(name, tris, off, pos, nor, T))
    collection.objects.link(ob)
    props = {
        n[len("prop-") :]: up @ _world(nodes, n, {}, cache)
        for n in nodes
        if _is_prop(n)
    }
    return ob, props


def import_skinned(body_path, name, collection, anim_path=None, frame=0):
    """Imports a skinned mesh in its rest pose, or posed on a frame of anim_path.

    Returns (object, {prop point: world matrix}).
    """
    body = ET.parse(body_path).getroot()
    anim = ET.parse(anim_path).getroot() if anim_path else body
    up = _up_matrix(body)
    bnodes, anodes = _nodes(body), _nodes(anim)
    by_id = {v[2]: k for k, v in anodes.items()}
    locals_ = {}
    for ch in anim.iter(C + "channel"):
        target = ch.get("target").split("/")[0]
        if target not in by_id:
            continue
        sampler = anim.find(f".//c:sampler[@id='{ch.get('source').lstrip('#')}']", NS)
        out = sampler.find("c:input[@semantic='OUTPUT']", NS).get("source")
        acc = anim.find(
            f".//c:source[@id='{out.lstrip('#')}']/c:technique_common/c:accessor", NS
        )
        if acc is None or acc.get("stride") != "16":
            continue  # full matrix channels only
        vals = _source(anim, out)
        k = min(frame, len(vals) // 16 - 1)
        locals_[by_id[target]] = _mat16(vals[16 * k : 16 * k + 16])
    # bones posed by the animation; prop points keep their position from the body
    for k, v in anodes.items():
        if k in bnodes and k not in locals_ and not k.startswith("prop"):
            locals_[k] = v[1]
    cache = {}
    skin = body.find(".//c:skin", NS)
    bsm = _mat16(skin.find("c:bind_shape_matrix", NS).text.split())
    joints = skin.find("c:joints", NS)
    jnames = _source(body, joints.find("c:input[@semantic='JOINT']", NS).get("source"))
    ib = _source(
        body, joints.find("c:input[@semantic='INV_BIND_MATRIX']", NS).get("source")
    )
    sid2name = {v[3]: k for k, v in bnodes.items() if v[3]}
    skinmats = [
        _world(bnodes, sid2name.get(jn, jn), locals_, cache)
        @ _mat16(ib[16 * j : 16 * j + 16])
        @ bsm
        for j, jn in enumerate(jnames)
    ]
    vw = skin.find("c:vertex_weights", NS)
    weights = _source(body, vw.find("c:input[@semantic='WEIGHT']", NS).get("source"))
    oj = int(vw.find("c:input[@semantic='JOINT']", NS).get("offset"))
    ow = int(vw.find("c:input[@semantic='WEIGHT']", NS).get("offset"))
    vcount = list(map(int, vw.find("c:vcount", NS).text.split()))
    v = list(map(int, vw.find("c:v", NS).text.split()))
    tris, off, P, N, T = _triangles(
        body, body.find(f".//c:geometry[@id='{skin.get('source').lstrip('#')}']", NS)
    )
    blends, pos, k = [], [], 0
    for vi, n in enumerate(vcount):
        M = (
            Matrix(((0,) * 4,) * 4) if n else bsm
        )  # unweighted vertices stay at their bind shape
        for _ in range(n):
            M = M + skinmats[v[2 * k + oj]] * weights[v[2 * k + ow]]
            k += 1
        M = up @ M
        blends.append(M)
        pos.append(M @ Vector(P[3 * vi : 3 * vi + 3]))
    nor = None
    if N is not None:
        nmap = {c[off["NORMAL"]]: c[off["VERTEX"]] for tri in tris for c in tri}
        nor = [None] * (len(N) // 3)
        for ni, vi in nmap.items():
            nor[ni] = blends[vi].to_3x3() @ Vector(N[3 * ni : 3 * ni + 3])
    ob = bpy.data.objects.new(name, _build_mesh(name, tris, off, pos, nor, T))
    collection.objects.link(ob)
    props = {
        n[len("prop-") :]: up @ _world(bnodes, n, locals_, cache)
        for n in bnodes
        if _is_prop(n)
    }
    return ob, props


def import_dae(path, collection):
    """Imports a .dae as the game sees it: one mesh plus an empty "prop_<name>" per prop point,
    parented to the mesh so nested props follow it. Returns the new objects."""
    name = os.path.splitext(os.path.basename(path))[0]
    root = ET.parse(path).getroot()
    if root.find(".//c:instance_controller", NS) is not None:
        ob, props = import_skinned(path, name, collection)
    else:
        ob, props = import_static(path, name, collection)
    objects = [ob]
    for prop_name, matrix in props.items():
        empty = bpy.data.objects.new("prop_" + prop_name, None)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 0.2
        empty.parent = ob
        empty.matrix_basis = matrix
        collection.objects.link(empty)
        objects.append(empty)
    return objects
