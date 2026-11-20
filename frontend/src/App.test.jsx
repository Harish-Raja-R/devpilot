// Runtime validation coverage for workspace selection and the AI task composer.
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import { api } from "./api.js";

vi.mock("@monaco-editor/react", () => ({
  default: ({ value, onChange }) => (
    <textarea aria-label="Code editor" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));
vi.mock("./api.js", () => ({ api: vi.fn(), socketUrl: (path) => path }));

const sessionId = "kla-session";
const session = {
  id: sessionId,
  title: "KLA",
  workspace: "C:\\workspace\\KLA",
  status: "idle",
};

let tasks;
let approvals;
let files;
let fileContent;
let proposedFileContent;

function installApiResponses() {
  api.mockImplementation(async (path, options = {}) => {
    if (path === "/api/health") return {};
    if (path === "/api/sessions") return [session];
    if (path === `/api/sessions/${sessionId}/files`) return { files };
    if (path === `/api/sessions/${sessionId}/tasks` && options.method === "POST") {
      const task = JSON.parse(options.body).task;
      tasks = [{ id: "task-1", task, status: "queued" }];
      return { id: "task-1" };
    }
    if (path === `/api/sessions/${sessionId}/tasks`) return tasks;
    if (path === `/api/sessions/${sessionId}/events`) return [];
    if (path === `/api/sessions/${sessionId}/approvals`) return approvals;
    if (path === `/api/sessions/${sessionId}/git/status`) {
      return { is_git_repo: true, changed_files: [] };
    }
    if (path.startsWith(`/api/sessions/${sessionId}/file?path=`)) {
      return { content: fileContent, sha256: "file-hash" };
    }
    if (path === `/api/sessions/${sessionId}/file` && options.method === "PUT") {
      proposedFileContent = JSON.parse(options.body).content;
      approvals = [{
        id: "approval-1",
        kind: "file_write",
        details: { path: "src/app.py", new_file: false, command: "write_file" },
        status: "pending",
      }];
      return { approval_id: "approval-1" };
    }
    if (path === `/api/sessions/${sessionId}/approvals/approval-1` && options.method === "PUT") {
      if (JSON.parse(options.body).approved) fileContent = proposedFileContent;
      approvals = [];
      return {};
    }
    if (path === `/api/sessions/${sessionId}/tasks/task-running/cancel`) return {};
    if (path === `/api/sessions/${sessionId}/tasks/task-1/start`) return {};
    throw new Error(`Unexpected API request: ${options.method || "GET"} ${path}`);
  });
}

async function selectKlaWorkspace() {
  const selector = await screen.findByRole("combobox", { name: "Active coding session" });
  fireEvent.change(selector, { target: { value: sessionId } });
  await waitFor(() => expect(screen.getByRole("textbox", { name: "Coding task" }).disabled).toBe(false));
}

beforeEach(() => {
  tasks = [];
  approvals = [];
  files = [];
  fileContent = "print('before')\n";
  proposedFileContent = "";
  installApiResponses();
  vi.stubGlobal("WebSocket", class {
    close() {}
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("AI task composer", () => {
  it("explains the empty state and keeps sending disabled until a workspace is selected", () => {
    render(<App />);

    expect(screen.getByRole("textbox", { name: "Coding task" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Start coding task" }).disabled).toBe(true);
    expect(screen.getByText("What should we build?")).toBeTruthy();
  });

  it("stays available after selecting a workspace and sends the task through the session API", async () => {
    render(<App />);
    await selectKlaWorkspace();

    const textarea = screen.getByRole("textbox", { name: "Coding task" });
    const sendButton = screen.getByRole("button", { name: "Start coding task" });
    expect(textarea.disabled).toBe(false);
    expect(sendButton.disabled).toBe(true);

    const task = "Summarize the project structure without changing files.";
    fireEvent.change(textarea, { target: { value: task } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(api).not.toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/tasks`,
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.click(sendButton);

    await screen.findByText(task);
    expect(api).toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/tasks`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ task, model_name: null }),
      }),
    );
    expect(api).toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/tasks/task-1/start`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not submit on Shift+Enter and submits on Enter", async () => {
    render(<App />);
    await selectKlaWorkspace();

    const textarea = screen.getByRole("textbox", { name: "Coding task" });
    fireEvent.change(textarea, { target: { value: "first line" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(api).not.toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/tasks`,
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    await screen.findByText("first line");
    expect(api).toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/tasks`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("opens a workspace file, requests save approval, and applies the approved edit", async () => {
    files = ["src/app.py"];
    render(<App />);
    await selectKlaWorkspace();

    fireEvent.click(await screen.findByText("app.py"));
    const editor = await screen.findByRole("textbox", { name: "Code editor" });
    expect(editor.value).toBe("print('before')\n");

    fireEvent.change(editor, { target: { value: "print('after')\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/file`,
      expect.objectContaining({ method: "PUT" }),
    ));

    fireEvent.click(await screen.findByRole("button", { name: /Approve/ }));
    await waitFor(() => expect(editor.value).toBe("print('after')\n"));
    expect(api).toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/approvals/approval-1`,
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ approved: true }),
      }),
    );
  });

  it("keeps the active-task stop control available while disabling new submissions", async () => {
    tasks = [{ id: "task-running", task: "Inspect this workspace", status: "running" }];
    render(<App />);
    const selector = await screen.findByRole("combobox", { name: "Active coding session" });
    fireEvent.change(selector, { target: { value: sessionId } });

    await screen.findByRole("button", { name: "Stop" });
    expect(screen.getByRole("textbox", { name: "Coding task" }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await screen.findByText(/Cancellation requested/);
    expect(api).toHaveBeenCalledWith(
      `/api/sessions/${sessionId}/tasks/task-running/cancel`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("returns to the AI panel after selecting a workspace from the mobile workspace panel", async () => {
    render(<App />);
    const agentToggle = screen.getByRole("button", { name: "Toggle AI Agent panel" });
    const workspaceToggle = screen.getByRole("button", { name: "Toggle workspace panel" });
    fireEvent.click(workspaceToggle);
    expect(workspaceToggle.getAttribute("aria-expanded")).toBe("true");
    expect(agentToggle.getAttribute("aria-expanded")).toBe("false");

    const selector = await screen.findByRole("combobox", { name: "Active coding session" });
    fireEvent.change(selector, { target: { value: sessionId } });
    await waitFor(() => expect(agentToggle.getAttribute("aria-expanded")).toBe("true"));
    expect(workspaceToggle.getAttribute("aria-expanded")).toBe("false");
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Coding task" }).disabled).toBe(false));
  });

  it("announces backend errors instead of leaving the workspace selector in an unexplained state", async () => {
    api.mockImplementation(async (path) => {
      if (path === "/api/health") return {};
      if (path === "/api/sessions") throw new Error("Session list unavailable");
      throw new Error(`Unexpected API request: ${path}`);
    });

    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Session list unavailable");
  });
});
