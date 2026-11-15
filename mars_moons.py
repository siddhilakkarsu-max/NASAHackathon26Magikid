"""JPL MAR099 geometric moon states in rotating IAU_MARS coordinates.

Only fixed NASA URLs from the bundled manifest are downloaded. CSPICE's global
kernel pool is protected by one lock. No synthetic orbit is used on failure.
"""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import ssl
import threading
import urllib.request
from uuid import uuid4

import certifi
from fastapi import APIRouter, HTTPException, Query

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'moon_sources.json').read_text())
KERNELS = [f for f in MANIFEST['files'] if f['path'].startswith('data/moons/')]
FIRST_DAY, LAST_DAY = date(1995, 1, 2), date(2049, 12, 30)
STEP_SECONDS = 300
LOCK = threading.RLock()
_loaded = False
router = APIRouter(prefix='/api/moons', tags=['Mars moons'])
logger = logging.getLogger(__name__)


def _verified(path, spec):
    return (path.is_file() and path.stat().st_size == spec['bytes']
            and hashlib.sha256(path.read_bytes()).hexdigest() == spec['sha256'])


def _kernel(spec):
    path = ROOT / spec['path']
    if _verified(path, spec):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.download')
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        request = urllib.request.Request(spec['url'], headers={'User-Agent': 'Marswalk-Moons/1'})
        with urllib.request.urlopen(request, timeout=60, context=context) as response, temporary.open('wb') as output:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > spec['bytes']:
                    raise ValueError('Moon kernel size exceeds its verified manifest')
                output.write(chunk)
        if not _verified(temporary, spec):
            raise ValueError('Moon kernel checksum does not match its verified manifest')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _spice():
    global _loaded
    import spiceypy as spice
    # Always called with LOCK held: CSPICE is not thread-safe.
    if not _loaded:
        paths = [_kernel(spec) for spec in KERNELS]
        loaded = []
        try:
            for path in paths:
                spice.furnsh(str(path))
                loaded.append(path)
        except Exception:
            for path in loaded:
                spice.unload(str(path))
            raise
        _loaded = True
    return spice


def _day(value):
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, 'Use a UTC date in YYYY-MM-DD format.') from None
    if not FIRST_DAY <= day <= LAST_DAY:
        raise HTTPException(422, f'Moon ephemerides support {FIRST_DAY} through {LAST_DAY}.')
    return day


@lru_cache(maxsize=4)
def _daily(day):
    with LOCK:
        spice = _spice()
        start = spice.str2et(day.isoformat() + 'T00:00:00')
        end = spice.str2et((day + timedelta(days=1)).isoformat() + 'T00:00:00')
        epochs = [start + i * STEP_SECONDS for i in range(int((end - start) // STEP_SECONDS) + 1)]
        if end - epochs[-1] < 3:
            epochs[-1] = end
        else:
            epochs.append(end)
        # Sample in TDB, publish UTC including leap seconds. The browser uses
        # JulianDate/TAI elapsed seconds, not JavaScript's leap-blind Date arithmetic.
        times = [spice.et2utc(et, 'ISOC', 6) + 'Z' for et in epochs]
        # DE440 Sun states are included in MAR099s. Use the same UTC samples,
        # rotating frame and derivative convention as the moons for the overview.
        sun_samples = [[round(float(v) * 1000, 6) for v in
                        spice.spkezr('SUN', et, 'IAU_MARS', 'NONE', 'MARS')[0]] for et in epochs]
        moons = []
        for name in ['Phobos', 'Deimos']:
            samples = []
            for et in epochs:
                state, _ = spice.spkezr(name, et, 'IAU_MARS', 'NONE', 'MARS')
                q = spice.m2q(spice.pxform('IAU_' + name.upper(), 'IAU_MARS', et))
                samples.append([*[round(float(v) * 1000, 6) for v in state],
                                float(q[1]), float(q[2]), float(q[3]), float(q[0])])
            moons.append({'name': name, 'id': name.lower(), 'model': '/assets/moons/' + name.lower() + '.glb',
                          'model_scale': 1000, 'radii_m': (spice.bodvrd(name, 'RADII', 3)[1] * 1000).tolist(),
                          'samples': samples})
        return {'date': day.isoformat(), 'frame': 'IAU_MARS', 'center': 'Mars (499)',
                'ephemeris': 'JPL MAR099', 'aberration': 'NONE (geometric positions)',
                'orientation': 'IAU rotational models from pck00011.tpc',
                'units': {'position': 'm', 'velocity': 'm/s', 'quaternion': 'x,y,z,w'},
                'times': times, 'step_seconds': STEP_SECONDS, 'moons': moons,
                'sun': {'ephemeris': 'DE440 via MAR099s', 'samples': sun_samples}}


@router.get('/ephemeris')
def ephemeris(date_utc: str = Query(default=None, alias='date')):
    day = _day(date_utc or datetime.now(timezone.utc).date().isoformat())
    try:
        # Single-flight as well as thread safety: simultaneous cold requests must
        # not download or compute the same daily table repeatedly.
        with LOCK:
            return _daily(day)
    except Exception:
        logger.exception('NASA/JPL moon ephemeris unavailable')
        raise HTTPException(503, 'NASA/JPL moon data could not load. Retry when the source is available; no estimated orbit is substituted.') from None


@router.get('/sources')
def sources():
    return {'ephemeris': 'JPL MAR099 / DE440', 'frame': 'IAU_MARS',
            'first_date': str(FIRST_DAY), 'last_date': str(LAST_DAY),
            'files': MANIFEST['files'], 'model_credit': 'NASA/JPL-Caltech',
            'model_pages': ['https://science.nasa.gov/resource/phobos-mars-moon-3d-model/',
                            'https://science.nasa.gov/resource/deimos-mars-moon-3d-model/'],
            'method': 'SPICE geometric center-of-mass positions and velocities, transformed into rotating IAU_MARS; cubic Hermite interpolation of 300-second samples.',
            'limits': ['Positions are ephemeris predictions, not live observations or a spacecraft navigation product.',
                       'The animated overview uses DE440 Sun positions on the moon UTC clock. Its orbiting camera is a presentation choice; the Sun marker is not to scale.',
                       'Moon time is UTC and independent of the planner season and local solar time.',
                       'NASA model textures are visualization assets, not calibrated natural-color photometry. No false-color overlay is applied.',
                       'Model axes are aligned approximately to the IAU body frame; feature-level attitude and photometric phases/eclipses are not modeled.',
                       'Models and orbital distances use physical scale. Locator dots and labels are screen-size aids.',
                       'The pinned leap-second file must be updated if future leap seconds are announced.']}
