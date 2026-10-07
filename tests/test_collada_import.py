# SPDX-License-Identifier: GPL-2.0-or-later

import xml.etree.ElementTree as ET

import pytest
from mathutils import Matrix, Vector

from io_import_0ad_actor import collada_import as ci

IDENTITY = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"


def translation(x, y, z):
    return f"1 0 0 {x} 0 1 0 {y} 0 0 1 {z} 0 0 0 1"


def dae(body, up_axis="Y_UP"):
    up = f"<asset><up_axis>{up_axis}</up_axis></asset>" if up_axis else ""
    return (
        '<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
        f"{up}{body}</COLLADA>"
    )


def parse(body, up_axis="Y_UP"):
    return ET.fromstring(dae(body, up_axis))


def write(tmp_path, name, body, up_axis="Y_UP"):
    path = tmp_path / name
    path.write_text(dae(body, up_axis))
    return str(path)


def scene(nodes):
    return (
        "<library_visual_scenes><visual_scene id='scene'>"
        f"{nodes}</visual_scene></library_visual_scenes>"
    )


def geometry(gid, positions, primitive, extra_sources=""):
    return (
        f"<library_geometries><geometry id='{gid}'><mesh>"
        f"<source id='{gid}-pos'><float_array>{positions}</float_array></source>"
        f"{extra_sources}"
        f"<vertices id='{gid}-v'><input semantic='POSITION' source='#{gid}-pos'/></vertices>"
        f"{primitive}</mesh></geometry></library_geometries>"
    )


def assert_vectors(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert tuple(a) == pytest.approx(e, abs=1e-6)


def assert_translation(matrix, expected):
    assert tuple(matrix.to_translation()) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("prop-head", True),
        ("prop_rider", True),
        ("prop.head", False),
        ("head", False),
        ("root-prop-head", False),
    ],
)
def test_is_prop(name, expected):
    assert ci._is_prop(name) is expected


def test_source_reads_float_name_and_idref_arrays():
    root = parse(
        "<source id='f'><float_array>1 2.5 -3</float_array></source>"
        "<source id='n'><Name_array>hip spine</Name_array></source>"
        "<source id='i'><IDREF_array>a b</IDREF_array></source>"
    )
    assert ci._source(root, "#f") == [1.0, 2.5, -3.0]
    assert ci._source(root, "n") == ["hip", "spine"]
    assert ci._source(root, "#i") == ["a", "b"]


@pytest.mark.parametrize("up_axis", ["Y_UP", None])
def test_y_up_is_converted_to_z_up(up_axis):
    m = ci._up_matrix(parse("", up_axis))
    assert tuple(m @ Vector((1, 2, 3))) == pytest.approx((1, -3, 2))


def test_z_up_is_kept():
    assert ci._up_matrix(parse("", "Z_UP")) == Matrix.Identity(4)


def test_local_matrix_composes_transforms_in_document_order():
    node = parse(
        "<node><translate>1 0 0</translate><rotate>0 0 1 90</rotate>"
        "<scale>2 2 2</scale></node>"
    ).find("c:node", ci.NS)
    m = ci._local_matrix(node)
    # scaled first, then rotated, then translated
    assert tuple(m @ Vector((1, 0, 0))) == pytest.approx((1, 2, 0), abs=1e-6)


def test_local_matrix_reads_row_major_matrices():
    node = parse(f"<node><matrix>{translation(4, 5, 6)}</matrix></node>").find(
        "c:node", ci.NS
    )
    assert_translation(ci._local_matrix(node), (4, 5, 6))


def test_nodes_and_world_matrices():
    root = parse(
        scene(
            "<node id='a' name='A'><translate>1 0 0</translate>"
            "<node id='b-id' sid='b-sid'><translate>0 1 0</translate></node>"
            "<node id='dup1' name='A'><translate>0 0 1</translate></node>"
            "</node>"
        )
    )
    nodes = ci._nodes(root)
    # unnamed nodes are keyed by id; a repeated name gets a suffix
    assert list(nodes) == ["A", "b-id", "A.2"]
    assert nodes["b-id"][0] == "A"
    assert nodes["b-id"][2:4] == ("b-id", "b-sid")
    assert nodes["A.2"][0] == "A"

    cache = {}
    assert_translation(ci._world(nodes, "b-id", {}, cache), (1, 1, 0))
    assert_translation(ci._world(nodes, "A.2", {}, cache), (1, 0, 1))
    # locals_ overrides a node's own matrix, e.g. with an animation frame
    posed = {"A": Matrix.Translation((5, 0, 0))}
    assert_translation(ci._world(nodes, "b-id", posed, {}), (5, 1, 0))


def test_triangles_with_several_inputs_and_uv_sets():
    root = parse(
        geometry(
            "g",
            "0 0 0 1 0 0 0 1 0",
            "<triangles count='1'>"
            "<input semantic='VERTEX' source='#g-v' offset='0'/>"
            "<input semantic='NORMAL' source='#g-n' offset='1'/>"
            "<input semantic='TEXCOORD' source='#g-uv0' offset='2' set='0'/>"
            "<input semantic='TEXCOORD' source='#g-uv1' offset='3' set='1'/>"
            "<p>0 0 0 9 1 0 1 9 2 0 2 9</p></triangles>",
            "<source id='g-n'><float_array>0 0 1</float_array></source>"
            "<source id='g-uv0'><float_array>0 0 1 0 0 1</float_array></source>"
            "<source id='g-uv1'><float_array>5 5</float_array></source>",
        )
    )
    tris, off, P, N, T = ci._triangles(root, root.find(".//c:geometry", ci.NS))
    assert off == {"VERTEX": 0, "NORMAL": 1, "TEXCOORD": 2}  # first UV set only
    assert tris == [([0, 0, 0, 9], [1, 0, 1, 9], [2, 0, 2, 9])]
    assert P == [0, 0, 0, 1, 0, 0, 0, 1, 0]
    assert N == [0, 0, 1]
    assert T == [0, 0, 1, 0, 0, 1]


def test_polylist_is_fan_triangulated():
    root = parse(
        geometry(
            "g",
            "0 0 0 1 0 0 1 1 0 0 1 0 2 0 0",
            "<polylist count='2'>"
            "<input semantic='VERTEX' source='#g-v' offset='0'/>"
            "<vcount>4 3</vcount><p>0 1 2 3 1 4 2</p></polylist>",
        )
    )
    tris, off, P, N, T = ci._triangles(root, root.find(".//c:geometry", ci.NS))
    assert tris == [([0], [1], [2]), ([0], [2], [3]), ([1], [4], [2])]
    assert N is None and T is None


def test_polygons_are_read_one_p_per_polygon():
    root = parse(
        geometry(
            "g",
            "0 0 0 1 0 0 1 1 0 0 1 0",
            "<polygons count='2'>"
            "<input semantic='VERTEX' source='#g-v' offset='0'/>"
            "<p>0 1 2 3</p><p>0 2 3</p></polygons>",
        )
    )
    tris, *_ = ci._triangles(root, root.find(".//c:geometry", ci.NS))
    assert tris == [([0], [1], [2]), ([0], [2], [3]), ([0], [2], [3])]


def test_build_mesh_skips_degenerate_triangles_and_sets_uvs_and_normals(bpy_data):
    positions = [Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((0, 1, 0))]
    normals = [Vector((0, 0, 2))]
    T = [0, 0, 1, 0, 0, 1]
    off = {"VERTEX": 0, "NORMAL": 1, "TEXCOORD": 2}
    tris = [
        ([0, 0, 0], [1, 0, 1], [2, 0, 2]),
        ([0, 0, 0], [0, 0, 0], [1, 0, 1]),  # degenerate
    ]
    me = ci._build_mesh("m", tris, off, positions, normals, T)
    assert me.faces == [[0, 1, 2]]
    assert me.vertices == [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    assert [layer.name for layer in me.uv_layers] == ["UVMap"]
    assert [loop.uv for loop in me.uv_layers[0].data] == [(0, 0), (1, 0), (0, 1)]
    assert me.custom_normals == [pytest.approx((0, 0, 1))] * 3


def test_build_mesh_only_keeps_used_vertices(bpy_data):
    positions = [
        Vector((9, 9, 9)),
        Vector((0, 0, 0)),
        Vector((1, 0, 0)),
        Vector((0, 1, 0)),
    ]
    me = ci._build_mesh("m", [([3], [1], [2])], {"VERTEX": 0}, positions, None, None)
    assert me.vertices == [(0, 1, 0), (0, 0, 0), (1, 0, 0)]
    assert me.faces == [[0, 1, 2]]
    assert len(me.uv_layers) == 0
    assert me.custom_normals is None


STATIC = geometry(
    "box",
    "0 0 0 1 0 0 0 1 0",
    "<triangles count='1'><input semantic='VERTEX' source='#box-v' offset='0'/>"
    "<p>0 1 2</p></triangles>",
) + scene(
    "<node id='root' name='root'><translate>1 2 3</translate>"
    "<node id='mesh' name='mesh'><instance_geometry url='#box'/></node>"
    "<node id='prop-head' name='prop-head'><translate>0 1 0</translate></node>"
    "<node id='prop_rider' name='prop_rider'><translate>0 0 1</translate></node>"
    "<node id='other' name='other'/>"
    "</node>"
)


def test_import_static_applies_world_and_up_axis(tmp_path, bpy_data, collection):
    path = write(tmp_path, "box.dae", STATIC)
    ob, props = ci.import_static(path, "box", collection)
    assert collection.objects == [ob]
    assert ob.name == "box"
    # (x, y, z) + (1, 2, 3) in Y_UP -> (x, -z, y) in Z_UP
    assert_vectors(ob.data.vertices, [(1, -3, 2), (2, -3, 2), (1, -3, 3)])
    assert sorted(props) == ["head", "rider"]
    assert_translation(props["head"], (1, -3, 3))
    assert_translation(props["rider"], (1, -4, 2))


def test_import_static_keeps_z_up(tmp_path, bpy_data, collection):
    path = write(tmp_path, "box.dae", STATIC, "Z_UP")
    ob, props = ci.import_static(path, "box", collection)
    assert_vectors(ob.data.vertices, [(1, 2, 3), (2, 2, 3), (1, 3, 3)])
    assert_translation(props["head"], (1, 3, 3))


def test_import_static_without_geometry_fails(tmp_path, bpy_data, collection):
    path = write(tmp_path, "empty.dae", scene("<node id='n' name='n'/>"))
    with pytest.raises(ValueError, match="no <instance_geometry>"):
        ci.import_static(path, "empty", collection)


# One bone at (0, 1, 0); vertices 0 and 1 follow it, vertex 2 has no weights.
SKINNED = (
    geometry(
        "body",
        "0 0 0 1 0 0 0 0 1",
        "<triangles count='1'><input semantic='VERTEX' source='#body-v' offset='0'/>"
        "<p>0 1 2</p></triangles>",
    )
    + "<library_controllers><controller id='ctrl'><skin source='#body'>"
    f"<bind_shape_matrix>{IDENTITY}</bind_shape_matrix>"
    "<source id='joints'><Name_array>bone</Name_array></source>"
    f"<source id='ibm'><float_array>{translation(0, -1, 0)}</float_array></source>"
    "<source id='weights'><float_array>1</float_array></source>"
    "<joints><input semantic='JOINT' source='#joints'/>"
    "<input semantic='INV_BIND_MATRIX' source='#ibm'/></joints>"
    "<vertex_weights count='3'>"
    "<input semantic='JOINT' source='#joints' offset='0'/>"
    "<input semantic='WEIGHT' source='#weights' offset='1'/>"
    "<vcount>1 1 0</vcount><v>0 0 0 0</v></vertex_weights>"
    "</skin></controller></library_controllers>"
    + scene(
        "<node id='Armature' name='Armature'>"
        "<node id='bone' name='bone' sid='bone' type='JOINT'>"
        f"<matrix>{translation(0, 1, 0)}</matrix>"
        "<node id='prop-hand' name='prop-hand'><translate>1 0 0</translate></node>"
        "</node></node>"
        "<node id='body-node' name='body-node'><instance_controller url='#ctrl'/></node>"
    )
)

# Moves the bone to (0, 2, 0) on frame 0 and (0, 3, 0) on frame 1.
ANIMATION = (
    "<library_animations><animation id='anim'>"
    "<source id='anim-out'>"
    f"<float_array id='anim-out-array'>{translation(0, 2, 0)} {translation(0, 3, 0)}"
    "</float_array><technique_common>"
    "<accessor source='#anim-out-array' count='2' stride='16'/>"
    "</technique_common></source>"
    "<sampler id='anim-sampler'><input semantic='OUTPUT' source='#anim-out'/></sampler>"
    "<channel source='#anim-sampler' target='bone/transform'/>"
    "</animation></library_animations>"
    + scene(
        "<node id='Armature' name='Armature'>"
        f"<node id='bone' name='bone' sid='bone'><matrix>{IDENTITY}</matrix></node>"
        "</node>"
    )
)


def test_import_skinned_rest_pose(tmp_path, bpy_data, collection):
    path = write(tmp_path, "body.dae", SKINNED)
    ob, props = ci.import_skinned(path, "body", collection)
    assert collection.objects == [ob]
    # the bone is at its bind pose, so vertices only get the Y_UP -> Z_UP conversion
    assert_vectors(ob.data.vertices, [(0, 0, 0), (1, 0, 0), (0, -1, 0)])
    assert list(props) == ["hand"]
    assert_translation(props["hand"], (1, 0, 1))


@pytest.mark.parametrize(("frame", "offset"), [(0, 1), (1, 2), (7, 2)])
def test_import_skinned_posed_on_an_animation_frame(
    tmp_path, bpy_data, collection, frame, offset
):
    body = write(tmp_path, "body.dae", SKINNED)
    anim = write(tmp_path, "walk.dae", ANIMATION)
    ob, props = ci.import_skinned(body, "body", collection, anim, frame)
    # weighted vertices move up with the bone; the unweighted one stays at its bind shape
    assert_vectors(ob.data.vertices, [(0, 0, offset), (1, 0, offset), (0, -1, 0)])
    # prop points follow the posed bone
    assert_translation(props["hand"], (1, 0, 1 + offset))


def test_import_dae_creates_prop_empties_parented_to_the_mesh(
    tmp_path, bpy_data, collection
):
    path = write(tmp_path, "box.dae", STATIC)
    objects = ci.import_dae(path, collection)
    ob, *empties = objects
    assert ob.name == "box" and ob.data is not None
    assert sorted(e.name for e in empties) == ["prop_head", "prop_rider"]
    for e in empties:
        assert e.data is None
        assert e.parent is ob
        assert e.empty_display_type == "ARROWS"
    assert collection.objects == objects
    head = next(e for e in empties if e.name == "prop_head")
    assert_translation(head.matrix_basis, (1, -3, 3))


def test_import_dae_picks_the_skinned_importer(tmp_path, bpy_data, collection):
    path = write(tmp_path, "body.dae", SKINNED)
    ob, hand = ci.import_dae(path, collection)
    assert_vectors(ob.data.vertices, [(0, 0, 0), (1, 0, 0), (0, -1, 0)])
    assert hand.name == "prop_hand"
    assert_translation(hand.matrix_basis, (1, 0, 1))
