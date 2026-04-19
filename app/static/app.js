const taskForm = document.getElementById("task-form");
const tasksContainer = document.getElementById("tasks");
const systemStatus = document.getElementById("system-status");
const refreshButton = document.getElementById("refresh-button");
const formMode = document.getElementById("form-mode");
const formMessage = document.getElementById("form-message");
const submitButton = document.getElementById("submit-button");
const cancelEditButton = document.getElementById("cancel-edit-button");

let isRendering = false;

const parseList = (value) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function taskPayload(formData) {
  return {
    name: formData.get("name"),
    enabled: formData.get("enabled") === "true",
    paths: {
      source_dir: formData.get("source_dir"),
      target_root: formData.get("target_root"),
      output_subdir: formData.get("output_subdir"),
      recursive: formData.get("recursive") === "true",
    },
    file_rules: {
      office_extensions: parseList(formData.get("office_extensions")),
      text_extensions: parseList(formData.get("text_extensions")),
      debounce_seconds: Number(formData.get("debounce_seconds")),
    },
    git: {
      enabled: formData.get("git_enabled") === "true",
      branch: formData.get("branch"),
      remote_name: formData.get("remote_name"),
      auto_commit: formData.get("auto_commit") === "true",
      auto_push: formData.get("auto_push") === "true",
      push_delay_seconds: Number(formData.get("push_delay_seconds")),
      commit_message_template: formData.get("commit_message_template"),
    },
  };
}

function setFormMessage(message, level = "info") {
  if (!message) {
    formMessage.hidden = true;
    formMessage.textContent = "";
    formMessage.classList.remove("error");
    return;
  }
  formMessage.hidden = false;
  formMessage.textContent = message;
  formMessage.classList.toggle("error", level === "error");
}

function renderStatus(status) {
  systemStatus.innerHTML = `
    <div><dt>Total Tasks</dt><dd>${status.total_tasks}</dd></div>
    <div><dt>Running Tasks</dt><dd>${status.running_tasks}</dd></div>
  `;
}

function populateForm(task) {
  taskForm.elements.task_id.value = task.id;
  taskForm.elements.name.value = task.name;
  taskForm.elements.enabled.value = String(task.enabled);
  taskForm.elements.source_dir.value = task.paths.source_dir;
  taskForm.elements.target_root.value = task.paths.target_root;
  taskForm.elements.output_subdir.value = task.paths.output_subdir;
  taskForm.elements.recursive.value = String(task.paths.recursive);
  taskForm.elements.office_extensions.value = task.file_rules.office_extensions.join(",");
  taskForm.elements.text_extensions.value = task.file_rules.text_extensions.join(",");
  taskForm.elements.debounce_seconds.value = task.file_rules.debounce_seconds;
  taskForm.elements.git_enabled.value = String(task.git.enabled);
  taskForm.elements.branch.value = task.git.branch;
  taskForm.elements.remote_name.value = task.git.remote_name;
  taskForm.elements.auto_commit.value = String(task.git.auto_commit);
  taskForm.elements.auto_push.value = String(task.git.auto_push);
  taskForm.elements.push_delay_seconds.value = task.git.push_delay_seconds;
  taskForm.elements.commit_message_template.value = task.git.commit_message_template;
  formMode.textContent = `Editing task #${task.id}. Target is the Git root, output writes to '${task.paths.output_subdir}', and sync runs after ${task.file_rules.debounce_seconds} seconds idle plus the 0.5 second worker scan.`;
  submitButton.textContent = "Update Task";
  cancelEditButton.hidden = false;
  setFormMessage("");
  taskForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetForm() {
  taskForm.reset();
  taskForm.elements.task_id.value = "";
  taskForm.elements.enabled.value = "true";
  taskForm.elements.recursive.value = "true";
  taskForm.elements.git_enabled.value = "false";
  taskForm.elements.output_subdir.value = "md";
  taskForm.elements.auto_commit.value = "true";
  taskForm.elements.auto_push.value = "false";
  taskForm.elements.debounce_seconds.value = "1.5";
  taskForm.elements.push_delay_seconds.value = "10";
  taskForm.elements.branch.value = "main";
  taskForm.elements.remote_name.value = "origin";
  taskForm.elements.commit_message_template.value = "auto: sync {task_name}";
  taskForm.elements.office_extensions.value = ".doc,.docx,.ppt,.pptx,.xls,.xlsx,.pdf";
  taskForm.elements.text_extensions.value = ".txt,.md,.markdown,.csv,.tsv,.log";
  formMode.textContent = "New task. Target is the output workspace and Git root. Sync runs after the file has been idle for the debounce interval, checked every 0.5 seconds.";
  submitButton.textContent = "Save Task";
  cancelEditButton.hidden = true;
}

function buildTaskCard(task, taskStatus, events) {
  const article = document.createElement("article");
  article.className = "task-card";
  article.dataset.taskId = task.id;
  article.innerHTML = `
    <h3>${task.name}</h3>
    <p><strong>Source:</strong> ${task.paths.source_dir}</p>
    <p><strong>Target Workspace:</strong> ${task.paths.target_root}</p>
    <p><strong>Output Subdir:</strong> ${task.paths.output_subdir}</p>
    <p><strong>Enabled:</strong> ${task.enabled ? "Yes" : "No"}</p>
    <p><strong>Git:</strong> ${task.git.enabled ? "Enabled" : "Disabled"}</p>
    <p><strong>Git Root:</strong> ${task.paths.target_root}</p>
    <p><strong>Sync Timing:</strong> file idle ${task.file_rules.debounce_seconds}s, worker scan 0.5s</p>
    <p><strong>Running:</strong> ${taskStatus?.running ? "Yes" : "No"}</p>
    <p><strong>Last Error:</strong> ${taskStatus?.last_error || "None"}</p>
    <div class="actions">
      <button data-action="edit" data-id="${task.id}" type="button">Edit</button>
      <button data-action="${task.enabled ? "disable" : "enable"}" data-id="${task.id}" type="button">${task.enabled ? "Disable" : "Enable"}</button>
      <button data-action="rescan" data-id="${task.id}" type="button">Rescan</button>
      <button data-action="push" data-id="${task.id}" type="button">Push</button>
      <button data-action="delete" data-id="${task.id}" type="button" class="secondary">Delete</button>
    </div>
    <h4>Recent Events</h4>
    <ul>${events
      .slice(0, 5)
      .map((event) => `<li>${new Date(event.created_at).toLocaleString()}: ${event.message}</li>`)
      .join("")}</ul>
  `;
  return article;
}

async function renderTasks() {
  if (isRendering) {
    return;
  }
  isRendering = true;
  try {
    const [tasks, status] = await Promise.all([
      fetchJson("/api/tasks"),
      fetchJson("/api/system/status"),
    ]);
    renderStatus(status);
    const taskEntries = await Promise.all(
      tasks.map(async (task) => ({
        task,
        taskStatus: status.statuses.find((item) => item.task_id === task.id),
        events: await fetchJson(`/api/tasks/${task.id}/events`),
      })),
    );

    const existingNodes = new Map(
      [...tasksContainer.querySelectorAll("[data-task-id]")].map((node) => [Number(node.dataset.taskId), node]),
    );
    const nextNodes = [];

    for (const entry of taskEntries) {
      const card = buildTaskCard(entry.task, entry.taskStatus, entry.events);
      const current = existingNodes.get(entry.task.id);
      if (current) {
        current.replaceWith(card);
        existingNodes.delete(entry.task.id);
      } else {
        nextNodes.push(card);
      }
    }

    for (const leftover of existingNodes.values()) {
      leftover.remove();
    }

    for (const node of nextNodes) {
      tasksContainer.append(node);
    }
  } finally {
    isRendering = false;
  }
}

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(taskForm);
  const taskId = formData.get("task_id");
  try {
    await fetchJson(taskId ? `/api/tasks/${taskId}` : "/api/tasks", {
      method: taskId ? "PUT" : "POST",
      body: JSON.stringify(taskPayload(formData)),
    });
    resetForm();
    setFormMessage(taskId ? "Task updated." : "Task created.");
    await renderTasks();
  } catch (error) {
    setFormMessage(error.message, "error");
  }
});

tasksContainer.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  try {
    if (button.dataset.action === "edit") {
      const tasks = await fetchJson("/api/tasks");
      const task = tasks.find((item) => item.id === Number(button.dataset.id));
      if (task) {
        populateForm(task);
      }
      return;
    }
    if (button.dataset.action === "delete") {
      await fetchJson(`/api/tasks/${button.dataset.id}`, { method: "DELETE" });
      setFormMessage("Task deleted.");
      if (taskForm.elements.task_id.value === button.dataset.id) {
        resetForm();
      }
    } else {
      await fetchJson(`/api/tasks/${button.dataset.id}/${button.dataset.action}`, {
        method: "POST",
      });
      setFormMessage(button.dataset.action === "enable" ? "Task enabled." : "Task disabled.");
    }
    await renderTasks();
  } catch (error) {
    setFormMessage(error.message, "error");
  }
});

refreshButton.addEventListener("click", renderTasks);
cancelEditButton.addEventListener("click", resetForm);

renderTasks().catch((error) => {
  systemStatus.innerHTML = `<div><dt>Error</dt><dd>${error.message}</dd></div>`;
});

setInterval(() => {
  renderTasks().catch(() => {});
}, 5000);

resetForm();
