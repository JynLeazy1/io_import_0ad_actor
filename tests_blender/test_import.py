# SPDX-License-Identifier: GPL-2.0-or-later

"""Imports the actors of data/art/actors/test with the operator, in Blender."""

import hashlib
import math
import os
import unittest

import bpy

ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "art")
LOGGER = "PyrogenesisActorImporter"


def art_digest():
    """A hash of every file under data/art, to check that nothing is written there."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in sorted(os.walk(ART)):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            h.update(os.path.relpath(path, ART).encode())
            with open(path, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


class ImportTestCase(unittest.TestCase):
    def setUp(self):
        for collection in (
            bpy.data.objects,
            bpy.data.meshes,
            bpy.data.materials,
            bpy.data.images,
        ):
            for item in list(collection):
                collection.remove(item)

    def import_actor(self, name, **options):
        path = os.path.join(ART, "actors", "test", name + ".xml")
        result = bpy.ops.import_scene.zeroad_actor(filepath=path, **options)
        self.assertEqual(result, {"FINISHED"})
        bpy.context.view_layer.update()
        return {o.name: o for o in bpy.data.objects}

    def assertVectorsAlmostEqual(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            for x, y in zip(a, e):
                self.assertAlmostEqual(x, y, places=5, msg=f"{tuple(a)} != {e}")

    def world_vertices(self, ob):
        return [tuple(ob.matrix_world @ v.co) for v in ob.data.vertices]

    def assertAttachedTo(self, ob, prop_point):
        self.assertEqual(ob.parent, prop_point)
        self.assertEqual(
            [(c.type, c.target) for c in ob.constraints],
            [("COPY_LOCATION", prop_point), ("COPY_ROTATION", prop_point)],
        )
        self.assertVectorsAlmostEqual(
            [ob.matrix_world.translation], [prop_point.matrix_world.translation]
        )

    def linked_node(self, socket):
        return socket.links[0].from_node.bl_idname if socket.links else None


class TestStaticActor(ImportTestCase):
    def test_mesh_with_prop_points(self):
        objects = self.import_actor("static")
        self.assertEqual(sorted(objects), ["box", "helmet", "prop_hand", "prop_head"])
        box = objects["box"]
        self.assertEqual(box.type, "MESH")
        # Y_UP (x, y, z) -> Z_UP (x, -z, y)
        self.assertVectorsAlmostEqual(
            self.world_vertices(box),
            [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)],
        )
        # the quad is triangulated, like the game does
        self.assertEqual(len(box.data.polygons), 2)
        self.assertEqual([layer.name for layer in box.data.uv_layers], ["UVMap"])
        for point in ("prop_head", "prop_hand"):
            self.assertEqual(objects[point].type, "EMPTY")
            self.assertEqual(objects[point].parent, box)
        self.assertVectorsAlmostEqual(
            [objects["prop_head"].matrix_world.translation], [(0, 0, 2)]
        )
        self.assertVectorsAlmostEqual(
            [objects["prop_hand"].matrix_world.translation], [(1, 0, 1)]
        )

    def test_prop_follows_its_prop_point(self):
        objects = self.import_actor("static")
        helmet = objects["helmet"]
        self.assertAttachedTo(helmet, objects["prop_head"])
        # the rotation exporters give Y_UP prop points is undone, so the helmet stands up
        self.assertVectorsAlmostEqual(
            [tuple(helmet.matrix_world.to_euler())], [(0, 0, 0)]
        )
        self.assertVectorsAlmostEqual(
            self.world_vertices(helmet), [(0, 0, 2), (0.5, 0, 2), (0, 0, 2.5)]
        )

    def test_prop_point_without_that_rotation_is_turned_like_in_the_game(self):
        objects = self.import_actor("override")
        helmet = objects["helmet"]
        self.assertAttachedTo(helmet, objects["prop_hand"])
        self.assertAlmostEqual(
            helmet.matrix_world.to_euler().x, math.radians(90), places=5
        )

    def test_player_color_material(self):
        objects = self.import_actor("static")
        self.assertEqual(
            sorted(i.name for i in bpy.data.images),
            ["base.png", "helmet.png", "norm.png", "spec.png"],
        )
        self.assertEqual([m.name for m in objects["box"].data.materials], ["base.png"])
        material = bpy.data.materials["base.png"]
        nodes = material.node_tree.nodes
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        # player_trans: the base texture is mixed with the player color through its alpha
        self.assertEqual(
            self.linked_node(bsdf.inputs["Base Color"]), "ShaderNodeMixRGB"
        )
        self.assertEqual(self.linked_node(bsdf.inputs["Normal"]), "ShaderNodeNormalMap")
        self.assertEqual(
            self.linked_node(bsdf.inputs["Specular IOR Level"]), "ShaderNodeTexImage"
        )
        images = {n.image.name: n for n in nodes if n.type == "TEX_IMAGE"}
        self.assertEqual(sorted(images), ["base.png", "norm.png", "spec.png"])
        self.assertEqual(nodes.active, images["base.png"])
        for name in ("norm.png", "spec.png"):
            self.assertEqual(
                bpy.data.images[name].colorspace_settings.name, "Non-Color"
            )

    def test_transparent_material(self):
        objects = self.import_actor("static")
        self.assertEqual(
            [m.name for m in objects["helmet"].data.materials], ["helmet.png"]
        )
        nodes = bpy.data.materials["helmet.png"].node_tree.nodes
        output = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
        # basic_trans: the alpha mixes the BSDF with a transparent shader
        self.assertEqual(
            self.linked_node(output.inputs["Surface"]), "ShaderNodeMixShader"
        )
        self.assertTrue(any(n.type == "BSDF_TRANSPARENT" for n in nodes))

    def test_without_props(self):
        objects = self.import_actor("static", import_props=False)
        self.assertEqual(sorted(objects), ["box", "prop_hand", "prop_head"])

    def test_without_textures(self):
        objects = self.import_actor("static", import_textures=False)
        self.assertEqual(len(bpy.data.images), 0)
        self.assertEqual(len(bpy.data.materials), 0)
        self.assertIn("helmet", objects)

    def test_source_files_are_not_modified(self):
        before = art_digest()
        for actor in ("static", "inherited", "override", "quality", "skinned", "decal"):
            self.setUp()
            self.import_actor(actor)
        self.assertEqual(art_digest(), before)


class TestVariants(ImportTestCase):
    def test_everything_inherited_through_a_variant_file(self):
        objects = self.import_actor("inherited")
        self.assertEqual(sorted(objects), ["box", "helmet", "prop_hand", "prop_head"])
        self.assertEqual([m.name for m in objects["box"].data.materials], ["base.png"])
        self.assertAttachedTo(objects["helmet"], objects["prop_head"])

    def test_later_group_removes_a_prop(self):
        objects = self.import_actor("override")
        helmets = [o for o in objects.values() if o.name.startswith("helmet")]
        # only the one on "hand" is left
        self.assertEqual(len(helmets), 1)
        self.assertEqual(helmets[0].parent, objects["prop_hand"])

    def test_highest_quality_level(self):
        objects = self.import_actor("quality")
        self.assertIn("box", objects)
        self.assertNotIn("helmet", objects)


class TestSkinnedActor(ImportTestCase):
    def test_rest_pose_and_prop_on_a_bone(self):
        objects = self.import_actor("skinned")
        self.assertEqual(sorted(objects), ["body", "helmet", "prop_hand"])
        body = objects["body"]
        # no armature is created; the mesh is deformed into its rest pose
        self.assertFalse(any(o.type == "ARMATURE" for o in bpy.data.objects))
        self.assertVectorsAlmostEqual(
            self.world_vertices(body), [(0, 0, 0), (1, 0, 0), (0, -1, 0)]
        )
        self.assertEqual(objects["prop_hand"].parent, body)
        self.assertVectorsAlmostEqual(
            [objects["prop_hand"].matrix_world.translation], [(1, 0, 1)]
        )
        self.assertAttachedTo(objects["helmet"], objects["prop_hand"])


class TestDecal(ImportTestCase):
    def test_decal_plane(self):
        objects = self.import_actor("decal")
        self.assertEqual(sorted(objects), ["Decal"])
        decal = objects["Decal"]
        # width 2 and depth 3 turned 90 degrees, centred on (offsetx, offsetz)
        xs, ys, zs = zip(*self.world_vertices(decal))
        self.assertAlmostEqual(min(xs), -0.5, places=5)
        self.assertAlmostEqual(max(xs), 2.5, places=5)
        self.assertAlmostEqual(min(ys), 1, places=5)
        self.assertAlmostEqual(max(ys), 3, places=5)
        self.assertTrue(all(math.isclose(z, 0.01, abs_tol=1e-5) for z in zs))
        self.assertEqual([layer.name for layer in decal.data.uv_layers], ["UVMap"])
        self.assertEqual([m.name for m in decal.data.materials], ["base.png"])


class TestErrors(ImportTestCase):
    def test_valid_actors_log_no_errors(self):
        for actor in ("static", "inherited", "override", "quality", "skinned", "decal"):
            with self.subTest(actor=actor), self.assertNoLogs(LOGGER, level="ERROR"):
                self.setUp()
                self.import_actor(actor)

    def test_missing_mesh_is_logged(self):
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            objects = self.import_actor("missing_mesh")
        self.assertEqual(objects, {})
        self.assertTrue(any("missing.dae" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
