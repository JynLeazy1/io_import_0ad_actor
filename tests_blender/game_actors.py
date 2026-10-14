# SPDX-License-Identifier: GPL-2.0-or-later

"""Imports every actor of a 0 A.D. checkout and reports what went wrong.

    python3 tests_blender/game_actors.py ~/0ad/binaries/data/mods/public/art \\
        --output report.json [--baseline old-report.json] [--jobs 4] [--filter units/]

Run with Python, it splits the actors between several headless Blender processes (BLENDER, or
"blender" on the PATH), each of which runs this same file. Every actor is imported in an empty
scene with a fixed random seed, so two runs pick the same variants and can be compared. It also
checks that no file under art/ was written.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

LOGGER = "PyrogenesisActorImporter"


# --- Inside Blender ---------------------------------------------------------------------------


def run_worker(art, actors, output):
    import logging
    import random

    import bpy

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import io_import_0ad_actor

    io_import_0ad_actor.register()

    class Collect(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.messages = []

        def emit(self, record):
            self.messages.append(
                (record.levelname, record.getMessage().splitlines()[0])
            )

    handler = Collect()
    logging.getLogger(LOGGER).addHandler(handler)

    with open(output, "a") as out:
        for actor in actors:
            for data in (
                bpy.data.objects,
                bpy.data.meshes,
                bpy.data.materials,
                bpy.data.images,
                bpy.data.armatures,
            ):
                for item in list(data):
                    data.remove(item)
            handler.messages = []
            random.seed(actor)
            start = time.perf_counter()
            result = {"actor": actor}
            try:
                bpy.ops.import_scene.zeroad_actor(
                    filepath=os.path.join(art, "actors", actor)
                )
                result["status"] = "ok"
            except Exception as e:
                result["status"] = "exception"
                result["exception"] = f"{type(e).__name__}: {str(e).splitlines()[0]}"
            result["seconds"] = round(time.perf_counter() - start, 3)
            result["objects"] = len(bpy.data.objects)
            result["errors"] = [
                m for level, m in handler.messages if level != "WARNING"
            ]
            result["warnings"] = [
                m for level, m in handler.messages if level == "WARNING"
            ]
            if result["status"] == "ok" and result["errors"]:
                result["status"] = "errors"
            out.write(json.dumps(result) + "\n")
            out.flush()


# --- Outside Blender --------------------------------------------------------------------------


def snapshot(art):
    """{path: (size, mtime)} of every file under art/."""
    files = {}
    for dirpath, _, filenames in os.walk(art):
        for name in filenames:
            path = os.path.join(dirpath, name)
            st = os.stat(path)
            files[os.path.relpath(path, art)] = (st.st_size, st.st_mtime_ns)
    return files


def read_results(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_shard(blender, art, actors, workdir, index):
    """Imports actors in one Blender process, starting again after the actor that crashed it."""
    results, remaining = [], list(actors)
    while remaining:
        listing = os.path.join(workdir, f"shard{index}.txt")
        output = os.path.join(workdir, f"shard{index}-{len(results)}.jsonl")
        with open(listing, "w") as f:
            f.write("\n".join(remaining))
        log = os.path.join(workdir, f"shard{index}-{len(results)}.log")
        with open(log, "w") as f:
            process = subprocess.Popen(
                [blender, "-b", "--factory-startup", "--python", __file__, "--",
                 "--worker", art, listing, output],
                stdout=f, stderr=subprocess.STDOUT,
            )  # fmt: skip
        yield process
        done = read_results(output)
        results += done
        remaining = remaining[len(done) :]
        if remaining:  # the process died on this actor
            results.append({"actor": remaining[0], "status": "crashed", "log": log})
            remaining = remaining[1:]
    yield results


def run_all(args):
    art = os.path.abspath(os.path.expanduser(args.art))
    blender = os.environ.get("BLENDER", "blender")
    actors = sorted(
        os.path.relpath(os.path.join(dirpath, name), os.path.join(art, "actors"))
        for dirpath, _, names in os.walk(os.path.join(art, "actors"))
        for name in names
        if name.endswith(".xml")
    )
    actors = [a for a in actors if args.filter in a]
    print(f"{len(actors)} actors, {args.jobs} Blender processes", flush=True)

    before = snapshot(art)
    start = time.time()
    workdir = tempfile.mkdtemp(prefix="game_actors-")
    shards = [
        run_shard(blender, art, actors[i :: args.jobs], workdir, i)
        for i in range(args.jobs)
    ]
    running = {i: next(s) for i, s in enumerate(shards)}
    results = []
    while running:
        for i, process in list(running.items()):
            if process.poll() is None:
                continue
            step = next(shards[i])
            if isinstance(step, list):
                results += step
                del running[i]
            else:
                running[i] = step
        time.sleep(0.2)
    after = snapshot(art)

    changed = sorted(
        p for p in set(before) | set(after) if before.get(p) != after.get(p)
    )
    results.sort(key=lambda r: r["actor"])
    report = {
        "art": art,
        "seconds": round(time.time() - start),
        "modified_files": changed,
        "actors": results,
    }
    with open(args.output, "w") as f:
        json.dump(report, f, indent=1)
    summarise(report, args.baseline)
    return 1 if changed else 0


def summarise(report, baseline_path):
    actors = report["actors"]
    counts = {}
    for r in actors:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\n{len(actors)} actors in {report['seconds']} s: {counts}")

    messages = {}
    for r in actors:
        for m in r.get("errors", []) + ([r["exception"]] if "exception" in r else []):
            key = m.split(" /")[0].split(": /")[0][:100]
            messages.setdefault(key, []).append(r["actor"])
    if messages:
        print("\nMost common errors:")
        for key, who in sorted(messages.items(), key=lambda kv: -len(kv[1]))[:15]:
            print(f"  {len(who):5}  {key}  (e.g. {who[0]})")

    crashed = [r["actor"] for r in actors if r["status"] in ("crashed", "exception")]
    if crashed:
        print("\nCrashes and exceptions:")
        for a in crashed[:20]:
            print("  ", a)

    if report["modified_files"]:
        print(f"\nMODIFIED GAME FILES ({len(report['modified_files'])}):")
        for p in report["modified_files"][:20]:
            print("  ", p)
    else:
        print("\nNo game file was modified.")

    if baseline_path:
        with open(baseline_path) as f:
            old = {r["actor"]: r for r in json.load(f)["actors"]}
        changes = []
        for r in actors:
            o = old.get(r["actor"])
            if o is None:
                continue
            if (o["status"], len(o.get("errors", [])), o["objects"]) != (
                r["status"],
                len(r.get("errors", [])),
                r["objects"],
            ):
                changes.append(
                    f"  {r['actor']}: {o['status']}/{len(o.get('errors', []))} errors/"
                    f"{o['objects']} objects -> {r['status']}/{len(r.get('errors', []))}"
                    f" errors/{r['objects']} objects"
                )
        print(f"\n{len(changes)} actors changed since {baseline_path}")
        for c in changes[:50]:
            print(c)


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    if argv and argv[0] == "--worker":
        art, listing, output = argv[1:4]
        with open(listing) as f:
            run_worker(art, f.read().splitlines(), output)
        return 0
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("art", help="the game's art/ folder")
    parser.add_argument("--output", default="game_actors.json")
    parser.add_argument("--baseline", help="a previous report to compare with")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument(
        "--filter", default="", help="only actors whose path contains this"
    )
    return run_all(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
