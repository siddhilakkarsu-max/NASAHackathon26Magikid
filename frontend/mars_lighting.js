/* The Sun is drawn at a compressed distance so it can appear beside Mars in the overview. */
function createMarsLighting(viewer, ellipsoid, sunElement) {
  const { scene, camera } = viewer;
  const { globe, skyAtmosphere } = scene;
  const radius = ellipsoid.maximumRadius;
  const light = new Cesium.DirectionalLight({ direction: Cesium.Cartesian3.UNIT_X });
  scene.light = light;
  globe.lightingFadeOutDistance = radius * 1.12;
  globe.lightingFadeInDistance = radius * 1.8;
  globe.dynamicAtmosphereLighting = true;
  globe.dynamicAtmosphereLightingFromSun = false;
  skyAtmosphere.atmosphereRayleighCoefficient = new Cesium.Cartesian3(24e-6, 10e-6, 5e-6);
  skyAtmosphere.atmosphereMieCoefficient = new Cesium.Cartesian3(14e-6, 9e-6, 5e-6);
  skyAtmosphere.atmosphereMieScaleHeight = 5000;
  skyAtmosphere.atmosphereLightIntensity = 24;

  const sunPosition = new Cesium.Cartesian3();
  const look = new Cesium.Cartesian3();
  const pixel = new Cesium.Cartesian2();
  const globeHit = new Cesium.Cartesian3();
  scene.postRender.addEventListener(() => {
    let position;
    if (globe.enableLighting && camera.positionCartographic.height > radius * 0.2) {
      Cesium.Cartesian3.subtract(sunPosition, camera.positionWC, look);
      if (Cesium.Cartesian3.dot(look, camera.directionWC) > 0) {
        position = Cesium.SceneTransforms.worldToWindowCoordinates(scene, sunPosition, pixel);
      }
    }
    const inSky = position && position.x >= 0 && position.y >= 0
      && position.x <= scene.canvas.clientWidth && position.y <= scene.canvas.clientHeight
      && !camera.pickEllipsoid(position, ellipsoid, globeHit);
    sunElement.hidden = !inSky;
    if (inSky) {
      sunElement.style.transform = `translate(${position.x}px, ${position.y}px) translate(-50%, -50%)`;
    }
  });

  return {
    update(hour, ls, referenceLongitude) {
      // Same obliquity and seasonal declination as physics.sun_position.
      const obliquity = Cesium.Math.toRadians(25.19);
      const latitude = Math.asin(Math.sin(obliquity) * Math.sin(Cesium.Math.toRadians(ls)));
      const longitude = Cesium.Math.toRadians(referenceLongitude + 15 * (12 - hour));
      const towardsSun = ellipsoid.geodeticSurfaceNormalCartographic(
        new Cesium.Cartographic(longitude, latitude), sunPosition
      );
      Cesium.Cartesian3.negate(towardsSun, light.direction);
      Cesium.Cartesian3.multiplyByScalar(towardsSun, radius * 1.24, sunPosition);
      scene.requestRender();
    },
    setEnabled(enabled) {
      globe.enableLighting = enabled;
      skyAtmosphere.show = enabled;
      sunElement.hidden = true;
      scene.requestRender();
    },
  };
}
