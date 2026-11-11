// The icons of the report categories, from Material Icons (Google, Apache License 2.0, see vendor/LICENSE-material-icons.txt).
// The paths are copied here, so nothing is loaded from Google. All icons are 24 x 24 and filled.
// To change an icon, take another one from https://github.com/google/material-design-icons (src/<group>/<name>/materialicons/24px.svg).
(function (root) {
  "use strict";

  var ICONS = {
    litter: { source: "action/delete", paths: ["M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"] },
    graffiti: { source: "image/brush", paths: ["M7 14c-1.66 0-3 1.34-3 3 0 1.31-1.16 2-2 2 .92 1.22 2.49 2 4 2 2.21 0 4-1.79 4-4 0-1.66-1.34-3-3-3zm13.71-9.37l-1.34-1.34c-.39-.39-1.02-.39-1.41 0L9 12.25 11.75 15l8.96-8.96c.39-.39.39-1.02 0-1.41z"] },
    street_light: { source: "action/lightbulb", paths: ["M9 21c0 .5.4 1 1 1h4c.6 0 1-.5 1-1v-1H9v1zm3-19C8.1 2 5 5.1 5 9c0 2.4 1.2 4.5 3 5.7V17c0 .5.4 1 1 1h6c.6 0 1-.5 1-1v-2.3c1.8-1.3 3-3.4 3-5.7 0-3.9-3.1-7-7-7z"] },
    playground_equipment: { source: "maps/attractions", paths: ["M10.43,18.75C10.8,18.29,11.37,18,12,18c0.63,0,1.19,0.29,1.56,0.75c0.39-0.09,0.76-0.21,1.12-0.36l-1.42-3.18 c-0.39,0.15-0.82,0.23-1.26,0.23c-0.46,0-0.9-0.09-1.3-0.25l-1.43,3.19C9.65,18.54,10.03,18.67,10.43,18.75z M5.15,10 c-0.16,0.59-0.25,1.21-0.25,1.85c0,0.75,0.12,1.47,0.33,2.15c0.63,0.05,1.22,0.4,1.56,0.99c0.33,0.57,0.35,1.23,0.11,1.79 c0.27,0.27,0.56,0.53,0.87,0.76l1.52-3.39v0c-0.47-0.58-0.75-1.32-0.75-2.13c0-1.89,1.55-3.41,3.46-3.41 c1.91,0,3.46,1.53,3.46,3.41c0,0.82-0.29,1.57-0.78,2.16l1.5,3.35c0.32-0.24,0.62-0.5,0.9-0.79c-0.22-0.55-0.2-1.2,0.12-1.75 c0.33-0.57,0.9-0.92,1.52-0.99c0.22-0.68,0.34-1.41,0.34-2.16c0-0.64-0.09-1.27-0.25-1.86c-0.64-0.04-1.26-0.39-1.6-1 c-0.36-0.62-0.35-1.36-0.03-1.95c-0.91-0.98-2.1-1.71-3.44-2.05C13.39,5.6,12.74,6,12,6c-0.74,0-1.39-0.41-1.74-1.01 C8.92,5.33,7.73,6.04,6.82,7.02C7.15,7.62,7.17,8.37,6.8,9C6.45,9.62,5.81,9.97,5.15,10z M3.85,9.58C3.07,8.98,2.83,7.88,3.34,7 c0.51-0.88,1.58-1.23,2.49-0.85c1.11-1.17,2.56-2.03,4.18-2.42C10.15,2.75,10.99,2,12,2c1.01,0,1.85,0.75,1.98,1.73 c1.63,0.39,3.07,1.24,4.18,2.42c0.91-0.38,1.99-0.03,2.49,0.85c0.51,0.88,0.27,1.98-0.51,2.58c0.23,0.77,0.35,1.58,0.35,2.42 s-0.12,1.65-0.35,2.42c0.78,0.6,1.02,1.7,0.51,2.58c-0.51,0.88-1.58,1.23-2.49,0.85c-0.4,0.43-0.85,0.81-1.34,1.15l1.34,3H16.3 l-0.97-2.17c-0.43,0.18-0.88,0.33-1.34,0.44C13.85,21.25,13.01,22,12,22c-1.01,0-1.85-0.75-1.98-1.73 C9.54,20.15,9.08,20,8.64,19.81L7.66,22H5.78l1.36-3.03c-0.47-0.33-0.91-0.71-1.3-1.12C4.92,18.23,3.85,17.88,3.34,17 c-0.51-0.88-0.27-1.98,0.51-2.58C3.62,13.65,3.5,12.84,3.5,12S3.62,10.35,3.85,9.58z"] },
    pothole: { source: "maps/edit_road", paths: ["M18 4 L16 4 L16 11.9 L18 9.9Z", "M4 4h2v16h-2z", "M10 4h2v4h-2z", "M10 10h2v4h-2z", "M10 16h2v4h-2z", "M22.56,12.59l-1.15-1.15c-0.59-0.59-1.54-0.59-2.12,0L14,16.73V20h3.27l5.29-5.29C23.15,14.12,23.15,13.17,22.56,12.59z M16.58,18.45h-1.03v-1.03L19,13.97L20.03,15L16.58,18.45z"] },
    tree: { source: "maps/park", paths: ["M17 12 L19 12 L12 2 L5.05 12 L7 12 L3.1 18 L10.02 18 L10.02 22 L13.98 22 L13.98 18 L21 18Z"] },
    other: { source: "action/help", paths: ["M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z"] },
  };
  // Icons for the page itself, not for a category
  var UI = {
    people: { source: "social/people", paths: ["M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"] },
    photo: { source: "image/image", paths: ["M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"] },
  };
  var SVG_NS = "http://www.w3.org/2000/svg";

  function known(category) {
    return Object.prototype.hasOwnProperty.call(ICONS, category) ? category : "other";
  }

  function build(icon, className) {
    var element = document.createElementNS(SVG_NS, "svg");
    element.setAttribute("viewBox", "0 0 24 24");
    element.setAttribute("aria-hidden", "true");
    element.setAttribute("focusable", "false");
    if (className) element.setAttribute("class", className);
    icon.paths.forEach(function (d) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "currentColor");
      element.appendChild(path);
    });
    return element;
  }

  // An <svg> element that has the colour of the text around it. Built with the DOM, not with HTML text.
  function svg(category, className) { return build(ICONS[known(category)], className); }
  function ui(name, className) { return build(UI[name], className); }

  var api = { ICONS: ICONS, UI: UI, known: known, svg: svg, ui: ui };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Icons = api;
})(this);
