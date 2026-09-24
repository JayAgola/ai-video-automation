"use strict";
const API = "/api/v1/dashboard";

function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(r.status + " " + (await r.text()));
  return r.json();
}

async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  const data = await r.json().catch(function () { return {}; });
  if (!r.ok) throw new Error(data.detail || r.status);
  return data;
}

function fmtTime(ts) {
  if (!ts) return "Not available";
  try { return new Date(ts).toLocaleString(); } catch (e) { return ts; }
}

function badge(s) {
  const v = esc(String(s || "UNKNOWN")).replace(/\s+/g, "_");
  return '<span class="badge ' + v + '">' + esc(s || "Unknown") + "</span>";
}

function loadSystem() {
  jget(API + "/system").then(function (s) {
    document.getElementById("system").innerHTML =
      "Ollama: " + esc(s.ollama.status || "?") +
      " &middot; Visual: " + esc(s.visual_provider) +
      " &middot; Research: " + esc(s.research_provider);
  }).catch(function () {
    document.getElementById("system").textContent = "System status unavailable";
  });
}

function loadProjects() {
  return jget(API + "/projects").then(function (d) {
    let active = 0, completed = 0, failed = 0;
    d.projects.forEach(function (p) {
      if (p.status === "IN_PROGRESS") active += 1;
      else if (p.status === "COMPLETED") completed += 1;
      else if (p.status === "FAILED") failed += 1;
    });
    document.getElementById("counts").innerHTML =
      "<span>Total <b>" + d.count + "</b></span>" +
      "<span>Active <b>" + active + "</b></span>" +
      "<span>Completed <b>" + completed + "</b></span>" +
      "<span>Failed <b>" + failed + "</b></span>";
    const tb = document.querySelector("#projects tbody");
    tb.innerHTML = "";
    document.getElementById("noprojects").style.display = d.projects.length ? "none" : "block";
    d.projects.forEach(function (p) {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      tr.onclick = function () { selectProject(p.project_id); };
      const td = function (html) { const c = document.createElement("td"); c.innerHTML = html; return c; };
      tr.appendChild(td("<b>" + esc(p.project_id) + "</b>"));
      tr.appendChild(td(esc(p.topic || "Not available")));
      tr.appendChild(td(badge(p.status || "UNKNOWN")));
      tr.appendChild(td(esc(p.current_step || "Not available")));
      tr.appendChild(td(esc(p.progress_percent != null ? p.progress_percent + "%" : "Not available") +
        " &middot; Scenes " +
        esc(p.scenes_completed != null ? p.scenes_completed + "/" + p.scenes_total : "n/a")));
      tr.appendChild(td(badge(p.review_status || "NOT_READY")));
      tr.appendChild(td(esc(fmtTime(p.updated_at))));
      tb.appendChild(tr);
    });
  });
}

function renderSteps(pipeline) {
  if (!pipeline || !pipeline.steps) return '<p class="no">State unavailable</p>';
  let html = '<div class="stepgrid">';
  pipeline.steps.forEach(function (s) {
    html += '<span class="badge ' + esc(s.status) + '">' + esc(s.label) + "</span>";
  });
  html += '</div><p>Pipeline progress: <b>' +
    (pipeline.percent != null ? pipeline.percent + "%" : "Not available") + "</b> (" +
    pipeline.completed + "/" + pipeline.total + ")</p>";
  return html;
}

function renderArtifacts(arts) {
  if (!arts) return "<p>Not available</p>";
  let html = '<ul class="artifacts">';
  Object.keys(arts).forEach(function (k) {
    const a = arts[k];
    let extra = "";
    if (a.exists && a.kind === "dir" && a.count != null) extra = " (" + a.count + " files)";
    if (a.exists && a.kind === "video") extra = " — Final video available";
    html += '<li><span class="' + (a.exists ? "ok" : "no") + '">&#9679;</span> ' + k + extra + "</li>";
  });
  html += "</ul>";
  return html;
}

function renderLogs(logs) {
  if (!logs || !logs.length) return "<p>No logs yet for this project.</p>";
  let html = '<ul class="logs">';
  logs.slice().reverse().forEach(function (l) {
    html += '<li class="logline"><span class="lvl ' + esc(l.level) + '">' + esc(l.level) + "</span> "
      + esc(l.timestamp) + " [<b>" + esc(l.component) + "</b>] " + esc(l.message) + "</li>";
  });
  html += "</ul>";
  return html;
}

function renderReview(review, projectId) {
  const r = review || {};
  const status = r.status || "NOT_READY";
  let html = '<p>Review Status: ' + badge(status) + "</p>";
  if (status === "NOT_READY") {
    html += '<p class="no">Final video is not ready for review.</p>';
  } else {
    if (r.reviewer) html += "<p>Reviewer: " + esc(r.reviewer) + " &middot; " + esc(fmtTime(r.updated_at)) + "</p>";
    if (r.note) html += "<p>Note: " + esc(r.note) + "</p>";
    if (status === "PENDING") {
      html += '<p><textarea id="review-note" rows="2" cols="50" placeholder="Optional note (required on reject)"></textarea></p>' +
        '<button onclick="reviewAction(\'review/approve\',' + JSON.stringify(projectId) + ')">APPROVE</button> ' +
        '<button onclick="reviewAction(\'review/reject\',' + JSON.stringify(projectId) + ')">REJECT</button>';
    } else if (status === "APPROVED") {
      html += '<button onclick="reviewAction(\'review/reset\',' + JSON.stringify(projectId) + ')">SEND BACK TO REVIEW</button>';
    } else if (status === "REJECTED") {
      html += '<button onclick="reviewAction(\'review/reset\',' + JSON.stringify(projectId) + ')">SEND BACK TO REVIEW</button>';
    } else {
      html += '<p><button disabled>APPROVE</button> <button disabled>REJECT</button></p>';
    }
  }
  if (r.history && r.history.length) {
    html += "<h4>History</h4><ul>";
    r.history.slice().reverse().forEach(function (h) {
      html += "<li>" + esc(h.timestamp) + " <b>" + esc(h.action) + "</b> by " + esc(h.reviewer) +
        (h.note ? " — " + esc(h.note) : "") + "</li>";
    });
    html += "</ul>";
  }
  return html;
}

function renderVideo(fv, projectId) {
  if (!fv || !fv.available) return '<p class="no">Final video not available for playback.</p>';
  let meta = "";
  if (fv.duration_sec != null) meta += "Duration: " + fv.duration_sec + "s ";
  if (fv.size_bytes != null) meta += "Size: " + fv.size_bytes + " B";
  return "<p><b>Final Video</b> " + esc(meta) + "</p>" +
    '<video controls width="640" src="' + API + "/projects/" + encodeURIComponent(projectId) + '/video"></video>';
}

function reviewAction(endpoint, projectId) {
  const action = endpoint.split("/")[1];
  const noteEl = document.getElementById("review-note");
  const note = noteEl ? noteEl.value : "";
  if (action === "approve" && !confirm("Approve this video?\n\nThis will mark the project as approved for future publishing workflows.")) return;
  if (action === "reject" && !confirm("Reject this video?\n\nPlease provide a reason in the note field.")) return;
  if (action === "reject" && !note.trim()) { alert("A rejection note is required."); return; }
  jpost(API + "/projects/" + encodeURIComponent(projectId) + "/" + endpoint, { note: note })
    .then(function () { return selectProject(projectId); })
    .catch(function (e) { alert("Review action failed: " + e.message); });
}

function renderYoutube(yt, d) {
  // yt = {status, authenticated, configured, channel, preview, error}
  let html = "";
  const auth = !!yt.authenticated;
  html += "<p>Account: <b>" + (auth ? "Connected" : "Not Connected") + "</b>";
  if (yt.channel && yt.channel.title) html += " &middot; Channel: " + esc(yt.channel.title);
  html += "</p>";
  if (!auth) {
    html += '<button id="yt-connect">Connect YouTube</button>';
    if (yt.configured === false) html += '<p class="no">OAuth client not configured (set YOUTUBE_CLIENT_SECRET_FILE in .env).</p>';
  }
  const p = yt.preview;
  if (p) {
    html += "<p>Upload status: " + badge(p.upload_status) + " &middot; Review: " + badge(p.review_status) + "</p>";
    html += "<p>Title: <b>" + esc(p.title) + "</b></p>";
    if (p.description) html += "<p>Description: " + esc(p.description.slice(0, 200)) + (p.description.length > 200 ? "…" : "") + "</p>";
    if (p.tags && p.tags.length) html += "<p>Tags: " + esc(p.tags.join(", ")) + "</p>";
    html += "<p>Privacy: <b>" + esc((p.privacy_status || "private").toUpperCase()) + "</b> &middot; File: " +
      esc(p.video && p.video.filename) + (p.video && p.video.size != null ? " (" + p.video.size + " B)" : "") + "</p>";
    if (p.existing && p.existing.status === "UPLOADED") {
      html += '<p class="ok">Uploaded: video ' + esc(p.existing.video_id) + "</p>";
      if (p.existing.url) html += '<p><a href="' + esc(p.existing.url) + '" target="_blank" rel="noopener noreferrer">' + esc(p.existing.url) + "</a></p>";
      if (p.existing.uploaded_at) html += "<p>Uploaded at: " + esc(fmtTime(p.existing.uploaded_at)) + "</p>";
    } else if (p.upload_status === "READY") {
      html += '<p><label>Privacy: <select id="yt-privacy"><option value="private">PRIVATE</option><option value="unlisted">UNLISTED</option><option value="public">PUBLIC (visible to everyone)</option></select></label></p>';
      html += '<button id="yt-upload">Upload to YouTube</button>';
    } else if (!p.ready) {
      html += '<p class="no">Upload blocked: ' + esc(p.upload_status) + (p.review_status !== "APPROVED" ? " — human review must be APPROVED first." : "") + "</p>";
    }
  } else if (yt.error) {
    html += '<p class="no">YouTube status unavailable: ' + esc(yt.error) + "</p>";
  }
  return html;
}

function wireYoutube(projectId, d) {
  const connect = document.getElementById("yt-connect");
  if (connect) connect.onclick = function () {
    jget(API + "/youtube/auth_url").then(function (r) {
      if (r.url) window.open(r.url, "_blank", "noopener");
    }).catch(function (e) { alert("OAuth start failed: " + e.message); });
  };
  const btn = document.getElementById("yt-upload");
  if (btn) btn.onclick = function () {
    const privacy = (document.getElementById("yt-privacy") || {}).value || "private";
    if (!confirm("You are about to upload:\n\nTitle: " + d.preview.title +
                 "\nPrivacy: " + privacy.toUpperCase() + "\nProject: " + projectId +
                 "\nHuman Review: APPROVED\n\nContinue?" +
                 (privacy === "public" ? "\n\nWARNING: PUBLIC videos are visible to everyone." : ""))) return;
    jpost(API + "/projects/" + encodeURIComponent(projectId) + "/youtube/upload",
          { confirm: true, privacy_status: privacy })
      .then(function () { return selectProject(projectId); })
      .catch(function (e) { alert("Upload failed: " + e.message); });
  };
}

function loadYoutubeSection(projectId) {
  const el = document.getElementById("yt-section");
  if (!el) return;
  Promise.all([
    jget(API + "/youtube/status").catch(function () { return { authenticated: false, error: "status unavailable" }; }),
    jget(API + "/projects/" + encodeURIComponent(projectId) + "/youtube/preview").catch(function (e) { return null; })
  ]).then(function (res) {
    const st = res[0], preview = res[1];
    el.innerHTML = renderYoutube({
      authenticated: st.authenticated, configured: st.configured,
      channel: st.channel, error: st.error, preview: preview
    }, preview);
    wireYoutube(projectId, preview || {});
  });
}

function selectProject(id) {
  return jget(API + "/projects/" + encodeURIComponent(id))
    .then(function (d) {
      const sec = document.getElementById("detail");
      sec.style.display = "block";
      const state = d.state || {};
      const data = state.data || {};
      const fv = d.final_video || {};
      let fvInfo = fv.available ? "Final video available" : "Final video not yet available";
      if (fv.duration_sec != null) fvInfo += " (duration " + fv.duration_sec + "s)";
      if (fv.size_bytes != null) fvInfo += " (size " + fv.size_bytes + " B)";
      const selTopic = d.selected_topic && d.selected_topic.topic;
      const topic = selTopic || data.topic || "Not available";
      const seo = d.seo;
      let seoHtml = "<p>Not available</p>";
      if (seo) {
        seoHtml = "";
        if (seo.recommended_title) seoHtml += "<p>Recommended title: <b>" + esc(seo.recommended_title) + "</b></p>";
        if (seo.title_options) seoHtml += "<p>Titles: " + seo.title_options.map(esc).join(" | ") + "</p>";
        if (seo.tags) seoHtml += "<p>Tags: " + esc(seo.tags.join(", ")) + "</p>";
        if (seo.hashtags) seoHtml += "<p>Hashtags: " + esc(seo.hashtags.join(" ")) + "</p>";
      }
      document.getElementById("detail-title").innerHTML =
        "Project: " + esc(d.project_id) + " " + badge(state.status || "UNKNOWN");
      document.getElementById("detail-body").innerHTML =
        "<section><h3>Info</h3>" +
        "<p>Topic: <b>" + esc(topic) + "</b></p>" +
        "<p>Current step: " + esc(state.current_step || "Not available") + "</p>" +
        "<p>Created: " + esc(fmtTime(state.created_at)) + " &middot; Updated: " + esc(fmtTime(state.updated_at)) + "</p>" +
        '<p class="' + (fv.available ? "ok" : "no") + '">' + esc(fvInfo) + "</p>" +
        "</section>" +
        "<section><h3>Pipeline progress</h3>" + renderSteps(d.pipeline) + "</section>" +
        "<section><h3>Scenes</h3><p>" +
        esc(d.scenes && d.scenes.detail ? d.scenes.detail + " (" + d.scenes.percent + "%)" : "Not available") +
        "</p></section>" +
        "<section><h3>Human Review</h3>" + renderReview(d.review, d.project_id) + "</section>" +
        "<section><h3>YouTube</h3><div id='yt-section'>Loading…</div></section>" +
        "<section><h3>Video Review</h3>" + renderVideo(fv, d.project_id) + "</section>" +
        "<section><h3>SEO</h3>" + seoHtml + "</section>" +
        "<section><h3>Artifacts</h3>" + renderArtifacts(d.artifacts) + "</section>" +
        "<section><h3>Logs</h3><button onclick='event.stopPropagation();refreshLogs(\"" +
        esc(d.project_id) + "\")'>Refresh logs</button><div id='logs'>" + renderLogs([]) + "</div></section>";
      return refreshLogs(d.project_id).then(function () { loadYoutubeSection(d.project_id); });
    }).catch(function (e) {
      document.getElementById("detail").style.display = "block";
      document.getElementById("detail-body").innerHTML = '<p class="no">Error: ' + esc(e.message) + "</p>";
    });
}

function refreshLogs(id) {
  return jget(API + "/projects/" + encodeURIComponent(id) + "/logs").then(function (d) {
    const el = document.getElementById("logs");
    if (el) el.innerHTML = renderLogs(d.logs);
  });
}

loadSystem();
loadProjects();