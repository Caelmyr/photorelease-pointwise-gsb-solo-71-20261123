"use strict";

const byId = (id) => document.getElementById(id);
const state = {desks: [], desk: null, photo: null, view: "working", tool: null, drag: null, review: null, plans: null};
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
  byId("photo-list").replaceChildren(...desk.photos.map((item) => {
    const tail = !item.used ? "Excluded" : (item.approved ? "Approved" : "Needs review");
    const button = collectionEntry(item.name, tail, () => selectPhoto(item.id), "photo-item");
    const thumbnail = node("img");
    thumbnail.alt = "";
    thumbnail.loading = "lazy";
    thumbnail.src = `${photoURL(item)}/image/thumb`;
    button.prepend(thumbnail);
    button.classList.toggle("active", state.photo === item.id);
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
    const detail = photo.jpeg_quality === null || photo.jpeg_quality === undefined
      ? `${photo.width} × ${photo.height} px · PNG · ${formatBytes(photo.bytes)}`
      : `${photo.width} × ${photo.height} px · JPEG Q${photo.jpeg_quality} · ${formatBytes(photo.bytes)}`;
    text.append(node("small", ` · ${detail}`));
    row.append(text, link("Open saved photo", `${deskURL()}/issues/${issueId}/photos/${photo.source_id}`));
    list.append(row);
  }
  const actions = node("div", undefined, "dialog-actions");
  actions.append(action("← Issue history", showIssueHistory), link("Download ZIP", `${deskURL()}/issues/${issueId}/download`));
  const children = [list];
  if (issue.manifest) {
    children.push(node("p", `Manifested contents total ${formatBytes(issue.manifest.photos.reduce((sum, row) => sum + row.bytes, 0) + issue.manifest.contact_sheets.reduce((sum, row) => sum + row.bytes, 0))} before ZIP packaging.`, "plan-note"));
  }
  openDialog(issue.title, ...children, actions);
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

function formatBytes(value) {
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function labelFor(photo) {
  return photo.style.caption || photo.name;
}

function openPlanDialog() {
  const included = state.desk.photos.filter((photo) => photo.used);
  const form = node("form", undefined, "plan-form");
  const titleField = node("label", "Public issue title");
  titleField.classList.add("wide");
  const titleInput = node("input");
  titleInput.value = state.desk.title;
  titleInput.maxLength = 75;
  titleInput.required = true;
  titleField.append(titleInput);

  const capField = node("label", "Total package cap (MB)");
  const capInput = node("input");
  capInput.type = "number";
  capInput.min = "0.5";
  capInput.max = "96";
  capInput.step = "0.5";
  capInput.value = "25";
  capInput.required = true;
  capField.append(capInput);

  const qualityField = node("label", "Minimum JPEG quality");
  const qualityInput = node("input");
  qualityInput.type = "number";
  qualityInput.min = "40";
  qualityInput.max = "92";
  qualityInput.step = "1";
  qualityInput.value = "70";
  qualityInput.required = true;
  qualityField.append(qualityInput);

  const leadField = node("label", "Long-read lead photo");
  leadField.classList.add("wide");
  const leadSelect = node("select");
  for (const photo of included) {
    const option = node("option", labelFor(photo));
    option.value = photo.id;
    leadSelect.append(option);
  }
  leadField.append(leadSelect);

  const compare = node("button", "Compare two shippable plans", "primary");
  compare.type = "submit";
  form.append(titleField, capField, qualityField, leadField, compare);

  const result = node("div");
  form.addEventListener("submit", attempt(async (event) => {
    event.preventDefault();
    result.replaceChildren();
    const capBytes = Math.round(Number(capInput.value) * 1024 * 1024);
    const plans = await request(`${deskURL()}/package-plans`, "POST", {
      title: titleInput.value,
      cap_bytes: capBytes,
      min_quality: qualityInput.valueAsNumber,
      lead_photo_id: leadSelect.value,
    });
    state.plans = plans;
    renderPlanResults(plans, result, {
      title: titleInput.value, capBytes, minQuality: qualityInput.valueAsNumber, leadId: leadSelect.value,
    });
  }));
  openDialog("Create public issue", form, node("p", "PNG photos, contact sheets, the manifest and ZIP overhead stay fixed; only JPEG quality is adjusted.", "plan-note"), result);
}

function planTable(plan, included) {
  const table = node("table");
  const head = node("thead");
  const headRow = node("tr");
  for (const text of ["Photo", "Format", "Quality", "File size"]) {
    headRow.append(node("th", text));
  }
  head.append(headRow);
  const body = node("tbody");
  for (const row of plan.photos) {
    const tr = node("tr");
    const name = included.find((photo) => photo.id === row.source_id)?.name ?? row.name;
    tr.append(
      node("td", name),
      node("td", row.format.toUpperCase()),
      node("td", row.jpeg_quality === null ? "fixed PNG" : `Q${row.jpeg_quality}`),
      node("td", formatBytes(row.bytes)),
    );
    body.append(tr);
  }
  const foot = node("tfoot");
  const sheetBytes = plan.contact_sheets.reduce((sum, sheet) => sum + sheet.bytes, 0);
  foot.append(
    summaryRow("Contact sheets", formatBytes(sheetBytes)),
    summaryRow("Manifest", formatBytes(plan.manifest_bytes)),
    summaryRow("ZIP overhead", formatBytes(plan.overhead_bytes)),
    summaryRow("Total ZIP", formatBytes(plan.total_bytes)),
  );
  table.append(head, body, foot);
  return table;
}

function summaryRow(label, value) {
  const tr = node("tr");
  const first = node("td", label);
  const last = node("td", value);
  last.colSpan = 3;
  tr.append(first, last);
  return tr;
}

function planCard(headline, plan, included, badge) {
  const card = node("div", undefined, "plan-card");
  const heading = node("div");
  heading.append(node("h3", headline), node("span", " "), badge);
  const qualities = plan.photos.filter((row) => row.jpeg_quality !== null).map((row) => row.jpeg_quality);
  const qualityText = qualities.length
    ? `JPEG quality ${Math.min(...qualities)}–${Math.max(...qualities)}`
    : "No JPEG photos";
  const meta = node("div", undefined, "plan-meta");
  meta.append(
    node("span", qualityText),
    node("span", `Total ZIP ${formatBytes(plan.total_bytes)}`),
  );
  card.append(heading, meta, planTable(plan, included));
  return card;
}

function renderPlanResults(plans, container, settings) {
  const included = state.desk.photos.filter((photo) => photo.used);
  if (!plans.feasible) {
    renderInfeasible(plans, container, settings);
    return;
  }
  const cards = node("div", undefined, "plan-results");
  const balancedCard = planCard(
    "Balanced: spread the loss evenly",
    plans.balanced, included, node("span", "minimizes the deepest quality drop", "plan-badge"),
  );
  const leadName = included.find((photo) => photo.id === plans.lead_photo_id)?.name ?? "Lead photo";
  const leadCard = planCard(
    `Lead-protected: ${leadName}`,
    plans.lead, included, node("span", "lead kept at the highest quality", "plan-badge locked"),
  );
  cards.append(balancedCard, leadCard);

  const actions = node("div", undefined, "dialog-actions");
  const choose = (card, plan) => action(`Issue this plan · ${formatBytes(plan.total_bytes)}`, async () => {
    for (const element of cards.children) element.classList.remove("chosen");
    card.classList.add("chosen");
    const desk = await mutate(`${deskURL()}/issues`, "POST", {
      title: settings.title,
      plan: {
        kind: plan.kind,
        cap_bytes: settings.capBytes,
        min_quality: settings.minQuality,
        lead_photo_id: settings.leadId,
        qualities: plan.qualities,
      },
    });
    dialog.close();
    state.desk = desk;
    showIssueHistory();
  }, "primary");
  actions.append(choose(balancedCard, plans.balanced), choose(leadCard, plans.lead));
  container.replaceChildren(cards, actions,
    node("p", "Both plans keep the current crop, pixel dimensions and PNG/JPEG choice. Approving a plan issues that exact ZIP; earlier issues stay available unchanged in Issue history.", "plan-note"));
}

function renderInfeasible(plans, container, settings) {
  const fixed = plans.fixed;
  const box = node("div", undefined, "infeasible");
  const overflow = fixed.floor_total_bytes - plans.cap_bytes;
  box.append(
    node("h3", "No package fits the cap, even at the lowest JPEG quality."),
    node("p", `At quality Q${plans.min_quality} the ZIP is ${formatBytes(fixed.floor_total_bytes)}, ${formatBytes(overflow)} over the ${formatBytes(plans.cap_bytes)} cap. Your draft settings are kept; nothing was changed or issued.`),
  );
  const table = node("table");
  const body = node("tbody");
  for (const row of fixed.rows) {
    const tr = node("tr");
    tr.append(
      node("td", row.name),
      node("td", row.format.toUpperCase()),
      node("td", row.fixed ? "fixed" : `Q${plans.min_quality} floor`),
      node("td", formatBytes(row.bytes)),
    );
    body.append(tr);
  }
  body.append(
    summaryRow("Contact sheets", formatBytes(fixed.sheet_bytes)),
    summaryRow("Manifest", formatBytes(fixed.manifest_bytes)),
    summaryRow("ZIP overhead", formatBytes(fixed.overhead_bytes)),
    summaryRow("Fixed subtotal (PNGs + sheets + manifest + overhead)", formatBytes(fixed.fixed_bytes)),
    summaryRow(`JPEG photos at Q${plans.min_quality}`, formatBytes(fixed.jpeg_floor_bytes)),
    summaryRow("Smallest possible ZIP", formatBytes(fixed.floor_total_bytes)),
  );
  table.append(body);
  box.append(table);
  box.append(node("p", "Raise the package cap, lower the minimum JPEG quality, switch a JPEG to a smaller output edge, or exclude a photo — then compare again.", "plan-note"));
  container.replaceChildren(box);
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
  openPlanDialog();
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

attempt(async () => {
  state.desks = await request("/release/desks");
  const previous = state.desks.find((desk) => desk.id === localStorage.getItem("photorelease-desk"));
  if (previous) await selectDesk(previous.id);
  else show();
})();
