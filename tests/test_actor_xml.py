# SPDX-License-Identifier: GPL-2.0-or-later

"""Reading actor and variant XML files, without importing any mesh."""

import logging
import types
import xml.etree.ElementTree as ET

import pytest

from io_import_0ad_actor.import_pyrogenesis_actor import ImportPyrogenesisActor


@pytest.fixture
def art(tmp_path):
    """An art/ folder like the game's; files are written with art.write(path, xml)."""
    root = tmp_path / "art"

    def write(path, xml):
        f = root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(xml)
        return str(f)

    return types.SimpleNamespace(path=str(root) + "/", write=write)


@pytest.fixture
def op(art):
    op = ImportPyrogenesisActor()
    op.currentPath = art.path
    return op


def variant_root(art, path, xml):
    return ET.parse(art.write(path, xml)).getroot()


def names(element, tag, attr):
    return [e.attrib[attr] for e in element.iter(tag)]


def test_operator_sets_up_a_logger():
    assert isinstance(ImportPyrogenesisActor().logger, logging.Logger)


def test_load_actor_returns_a_plain_actor(op, art):
    path = art.write(
        "actors/a.xml", '<actor version="1"><material>m.xml</material></actor>'
    )
    root = op.load_actor(path)
    assert root.tag == "actor"
    assert root.find("material").text == "m.xml"


def test_load_actor_picks_the_actor_without_quality(op, art):
    path = art.write(
        "actors/q.xml",
        "<qualitylevels>"
        '<actor quality="100" version="1"><material>low.xml</material></actor>'
        '<actor version="1"><material>high.xml</material></actor>'
        '<actor quality="200" version="1"><material>mid.xml</material></actor>'
        "</qualitylevels>",
    )
    assert op.load_actor(path).find("material").text == "high.xml"


def test_load_actor_falls_back_to_the_last_quality_level(op, art):
    path = art.write(
        "actors/q.xml",
        "<qualitylevels>"
        '<actor quality="100" version="1"><material>low.xml</material></actor>'
        '<actor quality="200" version="1"><material>high.xml</material></actor>'
        "</qualitylevels>",
    )
    assert op.load_actor(path).find("material").text == "high.xml"


def test_mesh_found_in_the_variant(op, art):
    root = variant_root(
        art, "variants/v.xml", "<variant><mesh>own.dae</mesh></variant>"
    )
    assert op.get_mesh_from_variant(root).text == "own.dae"


def test_mesh_inherited_through_nested_variant_files(op, art):
    art.write("variants/base.xml", "<variant><mesh>base.dae</mesh></variant>")
    art.write("variants/mid.xml", '<variant file="base.xml"/>')
    root = variant_root(art, "variants/top.xml", '<variant file="mid.xml"/>')
    assert op.get_mesh_from_variant(root).text == "base.dae"


def test_own_mesh_wins_over_the_inherited_one(op, art):
    art.write("variants/base.xml", "<variant><mesh>base.dae</mesh></variant>")
    root = variant_root(
        art,
        "variants/top.xml",
        '<variant file="base.xml"><mesh>own.dae</mesh></variant>',
    )
    assert op.get_mesh_from_variant(root).text == "own.dae"


def test_no_mesh_anywhere(op, art):
    art.write("variants/base.xml", "<variant/>")
    root = variant_root(art, "variants/top.xml", '<variant file="base.xml"/>')
    assert op.get_mesh_from_variant(root) is None
    assert op.get_textures_from_variant(root) is None
    assert op.get_props_from_variant(root) is None


def test_textures_are_merged_with_the_inherited_ones(op, art):
    art.write(
        "variants/base.xml",
        '<variant><textures><texture name="baseTex" file="b.png"/>'
        '<texture name="normTex" file="n.png"/></textures></variant>',
    )
    root = variant_root(
        art,
        "variants/top.xml",
        '<variant file="base.xml"><textures>'
        '<texture name="specTex" file="s.png"/></textures></variant>',
    )
    textures = op.get_textures_from_variant(root)
    assert names(textures, "texture", "file") == ["b.png", "n.png", "s.png"]


def test_own_textures_over_a_file_without_any(op, art):
    art.write("variants/empty.xml", "<variant/>")
    root = variant_root(
        art,
        "variants/own.xml",
        '<variant file="empty.xml"><textures>'
        '<texture name="baseTex" file="o.png"/></textures></variant>',
    )
    assert names(op.get_textures_from_variant(root), "texture", "file") == ["o.png"]


def test_textures_only_inherited(op, art):
    art.write(
        "variants/base.xml",
        '<variant><textures><texture name="baseTex" file="b.png"/></textures></variant>',
    )
    root = variant_root(art, "variants/top.xml", '<variant file="base.xml"/>')
    assert names(op.get_textures_from_variant(root), "texture", "file") == ["b.png"]


def test_props_only_inherited(op, art):
    art.write(
        "variants/brown.xml",
        '<variant><props><prop actor="props/hair.xml" attachpoint="hair"/></props>'
        "</variant>",
    )
    root = variant_root(art, "variants/top.xml", '<variant file="brown.xml"/>')
    assert names(op.get_props_from_variant(root), "prop", "attachpoint") == ["hair"]


def test_props_are_merged_through_nested_variant_files(op, art):
    art.write(
        "variants/base.xml",
        '<variant><props><prop actor="props/helmet.xml" attachpoint="helmet"/></props>'
        "</variant>",
    )
    art.write(
        "variants/mid.xml",
        '<variant file="base.xml"><props>'
        '<prop actor="props/shield.xml" attachpoint="shield"/></props></variant>',
    )
    root = variant_root(
        art,
        "variants/top.xml",
        '<variant file="mid.xml"><props>'
        '<prop actor="props/sword.xml" attachpoint="r_hand"/></props></variant>',
    )
    props = op.get_props_from_variant(root)
    assert names(props, "prop", "attachpoint") == ["helmet", "shield", "r_hand"]


@pytest.mark.parametrize(
    ("point", "expected"),
    [("head", "prop_head"), ("r_hand", "prop_r_hand"), ("tail", None)],
)
def test_find_prop_root_object(op, point, expected):
    objects = [
        types.SimpleNamespace(name=n) for n in ("body", "prop_head", "prop_r_hand")
    ]
    found = op.find_prop_root_object(objects, point)
    assert (found.name if found else None) == expected


def test_print_header_lines_have_the_same_length(op, caplog):
    with caplog.at_level(logging.INFO, logger="PyrogenesisActorImporter"):
        op.print_header("Gathering Mesh")
        op.print_header("A header much longer than the fifty five characters limit")
    lines = [r.getMessage() for r in caplog.records if r.getMessage()]
    assert len(lines) == 6
    assert {len(line) for line in lines} == {55}
    assert "Gathering Mesh" in lines[1]


def props_element(*props):
    return ET.fromstring(
        "<props>"
        + "".join(
            f'<prop attachpoint="{point}"'
            + ("" if actor is None else f' actor="{actor}"')
            + "/>"
            for point, actor in props
        )
        + "</props>"
    )


def chosen(props):
    return [(p.attrib["attachpoint"], p.attrib["actor"]) for p in props]


def test_variant_props_are_added_to_the_chosen_ones(op):
    first = op.apply_variant_props([], props_element(("helmet", "h.xml")))
    result = op.apply_variant_props(first, props_element(("shield", "s.xml")))
    assert chosen(result) == [("helmet", "h.xml"), ("shield", "s.xml")]


def test_variant_props_replace_those_on_the_same_attach_point(op):
    first = op.apply_variant_props(
        [], props_element(("root", "mask.xml"), ("crest", "c.xml"))
    )
    result = op.apply_variant_props(first, props_element(("root", "other.xml")))
    assert chosen(result) == [("crest", "c.xml"), ("root", "other.xml")]


@pytest.mark.parametrize("actor", ["", None])
def test_empty_props_remove_those_on_the_same_attach_point(op, actor):
    # e.g. the "No - Mask" variant of props/units/helmets/hele_thracian_b1.xml, or the
    # "Idle" variant of props/units/kush_meroitic_scabbard.xml (<prop attachpoint="sword"/>)
    first = op.apply_variant_props(
        [], props_element(("root", "mask.xml"), ("crest", "c.xml"))
    )
    result = op.apply_variant_props(first, props_element(("root", actor)))
    assert chosen(result) == [("crest", "c.xml")]


def test_several_props_on_one_attach_point_are_kept(op):
    # e.g. the two hair props on "hair" in the stable horse variants
    result = op.apply_variant_props(
        [], props_element(("hair", "hair_a.xml"), ("hair", "hair_b.xml"))
    )
    assert chosen(result) == [("hair", "hair_a.xml"), ("hair", "hair_b.xml")]
