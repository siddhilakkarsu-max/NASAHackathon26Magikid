"""Offline regressions; numerical checks run when the pinned NAIF kernels exist."""
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scipy.interpolate import CubicHermiteSpline
import mars_moons as moons

app = FastAPI()
app.include_router(moons.router)
client = TestClient(app)
HAVE_KERNELS = all((moons.ROOT / k['path']).exists() for k in moons.KERNELS)


class MoonServiceTests(unittest.TestCase):
    def test_invalid_dates_are_rejected_before_any_download(self):
        with patch.object(moons, '_spice', side_effect=AssertionError('must not fetch')):
            for day in ['not-a-date', '2026-02-30', '1994-12-31', '2050-01-01']:
                self.assertEqual(client.get('/api/moons/ephemeris', params={'date': day}).status_code, 422)

    def test_unavailable_ephemeris_has_no_placeholder_states(self):
        moons._daily.cache_clear()
        with patch.object(moons, '_spice', side_effect=OSError('fixture source outage')):
            result = client.get('/api/moons/ephemeris?date=2026-11-15')
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('moons', result.json())

    def test_download_checksum_rejects_partial_or_corrupt_source(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(moons, 'ROOT', Path(directory)):
            spec = {'path': 'data/moons/test.bsp', 'bytes': 4, 'sha256': hashlib.sha256(b'good').hexdigest(),
                    'url': 'https://naif.jpl.nasa.gov/test-fixture'}
            for response in [b'bad', b'nope', b'oversized']:
                with patch('urllib.request.urlopen', return_value=io.BytesIO(response)):
                    with self.assertRaises(ValueError): moons._kernel(spec)
                self.assertFalse((Path(directory) / spec['path']).exists())
                self.assertEqual(list(Path(directory).rglob('*.download')), [])
            with patch('urllib.request.urlopen', return_value=io.BytesIO(b'good')):
                path = moons._kernel(spec)
            with patch('urllib.request.urlopen', side_effect=AssertionError('cached source must not download')):
                self.assertEqual(moons._kernel(spec), path)

    def test_sources_distinguish_physical_positions_from_visual_models(self):
        data = client.get('/api/moons/sources').json()
        self.assertEqual(data['frame'], 'IAU_MARS')
        self.assertTrue(any('independent' in line for line in data['limits']))
        for spec in moons.MANIFEST['files']:
            if spec['path'].endswith('.glb'):
                self.assertTrue(moons._verified(moons.ROOT / spec['path'], spec))


@unittest.skipUnless(HAVE_KERNELS, 'Download the verified NAIF kernels to run physical ephemeris checks')
class MoonPhysicsTests(unittest.TestCase):
    def test_sun_uses_same_epoch_units_and_rotating_frame_as_moons(self):
        data = moons.ephemeris('2026-11-15')
        with moons.LOCK:
            s = moons._spice()
            epochs = np.array([s.str2et(t.rstrip('Z')) for t in data['times']])
            states = np.array(data['sun']['samples'])
            self.assertEqual(states.shape, (len(epochs), 6))
            spline = CubicHermiteSpline(epochs - epochs[0], states[:, :3], states[:, 3:6])
            for i in [0, 144, len(epochs)-1]:
                expected = s.spkezr('SUN', epochs[i], 'IAU_MARS', 'NONE', 'MARS')[0] * 1000
                # Published UTC is rounded to microseconds. At solar distances,
                # Mars-frame rotation turns that rounding into several metres.
                np.testing.assert_allclose(states[i, :3], expected[:3], atol=20, rtol=0)
                np.testing.assert_allclose(states[i, 3:], expected[3:], atol=.002, rtol=0)
            for et in (epochs[1:] + epochs[:-1]) / 2:
                actual = s.spkezr('SUN', et, 'IAU_MARS', 'NONE', 'MARS')[0][:3] * 1000
                interpolated = spline(et - epochs[0])
                # Angular Sun direction, not metre-level solar ranging accuracy.
                self.assertLess(np.linalg.norm(actual / np.linalg.norm(actual) -
                                               interpolated / np.linalg.norm(interpolated)), 1e-7)

    def test_independent_horizons_reference_and_frame_units(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/mars_moons_horizons.json').read_text())
        with moons.LOCK:
            s = moons._spice()
            et = s.str2et(fixture['utc'].rstrip('Z'))
            rotation = s.sxform('J2000', 'IAU_MARS', et)
            data = moons.ephemeris('2026-11-15')
            for moon in data['moons']:
                reference = np.array(fixture['states'][moon['name']])
                actual = s.spkezr(moon['name'], et, 'J2000', 'NONE', 'MARS')[0]
                # Horizons UT and SPICE UTC differ slightly here; this is an
                # agreement check at one epoch, not an ephemeris accuracy claim.
                self.assertLess(np.linalg.norm(actual[:3] - reference[:3]) * 1000, 0.2)
                index = min(range(len(data['times'])), key=lambda i: abs(s.str2et(data['times'][i].rstrip('Z')) - et))
                self.assertLess(abs(s.str2et(data['times'][index].rstrip('Z')) - et), .01)
                np.testing.assert_allclose(moon['samples'][index][:6], rotation @ reference * 1000, atol=1, rtol=0)

    def test_hermite_interpolation_preserves_measured_state_between_samples(self):
        data = moons.ephemeris('2026-11-15')
        worst = 0
        with moons.LOCK:
            s = moons._spice()
            times = np.array([s.str2et(t.rstrip('Z')) for t in data['times']])
            for moon in data['moons']:
                states = np.array(moon['samples'])
                spline = CubicHermiteSpline(times-times[0], states[:, :3], states[:, 3:6])
                for et in ((times[1:] + times[:-1]) / 2):
                    actual = s.spkezr(moon['name'], et, 'IAU_MARS', 'NONE', 'MARS')[0][:3]*1000
                    worst = max(worst, np.linalg.norm(spline(et-times[0])-actual))
        self.assertLess(worst, 1.0, f'Interpolation departure from direct SPICE: {worst} m')

    def test_leap_second_day_and_supported_edges_have_ordered_full_coverage(self):
        with moons.LOCK:
            s = moons._spice()
            for day in ['1995-01-02', '2016-12-31', '2049-12-30']:
                data = moons.ephemeris(day)
                et = np.array([s.str2et(t.rstrip('Z')) for t in data['times']])
                self.assertTrue(np.all(np.diff(et) > 298))
                self.assertTrue(np.all(np.diff(et) < 302))
                self.assertLess(abs((et[-1]-et[0]) - (86401 if day == '2016-12-31' else 86400)), .01)
                for moon in data['moons']:
                    states = np.array(moon['samples'])
                    self.assertEqual(states.shape, (len(et), 10))
                    self.assertTrue(np.isfinite(states).all())
                    np.testing.assert_allclose(np.linalg.norm(states[:, 6:], axis=1), 1, atol=1e-12)

    def test_relative_motion_accounts_for_mars_rotation(self):
        data = moons.ephemeris('2026-11-15')
        for moon in data['moons']:
            states = np.array(moon['samples'])
            longitude = np.unwrap(np.arctan2(states[:, 1], states[:, 0]))
            degrees = np.degrees(longitude[-1]-longitude[0])
            if moon['id'] == 'phobos':
                self.assertTrue(700 < degrees < 850, degrees)
            else:
                self.assertTrue(-80 < degrees < -40, degrees)
