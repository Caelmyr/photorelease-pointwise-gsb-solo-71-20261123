"use strict";

const byId = (id) => document.getElementById(id);
const state = {desks: [], desk: null, photo: null, view: "working", tool: null, drag: null, review: null};
const dialog = byId("dialog");
const dialogContent = byId("dialog-content");
const overlay = byId("overlay");
let toastTimer;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function action(text, run, className) {
  const button = node("button", text, className);
  button.type = "button";
  button.addEventListener("click", attempt(run));
  return button;
}

function link(text, href) {
  const anchor = node("a", text, "button");
  anchor.href = href;
  return anchor;
}

function attempt(run) {
  return async (event) => {
    try {
      await run(event);
    } catch (error) {
      notice(error.message);
    }
  };
}

function notice(message) {
  clearTimeout(toastTimer);
  byId("notice").textContent = message;
  toastTimer = setTimeout(() => { byId("notice").textContent = ""; }, 5500);
}

async function request(url, method = "GET", data) {
  const options = {method, cache: "no-store"};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {
    options.body = JSON.stringify(data);
    options.headers = {"Content-Type": "application/json"};
  }
  const response = await fetch(url, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "The desk could not finish that request.");
  return value;
}

function deskURL() {
  return `/release/desks/${state.desk.id}`;
}

function activePhoto() {
  return state.desk?.photos.find((photo) => photo.id === state.photo);
}

function photoURL(photo = activePhoto()) {
  return `${deskURL()}/photos/${photo.id}`;
}

function versioned(url) {
  return `${url}?revision=${state.desk.revision}`;
}

function selectPhoto(id) {
  state.photo = id;
  state.view = "working";
  state.tool = null;
  state.review = null;
  show();
  fetchReview();
}

async function selectDesk(id) {
  const desk = await request(`/release/desks/${id}`);
  state.desk = desk;
  localStorage.setItem("photorelease-desk", desk.id);
  selectPhoto(desk.photos[0]?.id ?? null);
}

async function fetchReview() {
  const photo = activePhoto();
  if (!photo) return;
  const deskId = state.desk.id;
  const revision = state.desk.revision;
  try {
    const review = await request(`${photoURL(photo)}/review`);
    if (state.desk?.id === deskId && state.desk.revision === revision && state.photo === photo.id) {
      state.review = review;
      showMarks(photo);
      updateImageInfo(photo);
    }
  } catch (error) {
    notice(error.message);
  }
}

async function acceptDesk(desk, pickLast = false) {
  state.desk = desk;
  if (pickLast) state.photo = desk.photos.at(-1)?.id ?? null;
  state.review = null;
  state.desks = await request("/release/desks");
  show();
  await fetchReview();
}

async function mutate(url, method, data) {
  const revision = state.desk.revision;
  const desk = await request(url, method, {revision, ...data});
  await acceptDesk(desk);
  return desk;
}

async function editPhoto(data) {
  return mutate(photoURL(), "PATCH", data);
}

function collectionEntry(title, meta, callback, className) {
  const button = action("", callback, className);
  const text = node("span", title);
  if (meta) text.append(node("small", meta));
  button.append(text);
  return button;
}

function showDesks() {
  byId("desk-list").replaceChildren(...state.desks.map((desk) => {
    const tail = `${desk.photo_count} photos · ${desk.issue_count} issues`;
    const button = collectionEntry(desk.title, tail, () => selectDesk(desk.id), "desk-item");
    button.classList.toggle("active", desk.id === state.desk?.id);
    return button;
  }));
}

function show() {
  showDesks();
  byId("welcome").hidden = Boolean(state.desk);
  byId("workspace").hidden = !state.desk;
  byId("photo-library").hidden = !state.desk;
  if (!state.desk) return;
  const desk = state.desk;
  const photo = activePhoto();
  byId("desk-title").textContent = desk.title;
  byId("issue-count").textContent = String(desk.issues.length);
  const included = desk.photos.filter((entry) => entry.used);
  byId("contact-sheet").disabled = included.length === 0;
  byId("make-issue").disabled = included.length === 0;
  byId("burst-review").disabled = desk.photos.length < 2;
  byId("photo-list").replaceChildren(...desk.photos.map((item) => {
    const tail = !item.used ? "Excluded" : (item.approved ? "Approved" : "Needs review");
    const button = collectionEntry(item.name, tail, () => selectPhoto(item.id), "photo-item");
    const thumbnail = node("img");
    thumbnail.alt = "";
    thumbnail.loading = "lazy";
    thumbnail.src = `${photoURL(item)}/image/thumb`;
    button.prepend(thumbnail);
    button.classList.toggle("active", state.photo === item.id);
    if (item.represented_by) {
      const representative = photoById(item.represented_by);
      button.append(node("small", `Represented by ${representative ? representative.name : "a removed photo"}`));
    }
    return button;
  }));
  byId("empty-desk").hidden = Boolean(photo);
  byId("photo-workspace").hidden = !photo;
  if (!photo) return;
  byId("photo-title").textContent = photo.name;
  byId("provenance").textContent = {
    synthetic: "SYNTHETIC SAMPLE", upload: "UPLOADED PHOTO",
    asset: "PREPARED SOURCE", result: "PREPARED RESULT",
  }[photo.provenance];
  byId("review-state").textContent = photo.approved ? "Approved" : "Needs review";
  byId("review-state").classList.toggle("approved", photo.approved);
  byId("include-photo").checked = photo.used;
  const representation = byId("representation");
  representation.replaceChildren();
  if (photo.represented_by) {
    const representative = photoById(photo.represented_by);
    representation.hidden = false;
    representation.append(node("small", `Unchecked in this draft by burst review; represented by ${representative ? representative.name : "a removed photo"}.`));
  } else {
    const followers = desk.photos.filter((item) => item.represented_by === photo.id);
    if (followers.length) {
      representation.hidden = false;
      representation.append(node("small", `Represents ${followers.length} unchecked photo${followers.length === 1 ? "" : "s"} in this draft.`));
    } else {
      representation.hidden = true;
    }
  }
  const index = desk.photos.indexOf(photo);
  byId("earlier").disabled = index === 0;
  byId("later").disabled = index === desk.photos.length - 1;
  byId("reset-crop").disabled = !photo.style.crop;
  const form = byId("styling");
  for (const key of ["edge", "format", "cover", "caption"]) form.elements[key].value = photo.style[key];
  showMarks(photo);
  showView();
}

function showMarks(photo) {
  byId("mark-count").textContent = String(photo.marks.length);
  const rows = photo.marks.map((mark) => {
    const description = node("div");
    const title = node("span", mark.label || (mark.kind === "cover" ? "Cover region" : "Keep region"));
    const measurement = state.review?.marks.find((entry) => entry.id === mark.id);
    const titleCase = mark.kind === "cover" ? "Cover" : "Keep";
    const measureText = measurement ? ` · ${Math.round(100 * measurement.fraction)}% in crop` : "";
    description.append(title, node("small", titleCase + measureText));
    const actions = node("div", undefined, "mark-ops");
    actions.append(
      action("Edit", () => editMarkDialog(mark)),
      action("Remove", () => mutate(`${photoURL()}/marks/${mark.id}`, "DELETE", {})),
    );
    const row = node("div", undefined, "mark");
    row.append(description, actions);
    return row;
  });
  byId("mark-list").replaceChildren(...(rows.length ? rows : [node("p", "No marked regions.", "muted")]));
}

function updateImageInfo(photo) {
  const size = state.view === "working" ? [photo.width, photo.height] : state.review?.size;
  byId("view-size").textContent = size ? `${size[0]} × ${size[1]} px` : "";
}

function showView() {
  const photo = activePhoto();
  if (!photo) return;
  byId("mark-tools").hidden = state.view !== "working";
  for (const button of document.querySelectorAll("[data-view]")) {
    const selected = button.dataset.view === state.view;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  }
  for (const button of document.querySelectorAll("[data-tool]")) {
    const selected = button.dataset.tool === state.tool;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  }
  const image = byId("canvas-photo");
  const newURL = versioned(`${photoURL()}/image/${state.view}`);
  if (image.getAttribute("src") !== newURL) image.src = newURL;
  image.alt = `${photo.name} · ${state.view === "working" ? "source photograph" : "public preview"}`;
  updateImageInfo(photo);
  byId("approve-photo").textContent = photo.approved ? "Withdraw approval" :
    (state.view === "draft" ? "Approve public preview" : "Review public preview");
  byId("tool-help").textContent = state.tool ? "Drag a rectangle on the source." :
    (state.view === "working" ? "Private source view" : "Preview of the encoded public file");
  drawOverlay();
}

function boxElement(box, type) {
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", box[0]);
  rect.setAttribute("y", box[1]);
  rect.setAttribute("width", box[2] - box[0]);
  rect.setAttribute("height", box[3] - box[1]);
  rect.setAttribute("class", type);
  return rect;
}

function drawOverlay() {
  const photo = activePhoto();
  if (!photo || state.view !== "working") {
    overlay.classList.remove("drawing");
    overlay.replaceChildren();
    return;
  }
  overlay.setAttribute("viewBox", `0 0 ${photo.width} ${photo.height}`);
  overlay.setAttribute("preserveAspectRatio", "none");
  overlay.classList.toggle("drawing", Boolean(state.tool));
  const items = photo.marks.map(({box, kind}) => boxElement(box, kind));
  if (photo.style.crop) items.unshift(boxElement(photo.style.crop, "crop"));
  if (state.drag) items.push(boxElement(orderedBox(state.drag.start, state.drag.end), "selection"));
  overlay.replaceChildren(...items);
}

function imagePoint(event) {
  const bounds = overlay.getBoundingClientRect();
  const photo = activePhoto();
  const proportion = (number) => Math.max(0, Math.min(1, number));
  return [
    photo.width * proportion((event.clientX - bounds.left) / bounds.width),
    photo.height * proportion((event.clientY - bounds.top) / bounds.height),
  ];
}

function orderedBox(start, end) {
  return [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])];
}

function setView(view) {
  state.view = view;
  state.tool = null;
  state.drag = null;
  showView();
}

function openDialog(title, ...children) {
  byId("dialog-title").textContent = title;
  dialogContent.replaceChildren(...children);
  if (!dialog.open) dialog.showModal();
}

function dialogForm(title, label, value, limit, submitLabel, submit, required = true) {
  const form = node("form");
  const field = node("label", label);
  const input = node("input");
  input.type = "text";
  input.value = value;
  input.maxLength = limit;
  input.required = required;
  field.append(input);
  const button = node("button", submitLabel, "primary");
  button.type = "submit";
  form.append(field, button);
  form.addEventListener("submit", attempt(async (event) => {
    event.preventDefault();
    await submit(input.value);
  }));
  openDialog(title, form);
}

function editMarkDialog(mark) {
  const form = node("form");
  const title = node("label", "Label");
  const name = node("input");
  name.value = mark.label;
  name.maxLength = 70;
  title.append(name);
  form.append(title);
  const limits = [activePhoto().width, activePhoto().height, activePhoto().width, activePhoto().height];
  const fields = ["Left", "Top", "Right", "Bottom"].map((field, index) => {
    const label = node("label", field);
    const input = node("input");
    input.type = "number";
    input.value = String(mark.box[index]);
    input.min = "0";
    input.max = String(limits[index]);
    input.required = true;
    label.append(input);
    form.append(label);
    return input;
  });
  const save = node("button", "Save region", "primary");
  save.type = "submit";
  form.append(save);
  form.addEventListener("submit", attempt(async (event) => {
    event.preventDefault();
    await mutate(`${photoURL()}/marks/${mark.id}`, "PATCH", {label: name.value, box: fields.map((input) => input.valueAsNumber)});
    dialog.close();
  }));
  openDialog("Edit marked region", form);
}

async function createDesk(title) {
  const desk = await request("/release/desks", "POST", {title});
  state.desks = await request("/release/desks");
  await selectDesk(desk.id);
  dialog.close();
}

async function loadDemo() {
  const desk = await request("/release/demo", "POST");
  state.desks = await request("/release/desks");
  await selectDesk(desk.id);
}

async function uploadPhoto(file) {
  const form = new FormData();
  form.set("file", file);
  form.set("revision", state.desk.revision);
  const desk = await request(`${deskURL()}/photos`, "POST", form);
  state.view = "working";
  state.tool = null;
  await acceptDesk(desk, true);
}

async function showPreparation() {
  const data = await request("/release/preparation");
  const containers = node("div", undefined, "results");
  const entries = [
    ...data.assets.map((entry) => ({entry, kind: "asset", payload: {asset_id: entry.id}})),
    ...data.results.map((entry) => ({entry, kind: "result", payload: {project_id: entry.project_id, result_id: entry.id}})),
  ];
  for (const {entry, kind, payload} of entries) {
    const row = node("div", undefined, "dialog-item");
    const detail = node("span", `${entry.name} · ${kind === "asset" ? "Source" : "Result"} · ${entry.width} × ${entry.height}`);
    const insert = action("Add to desk", async () => {
      const next = await request(`${deskURL()}/prepared-photo`, "POST", {revision: state.desk.revision, kind, ...payload});
      state.view = "working";
      state.tool = null;
      await acceptDesk(next, true);
      dialog.close();
    });
    row.append(detail, insert);
    containers.append(row);
  }
  if (!entries.length) containers.append(node("p", "Import a source or finish a result in Image preparation."));
  openDialog("Add from image preparation", containers, link("Go to image preparation ↗", "/prepare"));
}

function showContact(page = 1) {
  const photos = state.desk.photos.filter((photo) => photo.used);
  const pages = Math.ceil(photos.length / 6);
  const image = node("img");
  image.alt = `Draft contact sheet page ${page}`;
  image.src = versioned(`${deskURL()}/contact/${page}`);
  const controls = node("div", undefined, "dialog-actions");
  for (let target = 1; target <= pages; target += 1) {
    const button = action(`Page ${target}`, () => showContact(target));
    button.disabled = target === page;
    controls.append(button);
  }
  openDialog("Draft contact sheet", image, controls);
}

function showIssueHistory() {
  const list = node("div", undefined, "results");
  for (const issue of [...state.desk.issues].reverse()) {
    const row = node("div", undefined, "dialog-item");
    const heading = node("span", issue.title);
    heading.append(node("small", ` · ${issue.photo_count} photos · ${new Date(issue.created_at).toLocaleString()}`));
    const actions = node("div", undefined, "dialog-actions");
    actions.append(
      action("Open", () => showIssue(issue.id)),
      link("Download ZIP", `${deskURL()}/issues/${issue.id}/download`),
    );
    row.append(heading, actions);
    list.append(row);
  }
  if (!state.desk.issues.length) list.append(node("p", "No saved issues yet."));
  if (state.desk.issues.length >= 2 && activePhoto()) {
    list.append(action("Compare issues for this photo", compareDialog));
  }
  openDialog("Issue history", list);
}

async function showIssue(issueId) {
  const issue = await request(`${deskURL()}/issues/${issueId}`);
  const list = node("div", undefined, "results");
  for (const photo of issue.photos) {
    const row = node("div", undefined, "dialog-item");
    const text = node("span", photo.caption || photo.name);
    text.append(node("small", ` · ${photo.width} × ${photo.height} px`));
    row.append(text, link("Open saved photo", `${deskURL()}/issues/${issueId}/photos/${photo.source_id}`));
    list.append(row);
  }
  const actions = node("div", undefined, "dialog-actions");
  actions.append(action("← Issue history", showIssueHistory), link("Download ZIP", `${deskURL()}/issues/${issueId}/download`));
  openDialog(issue.title, list, actions);
}

function compareDialog() {
  const photo = activePhoto();
  const form = node("form");
  const picks = ["First issue", "Second issue"].map((label, index) => {
    const field = node("label", label);
    const input = node("select");
    for (const issue of state.desk.issues) {
      const option = node("option", issue.title);
      option.value = issue.id;
      input.append(option);
    }
    input.selectedIndex = index;
    field.append(input);
    form.append(field);
    return input;
  });
  const submit = node("button", "Compare saved photos", "primary");
  submit.type = "submit";
  form.append(submit);
  const result = node("div");
  form.addEventListener("submit", attempt(async (event) => {
    event.preventDefault();
    result.replaceChildren();
    const params = new URLSearchParams({photo: photo.id, first: picks[0].value, second: picks[1].value});
    const figures = node("div", undefined, "image-compare");
    for (const control of picks) {
      const figure = node("figure");
      const image = node("img");
      image.alt = control.selectedOptions[0].textContent;
      image.src = `${deskURL()}/issues/${control.value}/photos/${photo.id}`;
      figure.append(image, node("figcaption", control.selectedOptions[0].textContent));
      figures.append(figure);
    }
    result.append(figures);
    const report = await request(`${deskURL()}/compare?${params}`);
    const map = node("img");
    map.src = `${deskURL()}/compare?${params}&format=png`;
    map.alt = "Changed pixels highlighted in pink";
    result.append(node("p", `${report.changed_pixels} of ${report.total_pixels} pixels differ. Maximum channel difference: ${report.maximum_channel_delta}.`), map);
  }));
  openDialog("Compare issues for this photo", form, result, action("← Issue history", showIssueHistory));
}

async function inspectZip(file) {
  const form = new FormData();
  form.set("file", file);
  const result = await request("/release/inspect", "POST", form);
  const heading = node("p", result.valid ? "Files match the manifest." : "Some files do not match the manifest.");
  const list = node("ul");
  for (const item of result.files) list.append(node("li", `${item.path} · ${item.state}`));
  openDialog(`Verify ${result.title || "release ZIP"}`, heading, list);
}

function bind(id, event, handler) {
  byId(id).addEventListener(event, attempt(handler));
}

bind("close-dialog", "click", () => dialog.close());
bind("new-desk", "click", () => dialogForm("New publication desk", "Desk title", "", 90, "Create desk", createDesk));
bind("load-demo", "click", loadDemo);
bind("welcome-demo", "click", loadDemo);
bind("upload-photo", "click", () => byId("photo-file").click());
bind("empty-upload", "click", () => byId("photo-file").click());
bind("photo-file", "change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) await uploadPhoto(file);
});
bind("add-prepared", "click", showPreparation);
bind("inspect-issue", "click", () => byId("issue-file").click());
bind("issue-file", "change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) await inspectZip(file);
});
bind("contact-sheet", "click", () => showContact());
bind("show-issues", "click", showIssueHistory);
bind("make-issue", "click", () => {
  const pending = state.desk.photos.filter((photo) => photo.used && !photo.approved);
  if (pending.length) {
    openDialog("Approve included photos", node("p", "Review the public preview of every included photo before creating the issue."),
      ...pending.map((photo) => action(photo.name, () => {
        dialog.close();
        selectPhoto(photo.id);
        setView("draft");
      })));
    return;
  }
  dialogForm("Create public issue", "Public issue title", "", 75, "Save issue", async (title) => {
    await mutate(`${deskURL()}/issues`, "POST", {title});
    showIssueHistory();
  });
});
bind("reset-crop", "click", () => editPhoto({style: {crop: null}}));
bind("styling", "submit", async (event) => {
  event.preventDefault();
  await editPhoto({style: Object.fromEntries(new FormData(event.target))});
  setView("draft");
});
bind("approve-photo", "click", async () => {
  const photo = activePhoto();
  if (state.view !== "draft" && !photo.approved) {
    setView("draft");
    return;
  }
  await editPhoto({approved: !photo.approved});
});
bind("include-photo", "change", (event) => editPhoto({used: event.target.checked}));
bind("earlier", "click", () => editPhoto({move: "earlier"}));
bind("later", "click", () => editPhoto({move: "later"}));

for (const button of document.querySelectorAll("[data-view]")) {
  button.addEventListener("click", () => setView(button.dataset.view));
}
for (const button of document.querySelectorAll("[data-tool]")) {
  button.addEventListener("click", () => {
    state.tool = state.tool === button.dataset.tool ? null : button.dataset.tool;
    showView();
  });
}

overlay.addEventListener("pointerdown", (event) => {
  if (!state.tool || event.button !== 0) return;
  event.preventDefault();
  overlay.setPointerCapture(event.pointerId);
  const position = imagePoint(event);
  state.drag = {start: position, end: position};
  drawOverlay();
});
overlay.addEventListener("pointermove", (event) => {
  if (!state.drag) return;
  state.drag.end = imagePoint(event);
  drawOverlay();
});
overlay.addEventListener("pointercancel", () => {
  state.drag = null;
  drawOverlay();
});
overlay.addEventListener("pointerup", attempt(async (event) => {
  if (!state.drag) return;
  const box = orderedBox(state.drag.start, imagePoint(event));
  const tool = state.tool;
  state.drag = null;
  state.tool = null;
  showView();
  if (box[2] - box[0] < 2 || box[3] - box[1] < 2) return;
  if (tool === "crop") {
    await editPhoto({style: {crop: box}});
    return;
  }
  const label = tool === "cover" ? "Cover region" : "Keep region";
  dialogForm(`Mark ${label.toLowerCase()}`, "Private label", "", 70, "Save region", async (value) => {
    await mutate(`${photoURL()}/marks`, "POST", {kind: tool, label: value, box});
    dialog.close();
  }, false);
}));

/* Burst review: group near-identical bursts by a watched region. */
const GRID_NOTE = 24;
const burst = {analysis: null, mode: "anchor", threshold: 90, picks: new Set(), box: null, base: null};

function photoById(id) {
  return state.desk?.photos.find((photo) => photo.id === id);
}

function burstPairKey(left, right) {
  return left < right ? `${left}|${right}` : `${right}|${left}`;
}

function burstPair(analysis, left, right) {
  return analysis.pairMap.get(burstPairKey(left, right));
}

function recomputeGroups(analysis, mode, threshold) {
  const ids = analysis.photo_ids;
  const used = new Set();
  const groups = [];
  for (let i = 0; i < ids.length; i += 1) {
    if (used.has(i)) continue;
    const group = [i];
    for (let j = i + 1; j < ids.length; j += 1) {
      if (used.has(j)) continue;
      if (mode === "anchor") {
        if (burstPair(analysis, ids[i], ids[j]).similarity >= threshold) group.push(j);
      } else if (group.every((member) => burstPair(analysis, ids[member], ids[j]).similarity >= threshold)) {
        group.push(j);
      }
    }
    group.forEach((index) => used.add(index));
    groups.push(group);
  }
  return groups.map((group) => {
    let representativePosition = 0;
    if (mode === "pairwise" && group.length > 1) {
      let best = -Infinity;
      group.forEach((candidate, position) => {
        const score = group.reduce((sum, other) =>
          other === candidate ? sum : sum + burstPair(analysis, ids[candidate], ids[other]).similarity, 0);
        if (score > best) {
          best = score;
          representativePosition = position;
        }
      });
    }
    let worst = null;
    for (let a = 0; a < group.length; a += 1) {
      for (let b = a + 1; b < group.length; b += 1) {
        const metrics = burstPair(analysis, ids[group[a]], ids[group[b]]);
        if (!worst || metrics.similarity < worst.similarity) {
          worst = {...metrics, left: ids[group[a]], right: ids[group[b]]};
        }
      }
    }
    return {
      members: group.map((index) => ids[index]),
      representative: ids[group[representativePosition]],
      worst_pair: worst,
    };
  });
}

function burstPoint(svg, photo, event) {
  const bounds = svg.getBoundingClientRect();
  const clamp = (value) => Math.max(0, Math.min(1, value));
  return [
    photo.width * clamp((event.clientX - bounds.left) / bounds.width),
    photo.height * clamp((event.clientY - bounds.top) / bounds.height),
  ];
}

function burstBoxSVG(box, className) {
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", box[0]);
  rect.setAttribute("y", box[1]);
  rect.setAttribute("width", box[2] - box[0]);
  rect.setAttribute("height", box[3] - box[1]);
  rect.setAttribute("class", className);
  return rect;
}

function burstCanvas(photo, initialBox) {
  const frame = node("div", undefined, "burst-frame");
  const image = node("img");
  image.alt = `${photo.name} source`;
  image.src = versioned(`${deskURL()}/photos/${photo.id}/image/working`);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${photo.width} ${photo.height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  let drag = null;
  const paint = () => svg.replaceChildren(...(burst.box ? [burstBoxSVG(burst.box, "selection")] : []),
    ...(drag ? [burstBoxSVG(orderedBox(drag.start, drag.end), "draft-box")] : []));
  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    svg.setPointerCapture(event.pointerId);
    drag = {start: burstPoint(svg, photo, event), end: null};
  });
  svg.addEventListener("pointermove", (event) => {
    if (!drag) return;
    drag.end = burstPoint(svg, photo, event);
    paint();
  });
  const finish = attempt(async (event) => {
    if (!drag) return;
    const box = orderedBox(drag.start, burstPoint(svg, photo, event));
    drag = null;
    if (box[2] - box[0] >= 24 && box[3] - box[1] >= 24) {
      burst.box = box.map((value) => Math.round(value));
    } else {
      notice("The watch region needs to be at least 24 pixels wide and tall.");
    }
    paint();
  });
  svg.addEventListener("pointerup", finish);
  svg.addEventListener("pointercancel", () => { drag = null; paint(); });
  frame.append(image, svg);
  if (initialBox) burst.box = initialBox;
  paint();
  return frame;
}

function openBurst() {
  const first = state.desk.photos[0];
  const sameSize = state.desk.photos.filter((photo) =>
    photo.width === first.width && photo.height === first.height);
  burst.analysis = null;
  burst.mode = "anchor";
  burst.threshold = 90;
  burst.picks = new Set(sameSize.slice(0, 12).map((photo) => photo.id));
  burst.box = null;
  burst.base = photoById([...burst.picks][0]) || activePhoto() || first;
  renderBurstSetup();
}

function renderBurstSetup() {
  const photo = burst.base || activePhoto();
  const wrap = node("div", undefined, "burst-setup");
  const intro = node("p", "Pick the burst photographs (same camera position and size), then circle the region that must stay comparable, for example hands on a repair bench.", "muted");
  const pickList = node("div", undefined, "burst-picks");
  for (const item of state.desk.photos) {
    const label = node("label");
    const checkbox = node("input");
    checkbox.type = "checkbox";
    checkbox.checked = burst.picks.has(item.id);
    const sameDimension = item.width === photo.width && item.height === photo.height;
    checkbox.disabled = !sameDimension || (burst.picks.size >= 12 && !burst.picks.has(item.id));
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        if (burst.picks.size >= 12) {
          checkbox.checked = false;
          notice("A burst set can contain up to 12 photographs.");
          return;
        }
        burst.picks.add(item.id);
      } else burst.picks.delete(item.id);
    });
    label.append(checkbox, node("span", `${item.name} · ${item.width} × ${item.height} px`));
    if (!sameDimension) label.append(node("small", "different size"));
    pickList.append(label);
  }
  const baseLine = node("label", "Circle the watch region on ");
  const baseSelect = node("select");
  for (const item of state.desk.photos) {
    const option = new Option(item.name, item.id);
    option.disabled = item.width !== photo.width || item.height !== photo.height;
    baseSelect.append(option);
  }
  baseSelect.value = photo.id;
  baseSelect.addEventListener("change", () => {
    burst.base = photoById(baseSelect.value);
    burst.box = null;
    renderBurstSetup();
  });
  baseLine.append(baseSelect);
  const marks = node("select");
  marks.append(new Option("…or reuse an existing marked region", ""));
  for (const mark of photo.marks) {
    marks.append(new Option(`${mark.label || mark.kind} region [${mark.box.join(", ")}]`, mark.box.join(",")));
  }
  marks.addEventListener("change", () => {
    if (!marks.value) return;
    burst.box = marks.value.split(",").map(Number);
    renderBurstSetup();
  });
  const modeField = node("div", undefined, "burst-modes");
  const modes = [
    ["anchor", "Compared with the representative", "Every group member must resemble the photo you keep; groups can chain through gradual change."],
    ["pairwise", "All photos resemble each other", "Every pair inside a group must pass the threshold, so a group stays mutually interchangeable."],
  ];
  for (const [value, title, hint] of modes) {
    const choice = node("label");
    const radio = node("input");
    radio.type = "radio";
    radio.name = "burst-mode";
    radio.checked = burst.mode === value;
    radio.addEventListener("change", () => { burst.mode = value; });
    choice.append(radio, node("strong", title), node("small", hint));
    modeField.append(choice);
  }
  const thresholdLine = node("label", `Similarity threshold: ${burst.threshold}`);
  const slider = node("input");
  slider.type = "range";
  slider.min = "50";
  slider.max = "100";
  slider.value = String(burst.threshold);
  slider.addEventListener("input", () => {
    burst.threshold = Number(slider.value);
    thresholdLine.firstChild.textContent = `Similarity threshold: ${burst.threshold}`;
  });
  thresholdLine.append(slider);
  const compare = node("button", "Compare photographs", "primary");
  compare.type = "button";
  compare.addEventListener("click", attempt(async () => {
    if (burst.picks.size < 2) throw new Error("Choose at least two photographs.");
    if (!burst.box) throw new Error("Draw a watch region first.");
    compare.disabled = true;
    try {
      const analysis = await request(`${deskURL()}/bursts/analyze`, "POST", {
        mode: burst.mode, threshold: burst.threshold,
        photo_ids: [...burst.picks], box: burst.box,
      });
      analysis.pairMap = new Map(analysis.pairs.map((pair) => [burstPairKey(pair.left, pair.right), pair]));
      burst.analysis = analysis;
      burst.mode = analysis.mode;
      burst.threshold = analysis.threshold;
      renderBurstResults();
    } finally {
      compare.disabled = false;
    }
  }));
  const actions = node("div", undefined, "dialog-actions");
  actions.append(compare, action("Applied grouping history", renderBurstHistory));
  const body = node("div");
  body.append(intro, node("h3", "1. Photographs"), pickList,
    node("h3", "2. Watch region"), baseLine, marks, burstCanvas(photo, burst.box),
    node("h3", "3. Grouping rule"), modeField, thresholdLine, actions);
  wrap.append(body);
  openDialog("Burst review", wrap);
}

function renderBurstResults() {
  const analysis = burst.analysis;
  const groups = recomputeGroups(analysis, burst.mode, burst.threshold);
  const unchecked = groups.reduce((count, group) => count + group.members.length - 1, 0);
  const wrap = node("div", undefined, "burst-results");
  wrap.append(node("p", `${groups.length} group${groups.length === 1 ? "" : "s"} at similarity ${burst.threshold}+ · applying unchecks ${unchecked} of ${analysis.photo_ids.length} photos in this draft only.`, "muted"));

  const modeField = node("div", undefined, "burst-modes");
  for (const [value, title] of [["anchor", "Compared with the representative"], ["pairwise", "All photos resemble each other"]]) {
    const choice = node("label");
    const radio = node("input");
    radio.type = "radio";
    radio.name = "burst-mode-live";
    radio.checked = burst.mode === value;
    radio.addEventListener("change", () => { burst.mode = value; renderBurstResults(); });
    choice.append(radio, node("strong", title));
    modeField.append(choice);
  }
  const thresholdLine = node("label", `Similarity threshold: ${burst.threshold}`);
  const slider = node("input");
  slider.type = "range";
  slider.min = "50";
  slider.max = "100";
  slider.value = String(burst.threshold);
  slider.addEventListener("input", () => {
    burst.threshold = Number(slider.value);
    thresholdLine.firstChild.textContent = `Similarity threshold: ${burst.threshold}`;
    renderBurstResults();
  });
  thresholdLine.append(slider);
  wrap.append(modeField, thresholdLine);

  groups.forEach((group, groupIndex) => {
    const card = node("fieldset", undefined, "burst-group");
    card.append(node("legend", `Group ${groupIndex + 1} · ${group.members.length} photo${group.members.length === 1 ? "" : "s"}`));
    if (group.members.length === 1) {
      card.append(node("p", "No other selected photo reaches this threshold.", "muted"));
    }
    for (const memberId of group.members) {
      const row = node("div", undefined, "burst-member");
      const pick = node("label");
      const radio = node("input");
      radio.type = "radio";
      radio.name = `rep-${groupIndex}`;
      radio.checked = memberId === group.representative;
      radio.addEventListener("change", () => {
        group.representative = memberId;
      });
      const thumb = node("img");
      thumb.src = `${deskURL()}/photos/${memberId}/image/thumb`;
      thumb.alt = "";
      const detail = node("span", photoById(memberId)?.name || "Removed photo");
      if (memberId !== group.representative && group.worst_pair) {
        const toRep = burstPair(analysis, memberId, group.representative);
        if (toRep) detail.append(node("small", ` · ${toRep.similarity} similar to representative`));
      } else {
        detail.append(node("small", " · representative"));
      }
      pick.append(radio, thumb, detail);
      row.append(pick);
      card.append(row);
    }
    if (group.worst_pair) {
      const worst = group.worst_pair;
      const line = node("p", undefined, "burst-worst");
      line.append(node("small", `Largest difference inside group: ${photoById(worst.left)?.name} ↔ ${photoById(worst.right)?.name} · similarity ${worst.similarity} · mean error ${worst.mae} · shift ${worst.shift[0]}, ${worst.shift[1]} px`));
      line.append(action("View where it differs", () => renderBurstDifference(worst)));
      card.append(line);
    }
    wrap.append(card);
  });

  const actions = node("div", undefined, "dialog-actions");
  actions.append(
    action("← Reselect photos", renderBurstSetup),
    action("Applied grouping history", renderBurstHistory),
  );
  const apply = node("button", "Apply to this draft", "primary");
  apply.type = "button";
  apply.addEventListener("click", attempt(async () => {
    await request(`${deskURL()}/bursts/apply`, "POST", {
      revision: state.desk.revision,
      mode: burst.mode, threshold: burst.threshold, box: analysis.box,
      groups: groups.map((group) => ({members: group.members, representative: group.representative})),
    });
    dialog.close();
    await acceptDesk(state.desk);
    notice(`Applied the grouping: ${unchecked} photo${unchecked === 1 ? "" : "s"} represented and unchecked. Saved issues were not changed.`);
  }));
  actions.append(apply);
  wrap.append(actions);
  openDialog("Burst review", wrap);
}

async function renderBurstDifference(worst) {
  const response = await fetch(`${deskURL()}/bursts/difference`, {
    method: "POST",
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({photo_ids: [worst.left, worst.right], box: burst.analysis.box}),
  });
  if (!response.ok) {
    let message = "The difference view could not be built.";
    try {
      message = (await response.json()).error || message;
    } catch (error) {
      // keep the generic message when the body is not JSON
    }
    throw new Error(message);
  }
  const objectURL = URL.createObjectURL(await response.blob());
  const image = node("img");
  image.src = objectURL;
  image.alt = "Kept photo, aligned other photo and highlighted pixel differences";
  image.addEventListener("load", () => URL.revokeObjectURL(objectURL));
  image.addEventListener("error", () => URL.revokeObjectURL(objectURL));
  const rows = GRID_NOTE;
  const wrap = node("div", undefined, "burst-difference");
  wrap.append(
    node("p", `${photoById(worst.left)?.name} kept on the left; ${photoById(worst.right)?.name} aligned by a shift of (${worst.shift[0]}, ${worst.shift[1]}) px. Similarity ${worst.similarity}, mean per-channel error ${worst.mae}.`, "muted"),
    image,
    node("p", `Pink pixels changed inside the watch region. The yellow outline marks the most different of the ${rows} comparison blocks (block ${worst.max_cell + 1}).`, "muted"),
  );
  const back = action("← Back to groups", () => renderBurstResults());
  wrap.append(back);
  openDialog("Largest difference in this group", wrap);
}

function renderBurstHistory() {
  const history = state.desk.burst_history || [];
  const list = node("div", undefined, "results");
  if (!history.length) list.append(node("p", "No grouping has been applied to this desk yet.", "muted"));
  for (const entry of history) {
    const card = node("div", undefined, "dialog-item burst-history");
    const detail = node("span");
    detail.append(node("strong", `${entry.mode === "anchor" ? "Representative" : "Mutual"} grouping at ${entry.threshold}+`));
    detail.append(node("small", ` · ${new Date(entry.created_at).toLocaleString()}`));
    const groupLines = node("div", undefined, "burst-history-groups");
    for (const group of entry.groups) {
      if (group.members.length === 1) continue;
      const repName = photoById(group.representative)?.name || "(removed photo)";
      const otherNames = group.members
        .filter((id) => id !== group.representative)
        .map((id) => photoById(id)?.name || "(removed photo)")
        .join(", ");
      groupLines.append(node("p", `${repName} represents: ${otherNames}`, "muted"));
    }
    card.append(detail, groupLines);
    list.append(card);
  }
  const back = action("← Back", () => burst.analysis ? renderBurstResults() : renderBurstSetup());
  openDialog("Applied grouping history", list, back);
}

bind("burst-review", "click", () => {
  if (state.desk.photos.length < 2) {
    notice("Add at least two same-size photographs before a burst review.");
    return;
  }
  openBurst();
});

attempt(async () => {
  state.desks = await request("/release/desks");
  const previous = state.desks.find((desk) => desk.id === localStorage.getItem("photorelease-desk"));
  if (previous) await selectDesk(previous.id);
  else show();
})();
