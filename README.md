# 0 A.D. Actor Importer

Blender extension that imports [0 A.D.](https://play0ad.com) actors
(`art/actors/**/*.xml`) with their meshes, props and textures, as the game
assembles them.

> [!NOTE]
> This is a continuation of
> [StanleySweet/blender_pyrogenesis_importer](https://github.com/StanleySweet/blender_pyrogenesis_importer)
> by Stanislas Daniel Claude Dolcini and seragh, renamed and updated for
> Blender 5. Its full history is kept in this repository.

## What changed from the original

Blender 5.0 removed the built-in COLLADA importer, which the original add-on
relied on, so actors were imported without any mesh. This version:

- Reads the `.dae` files with a small built-in reader that covers what the
  game's converter uses: static and skinned meshes (rest pose), node
  transforms and prop points.
- No longer rewrites the game's `.dae` files (the original `MaxColladaFixer`
  modified them in place before importing).
- Supports actors wrapped in `<qualitylevels>`, props declared before the
  mesh, empty props and `loaded-*` ammo props.
- Works with Blender 4.4+ operator construction.

It has a new extension id (`io_import_0ad_actor`) and operator, so it can be
installed next to the original.

## Build

```sh
python3 build.py
```

Alternatively using Blender 4.2+

```sh
cd io_import_0ad_actor
blender --command extension build
```

## Installation

1. Build the zip (or download a release).
2. In Blender, navigate to **Edit > Preferences... > Get Extensions** and in
the dropdown menu in the top right corner select **Install from Disk...**

You can now import actor files with **File > Import > 0 A.D. Actor (.xml)**.
The actor must be inside an `art/actors/` folder of the game or of a mod,
since meshes, textures and variants are looked up from there.

## Unsupported Features

- Armatures and animation import: skinned meshes are imported in their rest
  pose
- Multiple UV sets (only the first one is read)

## License

GPL-2.0-or-later, like the original. See [LICENSE](LICENSE).
