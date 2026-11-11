// The dashboard: a map over the whole window and a list of reports, sorted by a priority (a suggestion, shown as a dot, never as points).
// Everything that comes from the server is put on the page with textContent, never as HTML:
// the address is typed by the user and the text of a report is the user's, so they are untrusted.
(function () {
  "use strict";

  var REFRESH_MS = 30000;
  var CATEGORY_NAMES = {
    litter: "Müll", graffiti: "Graffiti", street_light: "Straßenlaterne", playground_equipment: "Spielgerät",
    pothole: "Schlagloch", tree: "Baum", other: "Sonstiges",
  };
  var STATUS_NAMES = { received: "Eingegangen", in_progress: "In Bearbeitung", done: "Erledigt" };
  var TIER_NAMES = { high: "Hoch", medium: "Mittel", low: "Niedrig", done: "Erledigt" };
  var TIER_COLORS = { high: "--high", medium: "--medium", low: "--low", done: "--done" };
  // The map is a vector map of the region around Stuttgart. Tiles, fonts and symbols all come from our own server, so
  // no visitor sends an address or a map section to a third party (see docs/dashboard-plan.md).
  var STYLE_URL = "map/style_luftbild.json"; // the aerial photo; map/style.json is the dark vector map
  var START_VIEW = { center: [48.7758, 9.1829], zoom: 13 };
  var MAP_BOUNDS = [[48.685, 9.03], [48.87, 9.325]]; // the city: the aerial photo (and nothing outside) is in the map file
  var ATTRIBUTION = "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors";
  var PROTOMAPS = "<a href=\"https://protomaps.com\">Protomaps</a>";
  var AERIAL = "Luftbild: <a href=\"https://www.lgl-bw.de\">LGL-BW</a>, <a href=\"https://www.govdata.de/dl-de/by-2-0\">dl-de/by-2-0</a>";

  var PHONE_QUERY = "(max-width: 760px)"; // the same number as in style.css
  var TOP_HEIGHT = 8 + 36; // the mode pill above the map, without the safe area
  var params = new URLSearchParams(window.location.search);
  // Inside the iOS app the page is opened with ?app=1 (or the app puts "OrtsbildApp" into the user agent). The page then
  // shows no link that would take the web view away from the dashboard.
  var IN_APP = params.get("app") === "1" || /OrtsbildApp/.test(navigator.userAgent);

  var WEIGHTS = Score.DEFAULT_WEIGHTS; // the fixed weights of the hidden ranking, nothing in the page shows or changes them

  var state = {
    cases: [],
    selected: null,
    live: true,
    firstFit: true,
    loading: true, // the first answer of the server is on its way
    error: false, // it did not come
    listSnap: "peek", // where the list sheet rests on a phone: peek, half or full
    detailSnap: "half", // and the card: half or full
    wantedCase: null, // the case of the link (#case=...), selected as soon as it is in the data
    hiddenCats: {}, // the filter: categories and priorities that are switched off in the dropdown
    hiddenTiers: {},
    filterOpen: false,
  };
  var map, mini, miniFrame, markerLayer, markers = {};
  var detailShownFor = null, opener = null, lastAnnouncement = "";

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function byId(id) { return document.getElementById(id); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function cssColor(variable) { return getComputedStyle(document.documentElement).getPropertyValue(variable).trim(); }
  function categoryName(key) { return CATEGORY_NAMES[key] || "Sonstiges"; }
  function isPhone() { return window.matchMedia(PHONE_QUERY).matches; }
  function canHover() { return window.matchMedia("(hover: hover)").matches; }
  function announce(text) {
    if (text === lastAnnouncement) return;
    lastAnnouncement = text;
    byId("announce").textContent = text;
  }

  // The icon of a category in a round badge. The badge is white, the icon is the category, the small dot in the corner is the priority.
  function badge(category, tier, extraClass) {
    var known = Icons.known(category);
    var node = el("span", "cat-badge cat-" + known + (tier === "done" ? " is-done" : "") + (extraClass ? " " + extraClass : ""));
    node.appendChild(Icons.svg(known));
    node.appendChild(el("span", "tier-pip tier-" + tier));
    return node;
  }

  // Where a photo may come from: only the public endpoint of our own server
  var PHOTO_PREFIXES = ["/v1/public/"];

  // The photo of a report, or a placeholder while there is none (or while it cannot be loaded).
  // size is "thumb" (list) or "large" (card). The address of a photo has to be one of ours.
  function photoFrame(report, size) {
    var frame = el("span", "photo-frame " + size);
    function placeholder() {
      clear(frame);
      frame.classList.add("is-placeholder");
      frame.appendChild(Icons.ui("photo"));
      if (size === "large") frame.appendChild(el("span", "photo-caption", "Noch kein Foto"));
    }
    if (typeof report.photo_url === "string" && PHOTO_PREFIXES.some(function (prefix) { return report.photo_url.indexOf(prefix) === 0; })) {
      var image = el("img");
      image.src = report.photo_url;
      image.alt = size === "large" ? "Bereinigtes Foto der Meldung (Gesichter und Kennzeichen entfernt)" : "";
      if (size === "thumb") image.loading = "lazy";
      image.addEventListener("error", placeholder);
      frame.appendChild(image);
    } else {
      placeholder();
    }
    return frame;
  }

  // "3 Meldungen" (every report of a person is one vote for the case). Shown in every tile, also when there is only one.
  function reportsText(count) {
    var n = Math.max(1, count || 1);
    return n + (n === 1 ? " Meldung" : " Meldungen");
  }

  function countPill(report) {
    var pill = el("span", "count-pill");
    pill.appendChild(Icons.ui("people"));
    // only the number is shown, the words are for a screen reader ("3 Meldungen")
    pill.appendChild(el("span", null, String(Math.max(1, report.reports_count || 1))));
    pill.appendChild(el("span", "sr-only", reportsText(report.reports_count)));
    return pill;
  }

  function ageText(report) {
    var days = Score.ageDays(report, Date.now());
    if (days < 1 / 24) return "gerade eben";
    if (days < 1) return "vor " + Math.round(days * 24) + " Std.";
    var whole = Math.floor(days);
    return whole === 1 ? "gestern" : "vor " + whole + " Tagen";
  }

  // ---------------------------------------------------------------- data

  function loadLive() {
    return fetch("/v1/public/cases", { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("status " + response.status);
      return response.json();
    }).then(function (body) { return body.cases; });
  }

  function setMode(text, kind, banner) {
    var mode = byId("mode");
    mode.textContent = text;
    mode.className = "glass pill " + kind;
    var box = byId("banner");
    box.hidden = !banner;
    box.textContent = banner || "";
    // on a phone the longer text is the first line of the sheet
    var note = byId("sheet-note");
    note.hidden = !banner;
    note.textContent = banner || "";
  }

  function useLive(cases) {
    state.live = true;
    state.loading = false;
    state.error = false;
    state.cases = cases;
    setMode("Live", "live", "");
    render();
    tryWantedCase();
  }

  function failed() {
    if (state.cases.length > 0 && state.live) {
      // the last reports stay on the screen, the mode says that they may be old
      setMode("Live: keine Verbindung", "warn", "Der Server hat nicht geantwortet. Angezeigt werden die zuletzt geladenen Meldungen.");
      return;
    }
    state.loading = false;
    state.error = true;
    setMode("Keine Verbindung", "warn", "Die Meldungen konnten nicht geladen werden.");
    render();
  }

  function refresh() {
    return loadLive().then(useLive).catch(failed);
  }

  function retry() {
    state.loading = true;
    state.error = false;
    setMode("Lädt", "", "");
    render();
    refresh();
  }

  // ---------------------------------------------------------------- derived

  function ranked(cases) {
    var now = Date.now();
    return cases.map(function (report) {
      return { report: report, score: Score.score(report, WEIGHTS, now), tier: Score.tier(report, WEIGHTS, now) };
    }).sort(function (a, b) {
      var doneA = a.tier === "done" ? 1 : 0, doneB = b.tier === "done" ? 1 : 0;
      return doneA - doneB || b.score - a.score || Date.parse(a.report.created_at) - Date.parse(b.report.created_at);
    });
  }

  // The town that most reports are in, from the last part of the address ("48143 Münster" gives "Münster")
  function townOf(cases) {
    var counts = {};
    cases.forEach(function (report) {
      var parts = String(report.address || "").split(",");
      var town = parts[parts.length - 1].trim().replace(/^\d+\s*/, "");
      if (town) counts[town] = (counts[town] || 0) + 1;
    });
    var best = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0];
    return best || "Keine Meldungen";
  }

  // ---------------------------------------------------------------- render

  function render() {
    var all = ranked(state.cases);
    var items = all.filter(function (item) { return !state.hiddenCats[item.report.category] && !state.hiddenTiers[item.tier]; });
    if (state.selected && !items.some(function (item) { return item.report.id === state.selected; })) state.selected = null; // a filter hid the open report
    renderFilter(all);
    renderList(items);
    renderMap(items);
    renderDetail();
    renderEmpty(items);
    renderSummary(items.length);
    byId("place-name").textContent = townOf(state.cases);
  }

  // "4 Fälle" (a case is what the list shows: one defect with all its reports). Also said to screen readers when it changes.
  function renderSummary(shown) {
    var text;
    if (state.loading) text = "Meldungen werden geladen";
    else if (state.error) text = "";
    else if (filterCount() > 0) text = shown + " von " + state.cases.length + (state.cases.length === 1 ? " Fall" : " Fällen");
    else text = state.cases.length + (state.cases.length === 1 ? " Fall" : " Fälle");
    byId("sheet-count").textContent = state.loading ? "" : text;
    if (!state.loading) announce(state.error ? "Die Meldungen konnten nicht geladen werden" : text);
  }

  // The dropdown of the filter: which categories and which priorities are shown (list and map). Everything is on at the start.
  function filterCount() {
    return Object.keys(state.hiddenCats).length + Object.keys(state.hiddenTiers).length;
  }

  function renderFilter(all) {
    var box = byId("counts");
    clear(box);
    box.hidden = state.loading || all.length === 0;
    if (box.hidden) return;
    var button = el("button", "filter-button glass");
    button.type = "button";
    button.setAttribute("aria-expanded", String(state.filterOpen));
    button.setAttribute("aria-controls", "filter-panel");
    button.appendChild(el("span", null, "Filter"));
    if (filterCount() > 0) button.appendChild(el("span", "filter-badge", String(filterCount())));
    button.appendChild(el("span", "chevron"));
    button.addEventListener("click", function () { state.filterOpen = !state.filterOpen; renderFilter(all); });
    box.appendChild(button);
    if (!state.filterOpen) return;

    var panel = el("div", "filter-panel");
    panel.id = "filter-panel";
    function group(title, entries, hidden) {
      var fieldset = el("fieldset", "filter-group");
      fieldset.appendChild(el("legend", null, title));
      entries.forEach(function (entry) {
        var label = el("label", "filter-option");
        var input = el("input");
        input.type = "checkbox";
        input.checked = !hidden[entry.key];
        input.addEventListener("change", function () {
          if (input.checked) delete hidden[entry.key]; else hidden[entry.key] = true;
          render();
        });
        label.appendChild(input);
        if (entry.tier) label.appendChild(el("span", "dot tier-" + entry.tier));
        label.appendChild(el("span", "filter-name", entry.name));
        label.appendChild(el("span", "filter-count", String(entry.count)));
        fieldset.appendChild(label);
      });
      return fieldset;
    }
    var catCounts = {}, tierCounts = { high: 0, medium: 0, low: 0, done: 0 };
    all.forEach(function (item) {
      catCounts[item.report.category] = (catCounts[item.report.category] || 0) + 1;
      tierCounts[item.tier] += 1;
    });
    var cats = Object.keys(catCounts).sort(function (x, y) { return categoryName(x).localeCompare(categoryName(y), "de"); })
      .map(function (key) { return { key: key, name: categoryName(key), count: catCounts[key] }; });
    var tiers = ["high", "medium", "low", "done"].map(function (tier) { return { key: tier, tier: tier, name: TIER_NAMES[tier], count: tierCounts[tier] }; });
    panel.appendChild(group("Kategorie", cats, state.hiddenCats));
    panel.appendChild(group("Priorität", tiers, state.hiddenTiers));
    if (filterCount() > 0) {
      var reset = el("button", "filter-reset", "Zurücksetzen");
      reset.type = "button";
      reset.addEventListener("click", function () { state.hiddenCats = {}; state.hiddenTiers = {}; render(); });
      panel.appendChild(reset);
    }
    box.appendChild(panel);
  }

  function renderList(items) {
    var list = byId("list");
    var scroll = list.scrollTop;
    clear(list);
    list.setAttribute("aria-busy", String(state.loading));
    if (state.loading) {
      for (var n = 0; n < 4; n++) {
        var placeholder = el("li", "glass row skeleton");
        placeholder.setAttribute("aria-hidden", "true");
        placeholder.appendChild(el("span", "sk thumb"));
        var lines = el("span", "sk-main");
        lines.appendChild(el("span", "sk line"));
        lines.appendChild(el("span", "sk line"));
        placeholder.appendChild(lines);
        list.appendChild(placeholder);
      }
      return;
    }
    items.forEach(function (item) {
      var report = item.report;
      var li = el("li");
      var row = el("button", "glass row");
      row.type = "button";
      row.setAttribute("data-id", report.id);
      row.setAttribute("aria-pressed", String(state.selected === report.id));
      row.appendChild(photoFrame(report, "thumb"));
      var main = el("span", "row-main");
      main.appendChild(badge(report.category, item.tier));
      main.appendChild(el("span", "title", categoryName(report.category)));
      main.appendChild(countPill(report));
      var meta = el("span", "meta");
      meta.appendChild(el("span", "tier-text tier-" + item.tier, TIER_NAMES[item.tier]));
      var rest = " · " + ageText(report) + " · " + (report.address || "Keine Adresse");
      meta.appendChild(document.createTextNode(rest));
      main.appendChild(meta);
      row.appendChild(main);
      // on a big screen a second click on the open tile closes it
      row.addEventListener("click", function () { if (!isPhone() && state.selected === report.id) deselect(); else select(report.id); });
      li.appendChild(row);
      list.appendChild(li);
    });
    list.scrollTop = scroll;
  }

  function renderMap(items) {
    markerLayer.clearLayers();
    markers = {};
    items.forEach(function (item) {
      var report = item.report;
      if (typeof report.lat !== "number" || typeof report.lon !== "number") return;
      var selected = state.selected === report.id;
      // Every badge is 30 px and has the same size, the votes are shown in the list and in the card.
      // Around it is an invisible area of 44 px, so a finger hits it.
      var size = 36, hit = 48;
      if (selected) {
        // the dotted ring that marks the report that is open
        L.circleMarker([report.lat, report.lon], {
          radius: size / 2 + 9, color: cssColor("--ring"), weight: 2, dashArray: "2 6", lineCap: "round", fill: false, interactive: false,
        }).addTo(markerLayer);
      }
      var name = categoryName(report.category) + ", Priorität " + TIER_NAMES[item.tier].toLowerCase();
      var area = el("span", "marker-hit");
      area.appendChild(badge(report.category, item.tier, "marker-badge" + (selected ? " selected" : "")));
      var label = el("span", "marker-label"); // a small label under the badge: the votes of the case
      label.appendChild(Icons.ui("people"));
      label.appendChild(el("span", null, String(Math.max(1, report.reports_count || 1))));
      area.appendChild(label);
      area.appendChild(el("span", "sr-only", name)); // the name of the button for a screen reader
      var marker = L.marker([report.lat, report.lon], {
        icon: L.divIcon({ html: area, className: "marker-wrap", iconSize: [hit, hit], iconAnchor: [hit / 2, hit / 2] }),
        zIndexOffset: selected ? 100000 : Math.round(item.score * 10),
      });
      // a tooltip needs a mouse, on a touch screen the sheet says it
      if (canHover()) marker.bindTooltip(categoryName(report.category) + " · " + TIER_NAMES[item.tier], { direction: "top", offset: [0, -size / 2] });
      marker.on("click", function () { select(report.id); });
      marker.addTo(markerLayer);
      markers[report.id] = marker;
    });
    if (state.firstFit && items.length) {
      state.firstFit = false;
      fitAll(false);
    }
  }

  function renderEmpty(items) {
    var box = byId("empty");
    clear(box);
    box.hidden = state.loading || items.length > 0;
    if (box.hidden) return;
    function button(label, primary, handler) {
      var node = el("button", "btn" + (primary ? " primary" : ""), label);
      node.type = "button";
      node.addEventListener("click", handler);
      return node;
    }
    var actions = el("div", "actions");
    if (state.error) {
      box.appendChild(el("p", "title", "Die Meldungen konnten nicht geladen werden"));
      box.appendChild(el("p", "hint", "Prüfe die Verbindung und versuche es erneut."));
      actions.appendChild(button("Erneut versuchen", true, retry));
    } else if (state.cases.length > 0) {
      box.appendChild(el("p", "title", "Keine Meldung passt zum Filter"));
      actions.appendChild(button("Filter zurücksetzen", true, function () { state.hiddenCats = {}; state.hiddenTiers = {}; render(); }));
    } else if (state.cases.length === 0) {
      box.appendChild(el("p", "title", "Noch keine Meldungen"));
      box.appendChild(el("p", "hint", "Eine Meldung erscheint hier, sobald sie in der App freigegeben ist."));
    }
    box.appendChild(actions);
  }

  function renderDetail() {
    var panel = byId("detail");
    var box = byId("detail-body");
    var report = state.cases.find(function (r) { return r.id === state.selected; });
    document.body.classList.toggle("has-detail", !!report);
    if (!report) {
      panel.hidden = true;
      clear(box);
      detailShownFor = null;
      return;
    }
    // a refresh builds the card again, the reader stays where they were
    var scroll = detailShownFor === report.id ? box.scrollTop : 0;
    clear(box);
    panel.hidden = false;

    var head = el("div", "detail-head");
    var tier = Score.tier(report, WEIGHTS, Date.now());
    head.appendChild(badge(report.category, tier));
    head.appendChild(el("h2", null, categoryName(report.category)));
    var close = el("button", "close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Meldung schließen");
    close.addEventListener("click", function () { deselect(); });
    head.appendChild(close);
    box.appendChild(head);

    box.appendChild(photoFrame(report, "large"));

    var facts = el("dl", "facts");
    function fact(name, value) {
      if (value === null || value === undefined || value === "") return;
      var row = el("div", "fact");
      row.appendChild(el("dt", null, name));
      var dd = el("dd");
      if (value instanceof Node) dd.appendChild(value); else dd.textContent = value;
      row.appendChild(dd);
      facts.appendChild(row);
    }
    fact("Status", STATUS_NAMES[report.status] || report.status);
    fact("Art", report.lane === "hazard" ? "Gefahr" : "Ärgernis");
    fact("Gemeldet", ageText(report));
    if (report.reports_count > 1) fact("Meldungen", report.reports_count + " Meldungen zum selben Mangel");
    fact("Zuständige Stelle", report.authority);
    fact("Adresse", report.address);
    if (typeof report.lat === "number") {
      var position = report.lat.toFixed(6).replace(".", ",") + " / " + report.lon.toFixed(6).replace(".", ",");
      if (IN_APP) {
        // a link would take the web view away from the dashboard
        fact("Position", position);
      } else {
        var link = el("a", null, position);
        link.href = "https://www.openstreetmap.org/?mlat=" + report.lat + "&mlon=" + report.lon + "#map=19/" + report.lat + "/" + report.lon;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        fact("Position", link);
      }
    }
    if (typeof report.accuracy_m === "number") fact("GPS-Genauigkeit", "etwa " + Math.round(report.accuracy_m) + " m");
    box.appendChild(facts);

    if (report.text) {
      box.appendChild(el("h3", null, "Beschreibung"));
      box.appendChild(el("p", "text", report.text));
    }

    if (report.draft) {
      box.appendChild(el("h3", null, "Nachricht an die Behörde"));
      box.appendChild(el("p", "message", (report.draft.subject ? report.draft.subject + "\n\n" : "") + (report.draft.body || "")));
      if (report.draft.contact) {
        box.appendChild(el("p", "hint", "Kontakt (" + report.draft.contact.type + "): " + report.draft.contact.target));
      }
    }
    box.scrollTop = scroll;
    detailShownFor = report.id;
  }

  // ---------------------------------------------------------------- map

  // What the sheets and the pill at the top cover of the map, so the markers are not hidden behind them
  function mapPadding() {
    if (!isPhone()) return { topLeft: [450, 100], bottomRight: [state.selected ? 480 : 90, 90] } // the list on the left, the card of the open report on the right; // the card of the report on the left, the glass panel on the right
    var points = sheetPoints();
    var covered = Math.min(state.selected ? sheetHeight("detail", state.detailSnap) : sheetHeight("list", state.listSnap), points.half);
    return { topLeft: [30, insets().top + TOP_HEIGHT], bottomRight: [30, covered + 24] };
  }

  function fitAll(animate) {
    var points = state.cases.filter(function (report) { return typeof report.lat === "number"; })
      .map(function (report) { return [report.lat, report.lon]; });
    if (!points.length) return;
    var padding = mapPadding();
    map.fitBounds(points, { paddingTopLeft: padding.topLeft, paddingBottomRight: padding.bottomRight, maxZoom: 17, animate: animate });
  }

  function syncHash(id) {
    try {
      window.history.replaceState(null, "", window.location.pathname + window.location.search + (id ? "#case=" + encodeURIComponent(id) : ""));
    } catch (error) { /* a page that is not allowed to change its address still works */ }
  }

  // Opens the card of a case. `fromLink` is true when the address of the page asked for it (then the focus is not moved
  // and the address is left as it is).
  function select(id, fromLink) {
    state.wantedCase = null;
    if (!state.selected) opener = document.activeElement;
    if (state.selected !== id) state.detailSnap = "half";
    state.selected = id;
    if (!fromLink) syncHash(id);
    render();
    applySheets();
    var marker = markers[id];
    if (marker) {
      // keep the marker clear of the list and the card
      var padding = mapPadding();
      map.panInside(marker.getLatLng(), { paddingTopLeft: isPhone() ? padding.topLeft : [450, 100], paddingBottomRight: isPhone() ? padding.bottomRight : [480, 140] });
    }
    var close = byId("detail-body").querySelector(".close");
    if (!fromLink && close) close.focus({ preventScroll: true });
  }

  function deselect() {
    if (!state.selected) return;
    var id = state.selected;
    state.selected = null;
    state.wantedCase = null;
    syncHash(null);
    render();
    applySheets();
    // the focus goes back to where the card was opened
    var row = byId("list").querySelector('[data-id="' + id + '"]');
    var back = row || (opener && document.body.contains(opener) ? opener : null);
    if (back) back.focus({ preventScroll: true });
  }

  // The link of the page names a case (#case=<id>), the app uses it after a report was approved. The case may not be in the
  // data yet (the server keeps the list for a short time), so it is tried again with every refresh.
  function wantedFromHash() {
    var found = /^#case=([A-Za-z0-9_-]{1,64})$/.exec(window.location.hash);
    return found ? found[1] : null;
  }

  function tryWantedCase() {
    var id = state.wantedCase;
    if (id && state.cases.some(function (report) { return report.id === id; })) select(id, true);
  }

  function onHashChange() {
    var id = wantedFromHash();
    if (id) {
      state.wantedCase = id;
      tryWantedCase();
    } else if (state.selected) {
      deselect();
    }
  }

  // ---------------------------------------------------------------- sheets (phone)
  // On a phone the list and the card are sheets from the bottom edge. A sheet rests at a stop (peek, half, full) and the finger
  // can drag it, or a tap on the handle moves it to the next stop. The stops are worked out in sheet.js. The height of the sheet
  // that is open is the CSS variable --sheet-h, the buttons and the map credit above it follow that variable.

  // The safe areas of the phone (notch and home bar), measured with a hidden box that has them as padding
  function insets() {
    var style = getComputedStyle(byId("insets"));
    return { top: parseFloat(style.paddingTop) || 0, bottom: parseFloat(style.paddingBottom) || 0 };
  }

  function sheetPoints() {
    var space = insets();
    return Sheet.snapPoints(window.innerHeight, space.top + TOP_HEIGHT - 20, space.bottom);
  }

  function sheetHeight(kind, snap) {
    return snap === "closed" ? 0 : sheetPoints()[snap];
  }

  function setSheetHeight(pixels) {
    document.documentElement.style.setProperty("--sheet-h", Math.round(pixels) + "px");
  }

  // Puts the sheets where the state says: the card if a case is open, the list otherwise
  function applySheets() {
    var root = document.documentElement;
    if (!isPhone()) {
      root.style.removeProperty("--sheet-h");
      delete document.body.dataset.snap;
      return;
    }
    var kind = state.selected ? "detail" : "list";
    var snap = kind === "detail" ? state.detailSnap : state.listSnap;
    setSheetHeight(sheetHeight(kind, snap));
    document.body.dataset.snap = snap;
    byId("list-sheet").setAttribute("data-snap", state.listSnap);
    byId("detail").setAttribute("data-snap", state.detailSnap);
    var list = byId("list-handle");
    list.setAttribute("aria-expanded", String(state.listSnap !== "peek"));
    list.setAttribute("aria-label", state.listSnap === "full" ? "Liste verkleinern" : "Liste vergrößern");
    var detail = byId("detail-handle");
    detail.setAttribute("aria-expanded", String(state.detailSnap === "full"));
    detail.setAttribute("aria-label", state.detailSnap === "full" ? "Weniger von der Meldung zeigen" : "Die ganze Meldung zeigen");
  }

  function setSnap(kind, snap) {
    if (kind === "detail") state.detailSnap = snap; else state.listSnap = snap;
    applySheets();
  }

  // The handle of a sheet: drag with the finger, tap or press Enter to go to the next stop, arrow keys to go up and down
  function attachHandle(handle, kind) {
    var names = kind === "detail" ? ["half", "full"] : ["peek", "half", "full"];
    var drag = null, ignoreClick = false;
    function current() { return kind === "detail" ? state.detailSnap : state.listSnap; }

    handle.addEventListener("pointerdown", function (event) {
      if (!isPhone() || (event.pointerType === "mouse" && event.button !== 0)) return;
      drag = {
        id: event.pointerId, startY: event.clientY, startHeight: sheetHeight(kind, current()), moved: false,
        samples: [{ t: event.timeStamp, y: event.clientY }],
      };
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.id) return;
      var up = drag.startY - event.clientY;
      if (!drag.moved && Math.abs(up) < Sheet.TAP_PX) return;
      if (!drag.moved) document.body.classList.add("dragging");
      drag.moved = true;
      var points = sheetPoints();
      drag.height = Sheet.clamp(drag.startHeight + up, kind === "detail" ? 0 : points.peek, points.full);
      setSheetHeight(drag.height);
      drag.samples.push({ t: event.timeStamp, y: event.clientY });
      if (drag.samples.length > 8) drag.samples.shift();
    });
    function release(event) {
      if (!drag || event.pointerId !== drag.id) return;
      var finished = drag;
      drag = null;
      document.body.classList.remove("dragging");
      if (!finished.moved) return; // a tap: the click event follows and moves to the next stop
      ignoreClick = true;
      setTimeout(function () { ignoreClick = false; }, 60);
      var stops = Sheet.stops(sheetPoints(), kind === "detail" ? ["closed", "half", "full"] : names);
      var snap = event.type === "pointercancel" ? current() : Sheet.nearest(finished.height, Sheet.velocityOf(finished.samples), stops);
      if (snap === "closed") deselect(); else setSnap(kind, snap);
    }
    handle.addEventListener("pointerup", release);
    handle.addEventListener("pointercancel", release);
    handle.addEventListener("click", function () {
      if (ignoreClick || !isPhone()) return;
      setSnap(kind, Sheet.next(current(), names));
    });
    handle.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      var index = names.indexOf(current()) + (event.key === "ArrowUp" ? 1 : -1);
      if (index < 0 || index >= names.length) return;
      event.preventDefault();
      setSnap(kind, names[index]);
    });
  }

  function degrees(value, positive, negative) {
    return Math.abs(value).toFixed(3).replace(".", ",") + "° " + (value >= 0 ? positive : negative);
  }

  function updateReadout() {
    var center = map.getCenter();
    byId("read-lat").textContent = degrees(center.lat, "N", "S");
    byId("read-lon").textContent = degrees(center.lng, "O", "W");
    // the small map shows the same place from further away, with a frame around what the big map shows
    if (!mini) return; // there is no overview map on a phone
    mini.setView(center, Math.max(map.getZoom() - 4, 1), { animate: false });
    miniFrame.setBounds(map.getBounds());
  }

  // ---------------------------------------------------------------- search
  // One field for places and addresses. It lists the reports that match first (found in the data that is already loaded), then
  // the places and addresses that OUR server finds (/v1/public/search), so the browser never calls a third party.
  // Picking a report opens its card, picking a place moves the map there and sets a temporary marker with the name.

  var SEARCH_DELAY_MS = 300;
  var search = { text: "", places: [], placesState: "idle", options: [], active: -1, timer: null, controller: null, marker: null };
  var searchLayer;

  function searchOpen() { return byId("search").classList.contains("open"); }

  function setSearchOpen(open, returnFocus) {
    // On a big screen the field is always there, only the phone opens and closes it
    byId("search").classList.toggle("open", open);
    byId("search-toggle").setAttribute("aria-expanded", String(open));
    if (open) byId("search-input").focus();
    else if (returnFocus && isPhone()) byId("search-toggle").focus({ preventScroll: true });
  }

  function hideResults() {
    byId("search-results").hidden = true;
    byId("search-input").setAttribute("aria-expanded", "false");
    byId("search-input").removeAttribute("aria-activedescendant");
    search.active = -1;
  }

  function setActiveOption(index) {
    var nodes = byId("search-results").querySelectorAll('[role="option"]');
    search.active = nodes.length ? (index + nodes.length) % nodes.length : -1;
    nodes.forEach(function (node, position) {
      var on = position === search.active;
      node.classList.toggle("active", on);
      node.setAttribute("aria-selected", String(on));
    });
    var input = byId("search-input");
    if (search.active >= 0) {
      input.setAttribute("aria-activedescendant", nodes[search.active].id);
      nodes[search.active].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function renderResults() {
    var box = byId("search-results");
    clear(box);
    search.options = [];
    if (!search.text) { hideResults(); byId("search-status").textContent = ""; return; }

    var found = Search.matchCases(ranked(state.cases).map(function (item) { return item.report; }), search.text, categoryName);
    var optionCount = 0;
    function group(title, options) {
      var wrap = el("div", "search-group");
      wrap.setAttribute("role", "group");
      var heading = el("div", "search-heading", title);
      heading.id = "search-heading-" + title.length + "-" + optionCount;
      wrap.setAttribute("aria-labelledby", heading.id);
      wrap.appendChild(heading);
      options.forEach(function (option) { wrap.appendChild(option); });
      box.appendChild(wrap);
    }
    function option(build, pick) {
      var node = el("div", "search-option");
      node.id = "search-option-" + optionCount;
      optionCount += 1;
      node.setAttribute("role", "option");
      node.setAttribute("aria-selected", "false");
      build(node);
      // the mouse must not take the focus from the field, or the list would close before the click
      node.addEventListener("mousedown", function (event) { event.preventDefault(); });
      node.addEventListener("click", pick);
      return node;
    }
    function note(text) { box.appendChild(el("p", "search-note", text)); }

    if (found.length) {
      group("Meldungen", found.map(function (report) {
        return option(function (node) {
          node.appendChild(badge(report.category, Score.tier(report, WEIGHTS, Date.now())));
          var label = el("span");
          label.appendChild(document.createTextNode(categoryName(report.category)));
          label.appendChild(el("small", null, report.address || "Keine Adresse"));
          node.appendChild(label);
        }, function () { pickCase(report.id); });
      }));
    }
    if (search.places.length) {
      group("Orte und Adressen", search.places.map(function (place) {
        return option(function (node) { node.appendChild(el("span", null, place.label)); }, function () { pickPlace(place); });
      }));
    }
    if (search.placesState === "loading") note("Orte werden gesucht …");
    else if (search.placesState === "error") note("Die Suche ist gerade nicht erreichbar.");
    else if (search.placesState === "idle" && !found.length) note("Gib mindestens " + Search.MIN_PLACE_CHARS + " Zeichen ein, um Orte zu suchen.");
    else if (search.placesState === "done" && !found.length && !search.places.length) note("Nichts gefunden.");

    search.options = box.querySelectorAll('[role="option"]');
    box.hidden = false;
    byId("search-input").setAttribute("aria-expanded", "true");
    search.active = -1;
    var total = search.options.length;
    byId("search-status").textContent = search.placesState === "loading" ? "Orte werden gesucht"
      : search.placesState === "error" ? "Die Suche ist gerade nicht erreichbar"
      : total === 0 ? "Nichts gefunden" : total + " Treffer";
  }

  function fetchPlaces(text) {
    if (search.controller) search.controller.abort();
    var controller = new AbortController();
    search.controller = controller;
    fetch("/v1/public/search?q=" + encodeURIComponent(text), { signal: controller.signal, cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("status " + response.status);
      return response.json();
    }).then(function (body) {
      if (controller.signal.aborted || search.text !== text) return;
      search.places = Search.parseResults(body);
      search.placesState = "done";
      renderResults();
    }).catch(function (error) {
      if (controller.signal.aborted || (error && error.name === "AbortError") || search.text !== text) return;
      search.places = [];
      search.placesState = "error";
      renderResults();
    });
  }

  // Typing: the reports are matched at once, the places after a short pause, and an older request is cancelled
  function onSearchInput() {
    var text = byId("search-input").value.trim();
    byId("search-clear").hidden = !byId("search-input").value;
    search.text = text;
    window.clearTimeout(search.timer);
    if (search.controller) search.controller.abort();
    removeSearchMarker();
    search.places = [];
    if (text.length >= Search.MIN_PLACE_CHARS) {
      search.placesState = "loading";
      search.timer = window.setTimeout(function () { fetchPlaces(text); }, SEARCH_DELAY_MS);
    } else {
      search.placesState = "idle";
    }
    renderResults();
  }

  function removeSearchMarker() {
    if (search.marker) { searchLayer.removeLayer(search.marker); search.marker = null; }
  }

  function clearSearch() {
    window.clearTimeout(search.timer);
    if (search.controller) search.controller.abort();
    byId("search-input").value = "";
    byId("search-clear").hidden = true;
    search.text = "";
    search.places = [];
    search.placesState = "idle";
    removeSearchMarker();
    renderResults();
    byId("search-input").focus();
  }

  function finishPick() {
    hideResults();
    if (isPhone()) setSearchOpen(false, true);
  }

  function pickCase(id) {
    finishPick();
    select(id);
  }

  function pickPlace(place) {
    finishPick();
    byId("search-input").value = place.label;
    byId("search-clear").hidden = false;
    if (state.selected) deselect();
    removeSearchMarker();
    var pin = el("span", "search-pin");
    search.marker = L.marker([place.lat, place.lon], {
      icon: L.divIcon({ html: pin, className: "search-marker", iconSize: [24, 24], iconAnchor: [12, 24] }),
      keyboard: false, interactive: false,
    });
    search.marker.bindTooltip(el("span", null, place.label), { permanent: true, direction: "top", offset: [0, -22], className: "search-label" });
    search.marker.addTo(searchLayer);
    var calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (calm) map.setView([place.lat, place.lon], 16, { animate: false }); else map.flyTo([place.lat, place.lon], 16, { duration: 0.8 });
    announce(place.label);
  }

  function initSearch() {
    var input = byId("search-input");
    input.addEventListener("input", onSearchInput);
    input.addEventListener("focus", function () { if (search.text) renderResults(); });
    input.addEventListener("keydown", function (event) {
      var open = !byId("search-results").hidden;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!open && search.text) renderResults();
        event.preventDefault();
        setActiveOption(search.active + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Enter") {
        event.preventDefault();
        var nodes = byId("search-results").querySelectorAll('[role="option"]');
        var chosen = nodes[search.active >= 0 ? search.active : 0];
        if (open && chosen) chosen.click();
      } else if (event.key === "Escape") {
        event.stopPropagation(); // the card behind the search stays open
        if (open) hideResults();
        else if (input.value) clearSearch();
        else if (isPhone()) setSearchOpen(false, true);
      }
    });
    byId("search-clear").addEventListener("click", clearSearch);
    byId("search-toggle").addEventListener("click", function () { setSearchOpen(true); });
    // on a phone there is no Escape key: a button closes the field, and so does a tap on the map
    byId("search-close").addEventListener("click", function () { clearSearch(); setSearchOpen(false, true); });
    document.addEventListener("click", function (event) {
      if (isPhone() && searchOpen() && !byId("search").contains(event.target)) { clearSearch(); setSearchOpen(false); }
    });
    // a click anywhere else closes the list of results, the text stays
    document.addEventListener("click", function (event) {
      if (!byId("search").contains(event.target)) hideResults();
    });
  }

  // The style of the map as an object. It names our own server as `__ORIGIN__`, the page puts its own address there.
  function loadStyle() {
    return fetch(STYLE_URL).then(function (response) {
      if (!response.ok) throw new Error("status " + response.status);
      return response.text();
    }).then(function (text) { return JSON.parse(text.split("__ORIGIN__").join(window.location.origin)); });
  }

  function addVectorMap(target, style) {
    L.maplibreGL({ style: style }).addTo(target);
  }

  function start() {
    if (IN_APP) {
      document.body.classList.add("in-app");
      // a link (the credit of the map) would take the web view away from the dashboard
      document.addEventListener("click", function (event) {
        var link = event.target.closest ? event.target.closest("a") : null;
        if (link) event.preventDefault();
      });
    }
    // The web worker of MapLibre is a file of ours (the page does not allow scripts from anywhere else)
    maplibregl.setWorkerUrl(new URL("vendor/maplibre-gl-csp-worker.js", window.location.href).href);
    maplibregl.addProtocol("pmtiles", new pmtiles.Protocol().tile);

    state.wantedCase = wantedFromHash();
    applySheets();

    map = L.map("map", { zoomControl: false, attributionControl: false, minZoom: 13, maxZoom: 19, maxBounds: MAP_BOUNDS, maxBoundsViscosity: 1 })
      .setView(START_VIEW.center, isPhone() ? START_VIEW.zoom + 1 : START_VIEW.zoom); // a tall phone screen would show more than the map file holds
    L.control.attribution({ position: "bottomleft", prefix: false }).addAttribution(AERIAL).addAttribution(ATTRIBUTION).addAttribution(PROTOMAPS).addTo(map);
    // On a phone the credit is a small info button, a tap opens the text (a link inside still works as a link)
    var credit = document.querySelector(".leaflet-control-attribution");
    if (credit) {
      credit.setAttribute("role", "button");
      credit.setAttribute("tabindex", "0");
      credit.setAttribute("aria-label", "Quellenangaben der Karte");
      credit.addEventListener("click", function (event) {
        if (!isPhone() || (event.target.closest && event.target.closest("a"))) return;
        credit.classList.toggle("open");
        event.stopPropagation();
      });
      credit.addEventListener("keydown", function (event) {
        if (isPhone() && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); credit.classList.toggle("open"); }
      });
      document.addEventListener("click", function () { credit.classList.remove("open"); });
    }
    markerLayer = L.layerGroup().addTo(map);
    searchLayer = L.layerGroup().addTo(map);

    // The overview map is a second WebGL map: only where it is shown (not on a phone)
    var overview = null;
    if (!isPhone()) {
      mini = L.map("minimap", {
        zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
        boxZoom: false, keyboard: false, touchZoom: false,
      }).setView(START_VIEW.center, START_VIEW.zoom - 4);
      miniFrame = L.rectangle(map.getBounds(), { color: "#ffffff", weight: 1.5, fillOpacity: 0.1, interactive: false }).addTo(mini);
    }
    loadStyle().then(function (style) {
      addVectorMap(map, style);
      if (mini) {
        // the overview map has no labels and no symbols, at that size they only get in the way
        overview = JSON.parse(JSON.stringify(style));
        overview.layers = overview.layers.filter(function (layer) { return layer.type !== "symbol"; });
        addVectorMap(mini, overview);
      }
    }).catch(function () {
      // No map under the markers is better than a map from somebody else: there is no fallback to a public server
      setMode("Karte fehlt", "warn", "Die Karte konnte nicht gestartet werden (der Browser braucht WebGL, und die Kartendatei muss auf dem Server liegen). Die Meldungen werden ohne Karte gezeigt.");
    });
    map.on("move zoom", updateReadout);
    updateReadout();

    initSearch();
    byId("zoom-in").addEventListener("click", function () { map.zoomIn(); });
    byId("zoom-out").addEventListener("click", function () { map.zoomOut(); });
    byId("fit-all").addEventListener("click", function () { fitAll(true); });
    byId("minimap-button").addEventListener("click", function () { fitAll(true); });
    attachHandle(byId("list-handle"), "list");
    attachHandle(byId("detail-handle"), "detail");
    document.addEventListener("click", function (event) {
      // composedPath: the button that was clicked may already be replaced by a new one when the event arrives here
      if (state.filterOpen && event.composedPath().indexOf(byId("counts")) < 0) { state.filterOpen = false; render(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (state.filterOpen) { state.filterOpen = false; render(); return; }
      if (state.selected) deselect();
      else if (isPhone() && state.listSnap !== "peek") setSnap("list", "peek");
    });
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener("resize", function () { applySheets(); });

    // the skeleton while the first answer is on its way
    render();

    refresh();
    setInterval(function () { if (state.live && !state.error) refresh(); }, REFRESH_MS);
  }

  start();
})();
