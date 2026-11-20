import Editor from "@monaco-editor/react";
import {
  Activity,
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock3,
  Code2,
  Command,
  FileCode2,
  FilePlus2,
  Folder,
  GitBranch,
  GitCompareArrows,
  LoaderCircle,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  Square,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, socketUrl } from "./api.js";

const languageByExtension = {
  py: "python",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  json: "json",
  md: "markdown",
  yml: "yaml",
  yaml: "yaml",
  css: "css",
  html: "html",
  toml: "ini",
  sh: "shell",
  ps1: "powershell",
};

function languageFor(path) {
  return languageByExtension[path?.split(".").pop()?.toLowerCase()] || "plaintext";
}

function App() {
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [workspaceInput, setWorkspaceInput] = useState("");
  const [agentPanelOpen, setAgentPanelOpen] = useState(true);
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  const [files, setFiles] = useState([]);
  const [tabs, setTabs] = useState([]);
  const [documents, setDocuments] = useState({});
  const [activePath, setActivePath] = useState("");
  const [fileHash, setFileHash] = useState("");
  const [editorValue, setEditorValue] = useState("");
  const [events, setEvents] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [taskInput, setTaskInput] = useState("");
  const [modelName, setModelName] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [gitDiff, setGitDiff] = useState("");
  const [gitStatus, setGitStatus] = useState(null);
  const [panel, setPanel] = useState("terminal");
  const [health, setHealth] = useState("checking");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [cancellingTaskId, setCancellingTaskId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [collapsed, setCollapsed] = useState({});
  const socketRef = useRef(null);
  const sessionIdRef = useRef("");
  const editorRef = useRef(null);
  const activePathRef = useRef("");
  const documentsRef = useRef({});
  const eventEndRef = useRef(null);

  activePathRef.current = activePath;
  documentsRef.current = documents;
  const activeTask = useMemo(
    () => tasks.find((task) => task.status === "running" || task.status === "queued"),
    [tasks],
  );
  const activeDocument = activePath ? documents[activePath] : null;
  const hasUnsavedChanges = Boolean(activeDocument && activeDocument.content !== activeDocument.savedContent);

  const loadSessions = useCallback(async () => {
    const data = await api("/api/sessions");
    setSessions(data);
  }, []);

  const refreshSession = useCallback(async (id) => {
    if (!id) return;
    const [fileData, sessionTasks, sessionEvents, pending, git] = await Promise.all([
      api(`/api/sessions/${id}/files`),
      api(`/api/sessions/${id}/tasks`),
      api(`/api/sessions/${id}/events`),
      api(`/api/sessions/${id}/approvals`),
      api(`/api/sessions/${id}/git/status`),
    ]);
    if (sessionIdRef.current !== id) return;
    setFiles(fileData.files);
    setTasks(sessionTasks);
    setEvents(sessionEvents);
    setApprovals(pending.filter((item) => item.status === "pending"));
    setGitStatus(git);
    setWorkspacePath(sessions.find((session) => session.id === id)?.workspace || "");
  }, [sessions]);

  useEffect(() => {
    api("/api/health")
      .then(() => setHealth("online"))
      .catch(() => setHealth("offline"));
    loadSessions().catch((cause) => setError(cause.message));
  }, [loadSessions]);

  useEffect(() => {
    if (!sessionId) return undefined;
    refreshSession(sessionId).catch((cause) => setError(cause.message));
    const url = socketUrl(`/api/sessions/${sessionId}/events/ws`);
    const socket = new WebSocket(url);
    socketRef.current = socket;
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data);
      setEvents((current) => (current.some((item) => item.id === event.id) ? current : [...current, event]));
      if (event.type === "file_changed" || event.type === "file_deleted") {
        refreshSession(sessionId).catch((cause) => setError(cause.message));
        if (event.type === "file_deleted" && event.payload.path === activePathRef.current) {
          setActivePath("");
          setEditorValue("");
          setDocuments((current) => {
            const next = { ...current };
            delete next[event.payload.path];
            return next;
          });
        }
      }
      if (event.type === "command_result") {
        refreshSession(sessionId).catch((cause) => setError(cause.message));
        for (const [path, document] of Object.entries(documentsRef.current)) {
          if (document.content !== document.savedContent) continue;
          api(`/api/sessions/${sessionId}/file?path=${encodeURIComponent(path)}`)
            .then((file) => {
              const currentDocument = documentsRef.current[path];
              if (!currentDocument || currentDocument.content !== currentDocument.savedContent) return;
              setDocuments((current) => ({
                ...current,
                [path]: current[path]?.content === current[path]?.savedContent
                  ? { content: file.content, savedContent: file.content, hash: file.sha256 }
                  : current[path],
              }));
              if (activePathRef.current === path) {
                setEditorValue(file.content);
                setFileHash(file.sha256);
              }
            })
            .catch((cause) => {
              if (!cause.message.includes("not a file")) setError(cause.message);
            });
        }
      }
      if (event.type === "task_finished" || event.type === "task_error") {
        setCancellingTaskId("");
        refreshSession(sessionId).catch((cause) => setError(cause.message));
      }
      if (event.type === "approval_required") {
        setApprovals((current) => [...current.filter((item) => item.id !== event.payload.id), {
          id: event.payload.id,
          kind: event.payload.kind,
          details: event.payload.details,
          status: "pending",
        }]);
      }
      if (event.type === "approval_resolved") {
        setApprovals((current) => current.filter((item) => item.id !== event.payload.id));
      }
    };
    socket.onerror = () => setError("Live event stream disconnected. Refresh the session to reconnect.");
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [sessionId, refreshSession]);

  useEffect(() => {
    eventEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events, panel]);

  const createSession = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const created = await api("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace: workspaceInput }),
      });
      await loadSessions();
      sessionIdRef.current = created.id;
      setSessionId(created.id);
      setWorkspacePanelOpen(false);
      setAgentPanelOpen(true);
      setWorkspacePath(created.workspace);
      setTasks([]);
      setEvents([]);
      setApprovals([]);
      setGitStatus(null);
      setTaskInput("");
      setTabs([]);
      setDocuments({});
      setActivePath("");
      setEditorValue("");
      setWorkspaceInput("");
    } catch (cause) {
      setError(cause.message);
    } finally {
      setLoading(false);
    }
  };

  const selectSession = async (id) => {
    sessionIdRef.current = id;
    setSessionId(id);
    setWorkspacePanelOpen(false);
    setAgentPanelOpen(true);
    setWorkspacePath(sessions.find((session) => session.id === id)?.workspace || "");
    setFiles([]);
    setTasks([]);
    setEvents([]);
    setApprovals([]);
    setGitStatus(null);
    setTaskInput("");
    setTabs([]);
    setDocuments({});
    setActivePath("");
    setEditorValue("");
    setError("");
  };

  const openFile = async (path) => {
    if (documents[path]) {
      setActivePath(path);
      setEditorValue(documents[path].content);
      setFileHash(documents[path].hash);
      return;
    }
    setLoading(true);
    try {
      const response = await api(`/api/sessions/${sessionId}/file?path=${encodeURIComponent(path)}`);
      setTabs((current) => [...current, path]);
      setActivePath(path);
      setEditorValue(response.content);
      setFileHash(response.sha256);
      setDocuments((current) => ({
        ...current,
        [path]: { content: response.content, savedContent: response.content, hash: response.sha256 },
      }));
    } catch (cause) {
      setError(cause.message);
    } finally {
      setLoading(false);
    }
  };

  const saveFile = async () => {
    if (!activePath || !sessionId) return;
    setSaving(true);
    setError("");
    try {
      const proposal = await api(`/api/sessions/${sessionId}/file`, {
        method: "PUT",
        body: JSON.stringify({
          path: activePath,
          content: editorValue,
          expected_sha256: fileHash || null,
        }),
      });
      setNotice(`Save requested. Approve file change ${proposal.approval_id.slice(0, 8)} in the right panel.`);
      await loadApprovals();
    } catch (cause) {
      setError(cause.message);
    } finally {
      setSaving(false);
    }
  };

  const loadApprovals = async () => {
    if (!sessionId) return;
    const pending = await api(`/api/sessions/${sessionId}/approvals`);
    setApprovals(pending.filter((item) => item.status === "pending"));
  };

  const resolveApproval = async (approval, approved) => {
    setError("");
    try {
      await api(`/api/sessions/${sessionId}/approvals/${approval.id}`, {
        method: "PUT",
        body: JSON.stringify({ approved }),
      });
      setApprovals((current) => current.filter((item) => item.id !== approval.id));
      if (approved && approval.kind === "file_write") {
        const path = approval.details.path;
        const saved = await api(`/api/sessions/${sessionId}/file?path=${encodeURIComponent(path)}`);
        setDocuments((current) => ({
          ...current,
          [path]: { content: saved.content, savedContent: saved.content, hash: saved.sha256 },
        }));
        if (path === activePathRef.current) {
          setEditorValue(saved.content);
          setFileHash(saved.sha256);
        }
      }
      setNotice(approved ? "Action approved and applied." : "Action rejected.");
      await refreshSession(sessionId);
    } catch (cause) {
      setError(cause.message);
    }
  };

  const submitTask = async (event) => {
    event.preventDefault();
    if (!taskInput.trim() || !sessionId) return;
    setLoading(true);
    setError("");
    try {
      const task = await api(`/api/sessions/${sessionId}/tasks`, {
        method: "POST",
        body: JSON.stringify({ task: taskInput, model_name: modelName || null }),
      });
      setTaskInput("");
      await api(`/api/sessions/${sessionId}/tasks/${task.id}/start`, {
        method: "POST",
        body: JSON.stringify({ model_name: modelName || null }),
      });
      await refreshSession(sessionId);
      setPanel("activity");
    } catch (cause) {
      setError(cause.message);
    } finally {
      setLoading(false);
    }
  };

  const cancelTask = async (task) => {
    if (!task || !sessionId) return;
    setCancellingTaskId(task.id);
    setError("");
    try {
      await api(`/api/sessions/${sessionId}/tasks/${task.id}/cancel`, { method: "POST" });
      setNotice("Cancellation requested. An active model request or command may finish before it stops.");
    } catch (cause) {
      setCancellingTaskId("");
      setError(cause.message);
    }
  };

  const runTests = async () => {
    try {
      await api(`/api/sessions/${sessionId}/tests`, { method: "POST" });
      await loadApprovals();
      setPanel("tests");
    } catch (cause) {
      setError(cause.message);
    }
  };

  const showDiff = async () => {
    try {
      const result = await api(`/api/sessions/${sessionId}/git/diff`);
      setGitDiff(result.is_git_repo ? result.diff : result.error || "This workspace is not a Git repository.");
      setPanel("diff");
    } catch (cause) {
      setError(cause.message);
    }
  };

  const search = async (event) => {
    event.preventDefault();
    if (!searchText.trim() || !sessionId) return;
    try {
      const result = await api(`/api/sessions/${sessionId}/search?q=${encodeURIComponent(searchText)}`);
      setSearchResults(result.matches);
    } catch (cause) {
      setError(cause.message);
    }
  };

  const proposeDelete = async () => {
    if (!activePath || !window.confirm(`Request approval to delete ${activePath}?`)) return;
    try {
      await api(`/api/sessions/${sessionId}/file-delete`, {
        method: "POST",
        body: JSON.stringify({ path: activePath }),
      });
      await loadApprovals();
    } catch (cause) {
      setError(cause.message);
    }
  };

  const createFile = async () => {
    const path = window.prompt("New workspace-relative file path:");
    if (!path?.trim()) return;
    setActivePath(path);
    setTabs((current) => (current.includes(path) ? current : [...current, path]));
    setEditorValue("");
    setFileHash("");
    setDocuments((current) => ({ ...current, [path]: { content: "", savedContent: "", hash: "" } }));
    setNotice("Enter file contents, then use Save. The file is created only after approval.");
  };

  const closeTab = (path, event) => {
    event.stopPropagation();
    const nextTabs = tabs.filter((tab) => tab !== path);
    setTabs(nextTabs);
    if (activePath === path) {
      const next = nextTabs.at(-1) || "";
      setActivePath(next);
      if (next) openFile(next);
      else {
        setEditorValue("");
        setFileHash("");
      }
    }
  };

  const tree = useMemo(() => makeTree(searchResults ? searchResults.map((item) => item.path) : files), [files, searchResults]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Code2 size={17} /></div>
          <span>DevPilot</span><span className="brand-tag">ENGINEERING WORKSPACE</span>
        </div>
        <div className="topbar-centre">
          <GitBranch size={14} />
          <span className="workspace-name">{workspacePath || "No workspace selected"}</span>
          <span className={`connection ${health}`}><span />{health === "online" ? "Backend connected" : health === "offline" ? "Backend offline" : "Connecting"}</span>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" title="Refresh workspace" aria-label="Refresh workspace" onClick={() => refreshSession(sessionId).catch((cause) => setError(cause.message))} disabled={!sessionId}><RefreshCw size={15} /></button>
          <button
            className="icon-button agent-panel-toggle"
            title="Toggle AI Agent panel"
            aria-label="Toggle AI Agent panel"
            aria-expanded={agentPanelOpen}
            onClick={() => {
              setAgentPanelOpen((open) => !open);
              setWorkspacePanelOpen(false);
            }}
          >
            <Activity size={15} />
          </button>
          <button
            className="icon-button workspace-panel-toggle"
            title="Toggle workspace panel"
            aria-label="Toggle workspace panel"
            aria-expanded={workspacePanelOpen}
            onClick={() => {
              setWorkspacePanelOpen((open) => !open);
              setAgentPanelOpen(false);
            }}
          >
            <Folder size={15} />
          </button>
          <div className="avatar">DP</div>
        </div>
      </header>

      <div className={`workbench ${agentPanelOpen ? "agent-panel-open" : ""} ${workspacePanelOpen ? "workspace-panel-open" : ""}`}>
        <aside className={`sidebar left-sidebar ${workspacePanelOpen ? "mobile-panel-open" : ""}`}>
          <section className="side-section workspace-section">
            <div className="section-heading">WORKSPACE</div>
            <form className="workspace-form" onSubmit={createSession}>
              <input value={workspaceInput} onChange={(event) => setWorkspaceInput(event.target.value)} placeholder="Paste project folder path…" aria-label="Workspace folder path" />
              <button type="submit" className="square-button" title="Open workspace" disabled={loading || !workspaceInput.trim()}><Plus size={16} /></button>
            </form>
            <div className="session-select">
              <Folder size={15} />
              <select value={sessionId} onChange={(event) => selectSession(event.target.value)} aria-label="Active coding session">
                <option value="">Select a workspace session</option>
                {sessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}
              </select>
              <ChevronDown size={14} />
            </div>
          </section>

          <section className="file-section">
            <div className="section-heading file-heading">
              <span>EXPLORER</span>
              <div>
                <button className="tiny-button" title="Create file (approval required)" onClick={createFile} disabled={!sessionId}><FilePlus2 size={14} /></button>
                <button className="tiny-button" title="Refresh file tree" aria-label="Refresh file tree" onClick={() => refreshSession(sessionId).catch((cause) => setError(cause.message))} disabled={!sessionId}><RefreshCw size={13} /></button>
              </div>
            </div>
            <form className="search-box" onSubmit={search}>
              <Search size={14} />
              <input aria-label="Search in workspace" value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search in workspace…" disabled={!sessionId} />
              {searchResults && <button type="button" className="tiny-button" onClick={() => setSearchResults(null)} title="Clear search"><X size={13} /></button>}
            </form>
            <div className="file-tree">
              {!sessionId && <div className="empty-note">Open a workspace to browse files.</div>}
              {searchResults && <div className="search-count">{searchResults.length} matching locations</div>}
              {Object.entries(tree).map(([name, node]) => (
                <TreeNode key={name} name={name} node={node} depth={0} activePath={activePath} onOpen={openFile} collapsed={collapsed} setCollapsed={setCollapsed} />
              ))}
            </div>
          </section>
          <section className="side-section recent-section">
            <div className="section-heading">RECENT SESSIONS</div>
            {sessions.slice(0, 5).map((session) => (
              <button className={`recent-item ${session.id === sessionId ? "selected" : ""}`} key={session.id} onClick={() => selectSession(session.id)}>
                <Circle size={7} fill={session.status === "running" ? "#57c991" : "transparent"} />
                <span>{session.title}</span>
                <span className={`status-dot ${session.status}`} />
              </button>
            ))}
            {!sessions.length && <div className="empty-note">No recent sessions yet.</div>}
          </section>
          <div className="sidebar-footer"><ShieldAlert size={13} /> Commands and file changes require approval</div>
        </aside>

        <main className="editor-column">
          <div className="editor-toolbar">
            <div className="tabs">
              {tabs.map((tab) => (
                <button className={`editor-tab ${tab === activePath ? "active" : ""}`} key={tab} onClick={() => openFile(tab)}>
                  <FileCode2 size={14} /><span>{tab.split("/").at(-1)}</span>
                  <span className="tab-dir">{tab.includes("/") ? tab.slice(0, tab.lastIndexOf("/")) : ""}</span>
                  <X size={13} className="tab-close" onClick={(event) => closeTab(tab, event)} />
                </button>
              ))}
              {!tabs.length && <div className="no-tabs">DevPilot editor</div>}
            </div>
            <div className="editor-actions">
              {activePath && <button className="toolbar-button danger-quiet" onClick={proposeDelete} title="Request file deletion"><Trash2 size={14} /></button>}
              {activePath && <span className={`save-status ${hasUnsavedChanges ? "unsaved" : "saved"}`} role="status">{hasUnsavedChanges ? "Unsaved changes" : "Saved"}</span>}
              <button className="toolbar-button" onClick={saveFile} disabled={!activePath || saving} title="Save through approval">
                {saving ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />} Save
              </button>
            </div>
          </div>
          {activePath ? (
            <Editor
              height="100%"
              path={activePath}
              language={languageFor(activePath)}
              theme="vs-dark"
              value={editorValue}
              onChange={(value) => {
                const content = value ?? "";
                setEditorValue(content);
                setDocuments((current) => ({
                  ...current,
                  [activePath]: { ...(current[activePath] || { savedContent: "", hash: "" }), content },
                }));
              }}
              onMount={(editor) => { editorRef.current = editor; }}
              options={{ fontSize: 13, minimap: { enabled: false }, scrollBeyondLastLine: false, wordWrap: "on", padding: { top: 16 }, automaticLayout: true }}
            />
          ) : (
            <div className="editor-empty">
              <div className="editor-empty-icon"><Code2 size={25} /></div>
              <h2>{sessionId ? "Select a file to begin" : "Your engineering workspace"}</h2>
              <p>{sessionId ? "Choose a file from Explorer or ask DevPilot to work on a task." : "Open a local project folder to inspect files, review changes, and work with the agent."}</p>
              {sessionId && <button className="primary-button" onClick={createFile}><FilePlus2 size={15} /> Create a file</button>}
            </div>
          )}
          <section className="bottom-panel">
            <div className="panel-tabs">
              <button className={panel === "terminal" ? "active" : ""} onClick={() => setPanel("terminal")}><Terminal size={14} /> TERMINAL</button>
              <button className={panel === "activity" ? "active" : ""} onClick={() => setPanel("activity")}><Activity size={14} /> ACTIVITY <span className="tab-count">{events.length}</span></button>
              <button className={panel === "diff" ? "active" : ""} onClick={showDiff}><GitCompareArrows size={14} /> GIT DIFF</button>
              <button className={panel === "tests" ? "active" : ""} onClick={() => setPanel("tests")}><Play size={13} /> TESTS</button>
              <div className="panel-tools">
                <button className="toolbar-button" onClick={runTests} disabled={!sessionId || loading}><Play size={13} /> Run tests</button>
                <button className="tiny-button" title="Clear visible events" onClick={() => setEvents([])}><Trash2 size={13} /></button>
              </div>
            </div>
            <div className="panel-content">
              {panel === "diff" && <DiffView value={gitDiff} status={gitStatus} />}
              {panel === "activity" && <EventList events={events} endRef={eventEndRef} />}
              {panel === "terminal" && <TerminalView events={events} />}
              {panel === "tests" && <TestView events={events} />}
            </div>
          </section>
        </main>

        <aside className={`sidebar right-sidebar ${agentPanelOpen ? "mobile-panel-open" : ""}`}>
          <section className="agent-header">
            <div className="agent-title"><div className="agent-pulse"><Activity size={14} /></div><div><strong>AI Agent</strong><span>{health === "online" ? "Powered by your configured model" : "Connect the backend to start a task"}</span></div></div>
            <span className={`run-state ${activeTask ? "running" : ""}`}>{activeTask ? <><LoaderCircle size={12} className="spin" /> Working</> : <><Circle size={7} /> Ready</>}</span>
          </section>
          <section className="agent-config">
            <label htmlFor="model-name">MODEL OVERRIDE <span>optional</span></label>
            <input id="model-name" value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="Uses backend DEVPILOT_MODEL_NAME" disabled={Boolean(activeTask)} />
          </section>
          <div className="agent-content">
            <div className="chat-welcome">
              <div className="welcome-icon"><Code2 size={17} /></div>
              <div><strong>What should we build?</strong><p>Describe a coding task. DevPilot will inspect the project, share its steps, and request approval before each terminal action.</p></div>
            </div>
            {tasks.slice(0, 4).map((task) => (
              <div className="task-card" key={task.id}>
                <div className="task-card-title"><span className={`task-status ${task.status}`} />{task.status.toUpperCase()}</div>
                <div className="task-card-text">{task.task}</div>
                {events
                  .filter((event) => event.task_id === task.id && (
                    (event.type === "agent_message" && event.payload.content)
                    || (event.type === "task_finished" && event.payload.submission)
                    || (event.type === "task_error" && event.payload.error)
                  ))
                  .slice(-4)
                  .map((event) => (
                    <div className={event.type === "agent_message" ? "agent-update" : "task-outcome"} key={event.id}>
                      <span>{event.type === "agent_message" ? "DEVPILOT" : event.type === "task_error" ? "ERROR" : "RESULT"}</span>
                      <p>{event.type === "agent_message" ? event.payload.content : event.payload.submission || event.payload.error}</p>
                    </div>
                  ))}
              </div>
            ))}
            {approvals.length > 0 && (
              <div className="approval-section">
                <div className="approval-heading"><ShieldAlert size={14} /> ACTIONS NEED APPROVAL <span>{approvals.length}</span></div>
                {approvals.map((approval) => <ApprovalCard key={approval.id} approval={approval} onResolve={resolveApproval} />)}
              </div>
            )}
          </div>
          <form className="chat-compose" onSubmit={submitTask}>
            <textarea aria-label="Coding task" value={taskInput} onChange={(event) => setTaskInput(event.target.value)} onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); }
            }} placeholder={sessionId ? "Describe your coding task…" : "Open a workspace to start"} disabled={!sessionId || Boolean(activeTask)} rows={3} />
            <div className="compose-footer"><span><Command size={12} /> Enter to send · Shift+Enter for newline</span><button type="submit" className="send-button" aria-label="Start coding task" disabled={!sessionId || !taskInput.trim() || loading || Boolean(activeTask)} title="Start task"><Send size={15} /></button></div>
          </form>
          <section className="agent-progress">
            <div className="section-heading">TASK PROGRESS</div>
            {activeTask ? <div className="progress-row"><LoaderCircle size={14} className="spin" /><div><strong>Agent execution in progress</strong><span>Waiting for model output or your approval</span></div><button className="toolbar-button" onClick={() => cancelTask(activeTask)} disabled={cancellingTaskId === activeTask.id}><Square size={13} />{cancellingTaskId === activeTask.id ? "Stopping…" : "Stop"}</button></div>
              : tasks[0] ? <div className="progress-row"><Check size={14} /><div><strong>Latest task: {tasks[0].status}</strong><span>{tasks[0].task}</span></div></div>
                : <div className="empty-note">No active tasks.</div>}
          </section>
        </aside>
      </div>

      <footer className="statusbar">
        <div><span className="status-branch"><GitBranch size={12} /> {gitStatus?.is_git_repo ? "Git workspace" : "No Git repository"}</span><span>{gitStatus?.changed_files?.length || 0} changed files</span></div>
        <div><span>{activePath ? languageFor(activePath) : "Ready"}</span><span>UTF-8</span><span>DevPilot 0.1</span></div>
      </footer>

      {(error || notice) && <div className={`toast ${error ? "error" : "success"}`} role={error ? "alert" : "status"}><span>{error ? <AlertCircle size={15} /> : <Check size={15} />}{error || notice}</span><button onClick={() => { setError(""); setNotice(""); }} aria-label="Dismiss notification"><X size={14} /></button></div>}
    </div>
  );
}

function makeTree(paths) {
  const root = {};
  for (const path of paths) {
    const parts = path.split("/");
    let node = root;
    parts.forEach((part, index) => {
      node[part] ??= { children: {}, path: index === parts.length - 1 ? path : null };
      if (index < parts.length - 1) node = node[part].children;
    });
  }
  return root;
}

function TreeNode({ name, node, depth, activePath, onOpen, collapsed, setCollapsed }) {
  const isFolder = Object.keys(node.children).length > 0;
  const isCollapsed = collapsed[name + depth];
  return (
    <>
      <button className={`tree-row ${node.path === activePath ? "active" : ""}`} style={{ paddingLeft: 10 + depth * 14 }} onClick={() => {
        if (isFolder) setCollapsed((state) => ({ ...state, [name + depth]: !state[name + depth] }));
        else if (node.path) onOpen(node.path);
      }}>
        {isFolder ? (isCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />) : <FileCode2 size={13} />}
        {isFolder ? <Folder size={13} className="folder-icon" /> : <span className="tree-indent" />}
        <span>{name}</span>
      </button>
      {isFolder && !isCollapsed && Object.entries(node.children).map(([child, childNode]) => (
        <TreeNode key={`${name}/${child}`} name={child} node={childNode} depth={depth + 1} activePath={activePath} onOpen={onOpen} collapsed={collapsed} setCollapsed={setCollapsed} />
      ))}
    </>
  );
}

function ApprovalCard({ approval, onResolve }) {
  const command = approval.details.command;
  const label = {
    command: "Terminal command",
    dependency_install: "Dependency installation",
    file_write: approval.details.new_file ? "Create file" : "Modify file",
    file_delete: "Destructive file deletion",
    test_run: "Run automated tests",
    code_execution: "Code execution",
  }[approval.kind] || "Action";
  return (
    <article className={`approval-card ${approval.kind === "file_delete" ? "destructive" : ""}`}>
      <div className="approval-card-top"><span><ShieldAlert size={13} />{label}</span><span className="pending-pill">PENDING</span></div>
      <code className="approval-command">{command || approval.details.path}</code>
      {approval.details.path && command && <span className="approval-path">{approval.details.path}</span>}
      {approval.details.explanation && <p>{approval.details.explanation}</p>}
      <div className="approval-actions"><button onClick={() => onResolve(approval, false)}><X size={13} /> Reject</button><button className="approve-button" onClick={() => onResolve(approval, true)}><Check size={13} /> Approve</button></div>
    </article>
  );
}

function EventList({ events, endRef }) {
  if (!events.length) return <div className="panel-empty"><Activity size={18} /><span>Agent actions and tool results will appear here.</span></div>;
  return <div className="event-list">{events.slice(-200).map((event) => <EventRow key={event.id} event={event} />)}<div ref={endRef} /></div>;
}

function EventRow({ event }) {
  const icons = {
    task_started: <Play size={13} />,
    task_finished: <Check size={13} />,
    task_error: <AlertCircle size={13} />,
    command_proposed: <Terminal size={13} />,
    command_result: <Command size={13} />,
    approval_required: <ShieldAlert size={13} />,
    file_changed: <FileCode2 size={13} />,
    test_result: <Play size={13} />,
  };
  const detail = event.payload.command || event.payload.task || event.payload.path || event.payload.error || event.payload.submission || event.payload.status || JSON.stringify(event.payload);
  return <div className={`event-row ${event.type}`}><div className="event-icon">{icons[event.type] || <Clock3 size={13} />}</div><div className="event-body"><div className="event-title">{event.type.replaceAll("_", " ")}</div><pre>{String(detail).slice(0, 1000)}</pre>{event.payload.output && <pre className="event-output">{event.payload.output.slice(0, 4000)}</pre>}</div><time>{new Date(event.created_at * 1000).toLocaleTimeString()}</time></div>;
}

function TerminalView({ events }) {
  const entries = events.filter((event) => ["command_result", "command_rejected"].includes(event.type)).slice(-30);
  if (!entries.length) return <div className="panel-empty"><Terminal size={18} /><span>Approved command output appears here. DevPilot never exposes an unrestricted shell.</span></div>;
  return <div className="terminal-output">{entries.map((event) => (
    <div className="terminal-entry" key={event.id}><div className="terminal-command"><span className="terminal-prompt">$</span> {event.payload.command}</div><pre>{event.payload.output || event.payload.reason || "No output"}</pre><div className="terminal-meta">{event.type === "command_rejected" ? "blocked by policy" : `exit code ${event.payload.returncode}`}{event.payload.exception_info ? ` · ${event.payload.exception_info}` : ""}</div></div>
  ))}</div>;
}

function TestView({ events }) {
  const results = events.filter((event) => event.type === "test_result");
  if (!results.length) return <div className="panel-empty"><Play size={18} /><span>Use “Run tests” to request approval and run python -m pytest in the workspace.</span></div>;
  return <div className="test-results">{results.slice(-10).reverse().map((event) => (
    <article key={event.id} className="test-result"><div className={`test-result-heading ${event.payload.status}`}><span>{event.payload.status}</span><span>exit {event.payload.returncode}</span></div><pre>{event.payload.output}</pre></article>
  ))}</div>;
}

function DiffView({ value, status }) {
  return <div className="diff-view"><div className="diff-heading"><GitCompareArrows size={14} /> Actual workspace diff {status?.changed_files?.length ? `· ${status.changed_files.length} changed files` : ""}</div>{value ? <pre>{value}</pre> : <div className="panel-empty">No tracked Git changes to display.</div>}</div>;
}

export default App;
