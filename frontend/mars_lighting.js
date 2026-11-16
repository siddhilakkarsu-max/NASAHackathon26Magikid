const marsShadowSource = `
  czm_material czm_getMaterial(czm_materialInput materialInput) {
    czm_material material = czm_getDefaultMaterial(materialInput);
    vec3 outward = normalize(-materialInput.positionToEyeEC - czm_view[3].xyz);
    float cosine = dot(outward, czm_lightDirectionEC);
    float night = 1.0 - smoothstep(-0.06, 0.22, cosine);
    vec2 uv = (gl_FragCoord.xy - czm_viewport.xy) / czm_viewport.zw;
    float distanceToPointer = length((uv - spotlightCenter) * spotlightScale);
    float reveal = 1.0 - smoothstep(0.18, 1.0, distanceToPointer);
    material.diffuse = vec3(0.0);
    material.alpha = 0.70 * shadowStrength * night * (1.0 - reveal);
    return material;
  }
`;

function createMarsLighting(viewer, ellipsoid, sunElement) {
  const { scene, camera } = viewer;
  const { globe, skyAtmosphere, canvas } = scene;
  const radius = ellipsoid.maximumRadius;
  const light = new Cesium.DirectionalLight({ direction: Cesium.Cartesian3.UNIT_X });
  scene.light = light;
  // Keep Cesium's directional atmosphere. The globe material supplies its own shadow.
  globe.lightingFadeOutDistance = radius * 10_000;
  globe.lightingFadeInDistance = radius * 20_000;
  globe.dynamicAtmosphereLighting = true;
  globe.dynamicAtmosphereLightingFromSun = false;
  skyAtmosphere.atmosphereRayleighCoefficient = new Cesium.Cartesian3(24e-6, 10e-6, 5e-6);
  skyAtmosphere.atmosphereMieCoefficient = new Cesium.Cartesian3(14e-6, 9e-6, 5e-6);
  skyAtmosphere.atmosphereMieScaleHeight = 5000;
  skyAtmosphere.atmosphereLightIntensity = 24;

  const sunPosition = new Cesium.Cartesian3();
  let sunAvailable = true;
  const look = new Cesium.Cartesian3();
  const pixel = new Cesium.Cartesian2();
  const globeHit = new Cesium.Cartesian3();
  const spotlightCenter = new Cesium.Cartesian2(-2, -2);
  const spotlightScale = new Cesium.Cartesian2(1, 1);
  const shadow = new Cesium.Material({
    fabric: {
      uniforms: { spotlightCenter, spotlightScale, shadowStrength: 0 },
      source: marsShadowSource,
    },
  });
  // Fabric owns the uniform objects after initialization.
  const uniforms = shadow.uniforms;
  canvas.addEventListener("pointermove", event => {
    if (event.pointerType === "touch") return;
    const bounds = canvas.getBoundingClientRect();
    const point = uniforms.spotlightCenter;
    point.x = (event.clientX - bounds.left) / bounds.width;
    point.y = 1 - (event.clientY - bounds.top) / bounds.height;
    scene.requestRender();
  });
  function hideSpotlight() {
    uniforms.spotlightCenter.x = -2;
    uniforms.spotlightCenter.y = -2;
    scene.requestRender();
  }
  canvas.addEventListener("pointerleave", hideSpotlight);
  canvas.addEventListener("pointercancel", hideSpotlight);
  window.addEventListener("blur", hideSpotlight);
  scene.preRender.addEventListener(() => {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const size = Cesium.Math.clamp(Math.min(width, height) * 0.15, 48, 115);
    uniforms.spotlightScale.x = width / size;
    uniforms.spotlightScale.y = height / size;
    const cameraDistance = Cesium.Cartesian3.magnitude(camera.positionWC) / radius;
    uniforms.shadowStrength = Cesium.Math.clamp((cameraDistance - 1.12) / (1.8 - 1.12), 0, 1);
  });
  scene.postRender.addEventListener(() => {
    let position;
    if (sunAvailable && globe.enableLighting && camera.positionCartographic.height > radius * 0.2) {
      Cesium.Cartesian3.subtract(sunPosition, camera.positionWC, look);
      if (Cesium.Cartesian3.dot(look, camera.directionWC) > 0) {
        position = Cesium.SceneTransforms.worldToWindowCoordinates(scene, sunPosition, pixel);
      }
    }
    const inSky = position && position.x >= 0 && position.y >= 0
      && position.x <= canvas.clientWidth && position.y <= canvas.clientHeight
      && !camera.pickEllipsoid(position, ellipsoid, globeHit);
    sunElement.hidden = !inSky;
    if (inSky) {
      sunElement.style.transform = `translate(${position.x}px, ${position.y}px) translate(-50%, -50%)`;
    }
  });

  return {
    clearEphemeris() { sunAvailable = false; sunElement.hidden = true; },
    updateFromPosition(position) {
      // The overview supplies the geometric Mars-to-Sun vector in metres,
      // expressed in the same rotating frame as the globe and moon positions.
      Cesium.Cartesian3.clone(position, sunPosition);
      sunAvailable = true;
      Cesium.Cartesian3.normalize(position, light.direction);
      Cesium.Cartesian3.negate(light.direction, light.direction);
      scene.requestRender();
    },
    update(hour, ls, referenceLongitude) {
      sunAvailable = true;
      // Same obliquity and seasonal declination as physics.sun_position.
      const obliquity = Cesium.Math.toRadians(25.19);
      const latitude = Math.asin(Math.sin(obliquity) * Math.sin(Cesium.Math.toRadians(ls)));
      const longitude = Cesium.Math.toRadians(referenceLongitude + 15 * (12 - hour));
      const towardsSun = ellipsoid.geodeticSurfaceNormalCartographic(
        new Cesium.Cartographic(longitude, latitude), sunPosition
      );
      Cesium.Cartesian3.negate(towardsSun, light.direction);
      Cesium.Cartesian3.multiplyByScalar(towardsSun, radius * 1000, sunPosition);
      scene.requestRender();
    },
    setEnabled(enabled) {
      globe.enableLighting = enabled;
      skyAtmosphere.show = enabled;
      globe.material = enabled ? shadow : undefined;
      sunElement.hidden = true;
      scene.requestRender();
    },
  };
}
