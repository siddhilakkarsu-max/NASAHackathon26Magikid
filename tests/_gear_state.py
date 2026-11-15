"""
Keep the tests away from the real gear/state/published_kit.json.

Import this before anything from gear: it points MARSWALK_GEAR_STATE_DIR at a temp dir
for the whole test run (unless it is already set) and removes that dir at exit.
"""
import atexit
import os
import shutil
import sys
import tempfile

ENV = "MARSWALK_GEAR_STATE_DIR"

if not os.environ.get(ENV):
    _tmp = tempfile.mkdtemp(prefix="marswalk-gear-test-")
    os.environ[ENV] = _tmp
    atexit.register(shutil.rmtree, _tmp, True)

# gear.tools loads the published kit when first imported; if that already happened
# with another state dir, load again so the tests start from the temp dir.
if "gear.tools" in sys.modules:
    sys.modules["gear.tools"].load_published()
