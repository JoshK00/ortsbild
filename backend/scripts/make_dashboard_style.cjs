// Write the style of the dashboard map: dashboard/map/style.json (dark Protomaps basemap, German labels).
//
// The style is made from the open source package @protomaps/basemaps (BSD-3). Run it with node, from the repo root:
//   npm pack @protomaps/basemaps@5.7.2 && mkdir -p /tmp/basemaps && tar -xzf protomaps-basemaps-5.7.2.tgz -C /tmp/basemaps
//   node backend/scripts/make_dashboard_style.cjs /tmp/basemaps/package
//
// The addresses of the tiles, the glyphs and the sprites hold the word __ORIGIN__: the page replaces it with its own
// address, so every file of the map comes from our own server and nothing from a third party.
const fs = require("fs");
const path = require("path");

// How much bigger the labels are than in the original style (place names, streets, waters)
const LABEL_SCALE = 1.35;
const TILES_FILE = "/tiles/stuttgart.pmtiles";

const packageDir = process.argv[2];
if (!packageDir) {
  console.error("usage: node make_dashboard_style.cjs <folder of the unpacked @protomaps/basemaps package>");
  process.exit(1);
}
const { layers, namedFlavor } = require(path.join(packageDir, "dist", "cjs", "index.cjs"));

// Make the numbers in a text-size expression bigger. The zoom has to stay the input of the top level interpolate/step,
// so only the output values are scaled.
function scale(value) {
  if (typeof value === "number") return value * LABEL_SCALE;
  if (!Array.isArray(value)) return value;
  const out = value.slice();
  if (value[0] === "interpolate") {
    for (let i = 4; i < out.length; i += 2) out[i] = scale(out[i]);
  } else if (value[0] === "step") {
    out[2] = scale(out[2]);
    for (let i = 4; i < out.length; i += 2) out[i] = scale(out[i]);
  } else if (value[0] === "case") {
    for (let i = 2; i < out.length - 1; i += 2) out[i] = scale(out[i]);
    out[out.length - 1] = scale(out[out.length - 1]);
  }
  return out;
}

const styleLayers = layers("protomaps", namedFlavor("dark"), { lang: "de" }).map((layer) => {
  if (layer.layout && layer.layout["text-size"] !== undefined) {
    layer.layout["text-size"] = scale(layer.layout["text-size"]);
  }
  return layer;
});

const style = {
  version: 8,
  name: "Ortsbild dark",
  glyphs: "__ORIGIN__/dashboard/map/fonts/{fontstack}/{range}.pbf",
  sprite: "__ORIGIN__/dashboard/map/sprites/dark",
  sources: {
    protomaps: {
      type: "vector",
      url: "pmtiles://__ORIGIN__" + TILES_FILE,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
  layers: styleLayers,
};

const target = path.join(__dirname, "..", "dashboard", "map", "style.json");
fs.writeFileSync(target, JSON.stringify(style));
console.log(`wrote ${styleLayers.length} layers to ${target}`);

// The same map as an aerial photo (tiles/stuttgart_luftbild.pmtiles, made by build_aerial_tiles.py): the photo is the ground,
// only the names of the places, streets and waters of the vector map lie above it. The photo is a little darker, so the markers stand out.
const LABELS = ["places_subplace", "places_locality", "roads_labels_major", "roads_labels_minor", "water_label_lakes", "water_waterway_label"];
const aerial = {
  version: 8,
  name: "Ortsbild aerial",
  glyphs: style.glyphs,
  sprite: style.sprite,
  sources: {
    protomaps: style.sources.protomaps,
    aerial: { type: "raster", url: "pmtiles://__ORIGIN__/tiles/stuttgart_luftbild.pmtiles", tileSize: 256, maxzoom: 17 },
  },
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#2b2b2b" } },
    { id: "aerial", type: "raster", source: "aerial", paint: { "raster-brightness-max": 0.82, "raster-saturation": -0.15, "raster-contrast": 0.08, "raster-fade-duration": 150 } },
    // the names are white with a soft dark edge, so they can be read on every kind of photo
    ...styleLayers.filter((layer) => LABELS.includes(layer.id)).map((layer) => ({
      ...layer,
      paint: { ...layer.paint, "text-color": "rgba(255, 255, 255, 0.6)", "text-halo-color": "rgba(0, 0, 0, 0.35)", "text-halo-width": 1.2, "text-halo-blur": 0.5 },
    })),
  ],
};
const aerialTarget = path.join(__dirname, "..", "dashboard", "map", "style_luftbild.json");
fs.writeFileSync(aerialTarget, JSON.stringify(aerial));
console.log(`wrote ${aerial.layers.length} layers to ${aerialTarget}`);
